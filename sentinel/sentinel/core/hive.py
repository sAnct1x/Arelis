"""SwarmHive — Central Coordinator for Spawning, Scaling, Upgrading, and Commanding Sentinels."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import platform
import time
from pathlib import Path
from typing import Any

import psutil

from sentinel.castes import (
    CasteDescriptor,
    CasteHandler,
    CasteRegistry,
    DynamicCasteHandler,
    HarvesterCaste,
    SanitizerCaste,
    TripwireCaste,
    WardenCaste,
    build_default_caste_registry,
)
from sentinel.config import load_config, resolve_theme, save_local_preferences
from sentinel.core.authority import ACTION_BLAST_MAP, AuthorityGate
from sentinel.core.bus import EventBus, EventTopic
from sentinel.core.deception import DeceptionCoordinator
from sentinel.core.emp import EMPController, load_emp_flag
from sentinel.core.fsm import (
    CASTE_ORBIT_PROFILES,
    SentinelState,
    SentinelUnit,
    WorldNode,
    register_caste_profile,
    resolve_tier,
    unregister_caste_profile,
)
from sentinel.core.receipts import ReceiptLedger
from sentinel.core.simulator import SCENARIO_CATALOG, SimulationDirector
from sentinel.core.telemetry import TelemetryLogger
from sentinel.paths import harvest_dir, quarantine_dir
from sentinel.safety.network import SEND_ACT_OPS, check_send_allowed

log = logging.getLogger("sentinel.hive")


class SwarmHive:
    """Sovereign Swarm Coordinator controlled by Arelis and observed via the 3D Overseer."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        bus: EventBus | None = None,
        ledger: ReceiptLedger | None = None,
        registry: CasteRegistry | None = None,
        telemetry: TelemetryLogger | None = None,
        authority: AuthorityGate | None = None,
    ) -> None:
        self.config = config if config is not None else load_config()
        ret_cfg = self.config.get("retention") or {}
        max_log_b = int(ret_cfg.get("max_log_bytes", 5_242_880))
        max_log_bk = int(ret_cfg.get("max_log_backups", 2))
        max_ledger_n = int(ret_cfg.get("max_ledger_entries", 5000))

        self.bus = bus or EventBus()
        self.ledger = ledger or ReceiptLedger(max_disk_entries=max_ledger_n)
        self.telemetry = telemetry or TelemetryLogger(max_file_bytes=max_log_b, max_backups=max_log_bk)
        self.registry = registry or build_default_caste_registry(self.config)
        # Load before any units spawn so a restart on this data dir stays stopped.
        self.emp = EMPController(self.bus, tripped=load_emp_flag())
        self.authority = authority or AuthorityGate()
        self.deception = DeceptionCoordinator(bus=self.bus, ledger=self.ledger)
        self.simulator = SimulationDirector(self)



        # Register harvester HTTP client closer with EMP controller
        with contextlib.suppress(KeyError):
            hrv = self.registry.get("harvester")
            if isinstance(hrv, HarvesterCaste):
                self.emp.register_closer(hrv.close)

        swarm_cfg = self.config.get("swarm") or {}
        self.max_total_units = int(swarm_cfg.get("max_total_units", 64))
        self.auto_scale = bool(swarm_cfg.get("auto_scale", True))
        self.default_tier = str(swarm_cfg.get("default_tier", "mk1"))

        ui_cfg = self.config.get("ui") or {}
        self._theme = resolve_theme(str(ui_cfg.get("theme", "sodium")))

        self.units: dict[str, SentinelUnit] = {}
        self.nodes: dict[str, WorldNode] = {}
        self._unit_counters: dict[str, int] = {}
        self._mission_counter = 0
        self._patrol_tick = 0
        self._kinematics_task: asyncio.Task[Any] | None = None
        self._telemetry_task: asyncio.Task[Any] | None = None
        self._running = False

        # Prime psutil CPU counter and initialize real Bastion + Merkle 3D nodes
        with contextlib.suppress(psutil.Error, OSError):
            psutil.cpu_percent(interval=None)

        with contextlib.suppress(KeyError):
            wrd = self.registry.get("warden")
            if isinstance(wrd, WardenCaste):
                wrd._authorize_work = self._authorize_work
                self.nodes.update(wrd.create_bastion_nodes())
                wrd.sync_bastion_nodes(self.nodes)

        with contextlib.suppress(KeyError):
            trp = self.registry.get("tripwire")
            if isinstance(trp, TripwireCaste):
                trp.sync_merkle_nodes(self.nodes)

        self.host_telemetry: dict[str, Any] = self._collect_host_telemetry()
        self._pending_merkle_verdict: dict[str, Any] | None = None

        # Spawn initial pools per caste
        initial_pools = swarm_cfg.get("initial_pools") or {
            "harvester": 8,
            "warden": 6,
            "sanitizer": 4,
            "tripwire": 4,
        }
        for caste_id, count in initial_pools.items():
            if caste_id in self.registry.caste_ids:
                self.spawn_units(caste_id, int(count), tier=self.default_tier)

        self._trim_runtime_storage()

        self.telemetry.record(
            "INFO",
            unit_id="HIVE-CORE",
            caste="core",
            phase="BOOT",
            message=(
                f"Sentinel Hive initialized: {len(self.units)} autonomous units online across "
                f"{len(self.registry.caste_ids)} narrow castes; {len(self.nodes)} live OS Bastion & Merkle nodes armed."
            ),
        )

    def _authorize_work(
        self,
        action_token: str,
        target_identifier: str,
        justification: str,
    ) -> dict[str, Any] | None:
        """Shared live-path gate. None means run. A dict means parked for sign-off.

        Scale, ban, and prune go through check_send_allowed first, then the gate.
        """
        token = action_token.strip().upper()
        if token in SEND_ACT_OPS:
            verdict = check_send_allowed(token, url=target_identifier)
            if not verdict.allowed:
                return {
                    "ok": False,
                    "parked": True,
                    "error": verdict.reason or "queued for operator sign-off",
                }
            action_token = verdict.token or token
        allowed, req = self.authority.evaluate_request(
            action_token,
            target_identifier,
            justification,
        )
        if allowed:
            return None
        return {
            "ok": False,
            "parked": True,
            "error": "queued for operator sign-off",
            "request_id": req.request_id,
            "action_token": req.action_token,
            "pending_approval": req.model_dump(),
        }

    def _token_for_task(self, caste: str, task_payload: dict[str, Any]) -> tuple[str, str]:
        """Map a live task to a blast-map token. Unknown explicit tokens stay unknown."""
        explicit = str(task_payload.get("action_token") or "").strip().upper()
        raw = str(task_payload.get("action") or task_payload.get("capability") or "").strip().upper()
        token = explicit or raw
        target = str(
            task_payload.get("path")
            or task_payload.get("target")
            or task_payload.get("url")
            or task_payload.get("ip")
            or task_payload.get("source")
            or caste
        )
        if token in ACTION_BLAST_MAP:
            return token, target
        if explicit:
            return explicit, target
        return "INSPECT_PATH", target

    def _trim_runtime_storage(
        self,
        *,
        max_harvests: int | None = None,
        max_quarantines: int | None = None,
        max_log_bytes: int | None = None,
        max_ledger_entries: int | None = None,
    ) -> dict[str, Any]:
        """Cap harvest, quarantine, logs, and ledger. Startup housekeeping. Not gated."""
        ret_cfg = self.config.get("retention") or {}
        mh = max_harvests if max_harvests is not None else int(ret_cfg.get("max_harvest_dossiers", 25))
        mq = max_quarantines if max_quarantines is not None else int(ret_cfg.get("max_quarantine_files", 25))
        mlb = max_log_bytes if max_log_bytes is not None else int(ret_cfg.get("max_log_bytes", 5_242_880))
        mle = max_ledger_entries if max_ledger_entries is not None else int(ret_cfg.get("max_ledger_entries", 5000))

        removed_harvests: list[str] = []
        with contextlib.suppress(KeyError):
            hrv = self.registry.get("harvester")
            if isinstance(hrv, HarvesterCaste):
                removed_harvests = hrv.prune_harvest_dossiers(max_keep=mh)

        removed_quarantines: list[str] = []
        with contextlib.suppress(KeyError):
            san = self.registry.get("sanitizer")
            if isinstance(san, SanitizerCaste):
                removed_quarantines = san.prune_quarantine_files(max_keep=mq)

        log_summary = self.telemetry.prune_disk_logs(max_bytes=mlb)
        ledger_pruned = self.ledger.compact_disk_ledger(max_entries=mle)

        return {
            "ok": True,
            "pruned_harvests": removed_harvests,
            "pruned_quarantines": removed_quarantines,
            "rotated_logs": log_summary.get("rotated", []),
            "removed_log_backups": log_summary.get("removed_backups", []),
            "compacted_ledger_receipts": ledger_pruned,
        }

    def prune_runtime_storage(
        self,
        *,
        max_harvests: int | None = None,
        max_quarantines: int | None = None,
        max_log_bytes: int | None = None,
        max_ledger_entries: int | None = None,
    ) -> dict[str, Any]:
        """Operator prune. Tier 2. Parks until sign-off."""
        parked = self._authorize_work(
            "DELETE_QUARANTINE_FILE",
            "runtime-storage",
            "prune harvest, quarantine, logs, and ledger",
        )
        if parked is not None:
            return parked
        return self._trim_runtime_storage(
            max_harvests=max_harvests,
            max_quarantines=max_quarantines,
            max_log_bytes=max_log_bytes,
            max_ledger_entries=max_ledger_entries,
        )

    @property
    def theme(self) -> dict[str, Any]:
        return dict(self._theme)

    async def set_theme(self, theme_id: str) -> dict[str, Any]:
        self._theme = resolve_theme(theme_id)
        with contextlib.suppress(OSError):
            save_local_preferences(theme=str(self._theme.get("id", "sodium")))
        await self.bus.publish(EventTopic.THEME_CHANGED, self._theme)
        return self._theme

    def spawn_unit(self, caste: str, *, tier: str | None = None) -> SentinelUnit:
        """Spawn a single narrow-caste Sentinel unit into orbital patrol formation."""
        cid = caste.strip().lower()
        handler = self.registry.get(cid)
        if len(self.units) >= self.max_total_units:
            raise RuntimeError(
                f"Swarm capacity reached ({self.max_total_units} units). Retire or scale down first."
            )

        seq = self._unit_counters.get(cid, 0) + 1
        self._unit_counters[cid] = seq
        prefix = handler.descriptor.code_prefix
        unit_id = f"SNT-{prefix}-{seq:03d}"

        spec = resolve_tier(tier or self.default_tier)
        profile = CASTE_ORBIT_PROFILES.get(
            cid,
            {
                "radius": handler.descriptor.orbit_radius,
                "y_band": handler.descriptor.orbit_y_band,
                "speed_mult": handler.descriptor.speed_mult,
            },
        )
        angle = ((seq - 1) * 0.785398) % (math.pi * 2.0)
        phase = (seq * 1.37) % (math.pi * 2.0)
        r = profile["radius"]
        pos = [
            math.cos(angle) * r,
            profile["y_band"] + math.sin(phase) * 2.0,
            math.sin(angle) * r,
        ]
        vel = [-math.sin(angle) * 8.0, 0.0, math.cos(angle) * 8.0]

        unit = SentinelUnit(
            unit_id=unit_id,
            caste=cid,
            tier=spec.tier,
            version=handler.descriptor.version,
            state=SentinelState.EMP_DISABLED if self.emp.is_tripped else SentinelState.PATROLLING,
            doctrine=handler.descriptor.doctrine,
            position=pos,
            velocity=vel,
            orbit_angle=angle,
            orbit_phase=phase,
            current_task=f"Patrolling {cid} sector",
            orb_color=handler.descriptor.eye_color,
        )
        self.units[unit_id] = unit
        self.bus.publish_nowait(EventTopic.UNIT_SPAWNED, unit.to_dict())
        return unit

    def register_caste(
        self,
        handler: CasteHandler,
        *,
        initial_pool: int = 0,
        tier: str | None = None,
    ) -> dict[str, Any]:
        """Dynamically register a new or upgraded Sentinel Caste into the Hive."""
        parked = self._authorize_work(
            "SCALE_CASTE",
            handler.descriptor.caste_id,
            "register caste",
        )
        if parked is not None:
            return parked
        self.registry.register(handler)
        d = handler.descriptor
        register_caste_profile(
            d.caste_id,
            radius=d.orbit_radius,
            y_band=d.orbit_y_band,
            speed_mult=d.speed_mult,
            doctrine=d.doctrine,
        )
        spawned: list[str] = []
        if initial_pool > 0:
            units = self.spawn_units(d.caste_id, initial_pool, tier=tier or self.default_tier)
            spawned = [u.unit_id for u in units]

        self.bus.publish_nowait(EventTopic.CASTE_REGISTERED, d.to_dict())
        self.telemetry.record(
            "INFO",
            unit_id="HIVE-CORE",
            caste=d.caste_id,
            phase="CASTE REGISTERED",
            message=f"Registered custom Sentinel Caste {d.caste_id.upper()} ({d.title}) with {len(spawned)} initial units.",
            details={
                "caste_id": d.caste_id,
                "capabilities": sorted(d.allowed_capabilities),
                "spawned": spawned,
            },
        )
        res = d.to_dict()
        res["spawned_units"] = spawned
        return res

    def register_dynamic_caste(
        self,
        *,
        caste_id: str,
        code_prefix: str,
        title: str,
        single_purpose: str,
        allowed_capabilities: list[str] | frozenset[str],
        version: str = "1.0.0",
        orbit_radius: float = 20.0,
        orbit_y_band: float = 0.0,
        speed_mult: float = 1.0,
        eye_color: str = "#00e5ff",
        laser_kind: str = "harvest",
        doctrine: str = "HUNTER-SEEKER",
        rules: list[dict[str, Any]] | None = None,
        initial_pool: int = 0,
        tier: str | None = None,
    ) -> dict[str, Any]:
        """Create and register a declarative custom Sentinel Caste on behalf of Arelis."""
        desc = CasteDescriptor(
            caste_id=caste_id.strip().lower(),
            code_prefix=code_prefix.strip().upper(),
            title=title.strip(),
            single_purpose=single_purpose.strip(),
            allowed_capabilities=frozenset(allowed_capabilities),
            version=version,
            orbit_radius=float(orbit_radius),
            orbit_y_band=float(orbit_y_band),
            speed_mult=float(speed_mult),
            eye_color=eye_color,
            laser_kind=laser_kind,
            doctrine=doctrine,
        )
        handler = DynamicCasteHandler(desc, rules=rules)
        return self.register_caste(handler, initial_pool=initial_pool, tier=tier)

    def unregister_caste(self, caste_id: str) -> dict[str, Any]:
        """Retire all units of a caste and unregister it from the swarm."""
        cid = caste_id.strip().lower()
        if cid in {"harvester", "warden", "sanitizer", "tripwire"}:
            raise ValueError(f"Core Sentinel caste {cid!r} cannot be unregistered.")

        # Retire active units
        retired: list[str] = []
        for u in list(self.units.values()):
            if u.caste == cid and self.retire_unit(u.unit_id):
                retired.append(u.unit_id)


        ok = self.registry.unregister(cid)
        unregister_caste_profile(cid)
        if ok:
            self.bus.publish_nowait(EventTopic.CASTE_UNREGISTERED, {"caste_id": cid, "retired": retired})
            self.telemetry.record(
                "INFO",
                unit_id="HIVE-CORE",
                caste=cid,
                phase="CASTE UNREGISTERED",
                message=f"Unregistered Sentinel Caste {cid.upper()} and retired {len(retired)} units.",
                details={"caste_id": cid, "retired": retired},
            )
        return {"ok": ok, "caste_id": cid, "retired_units": retired}


    def spawn_units(self, caste: str, count: int, *, tier: str | None = None) -> list[SentinelUnit]:
        spawned: list[SentinelUnit] = []
        for _ in range(max(0, int(count))):
            if len(self.units) >= self.max_total_units:
                break
            spawned.append(self.spawn_unit(caste, tier=tier))
        return spawned

    def retire_unit(self, unit_id: str) -> bool:
        unit = self.units.pop(unit_id, None)
        if unit is None:
            return False
        self.bus.publish_nowait(EventTopic.UNIT_RETIRED, {"unit_id": unit_id, "caste": unit.caste})
        return True

    def upgrade_unit(
        self,
        unit_id: str,
        tier: str,
        *,
        version: str | None = None,
    ) -> SentinelUnit:
        if unit_id not in self.units:
            raise KeyError(f"Unknown Sentinel unit_id: {unit_id!r}")
        unit = self.units[unit_id]
        unit.upgrade(tier, new_version=version)
        self.bus.publish_nowait(EventTopic.UNIT_UPGRADED, unit.to_dict())
        return unit

    def upgrade_caste(
        self,
        caste: str,
        tier: str,
        *,
        version: str | None = None,
    ) -> list[dict[str, Any]]:
        cid = caste.strip().lower()
        upgraded: list[dict[str, Any]] = []
        for u in self.units.values():
            if u.caste == cid:
                u.upgrade(tier, new_version=version)
                d = u.to_dict()
                upgraded.append(d)
                self.bus.publish_nowait(EventTopic.UNIT_UPGRADED, d)
        return upgraded

    def upgrade_swarm(self, tier: str, *, caste: str | None = None) -> dict[str, Any]:
        """Upgrade all units (or a specific caste) to MK1 (8T), MK2 (10T), or MK3 (12T) and persist default tier."""
        spec = resolve_tier(tier)
        self.default_tier = spec.tier
        with contextlib.suppress(OSError):
            save_local_preferences(default_tier=spec.tier)

        upgraded_ids: list[str] = []
        target_caste = (caste or "all").strip().lower()
        for u in self.units.values():
            if target_caste in {"all", ""} or u.caste == target_caste:
                u.upgrade(spec.tier)
                upgraded_ids.append(u.unit_id)
                self.bus.publish_nowait(EventTopic.UNIT_UPGRADED, u.to_dict())

        self.telemetry.record(
            "INFO",
            unit_id="HIVE-CORE",
            caste="core",
            phase="VISUAL MODEL CHANGED",
            message=(
                f"Changed visual model for {len(upgraded_ids)} Sentinel units ({target_caste.upper()}) to "
                f"{spec.tier.upper()} ({spec.tentacles} IK tentacles, speed={spec.max_speed:.1f})."
            ),
            details={"tier": spec.tier, "tentacles": spec.tentacles, "count": len(upgraded_ids)},
        )
        return {
            "ok": True,
            "tier": spec.tier,
            "tentacles": spec.tentacles,
            "upgraded_count": len(upgraded_ids),
        }

    def scale_caste(self, caste: str, target_count: int, *, tier: str | None = None) -> dict[str, Any]:
        cid = caste.strip().lower()
        parked = self._authorize_work("SCALE_CASTE", cid, f"scale caste to {target_count}")
        if parked is not None:
            return parked
        self.registry.get(cid)
        target = max(0, min(int(target_count), self.max_total_units))
        current = [u for u in self.units.values() if u.caste == cid]
        diff = target - len(current)
        spawned_ids: list[str] = []
        retired_ids: list[str] = []

        if diff > 0:
            new_units = self.spawn_units(cid, diff, tier=tier)
            spawned_ids = [u.unit_id for u in new_units]
        elif diff < 0:
            # Prefer retiring idle PATROLLING/DOCKED units first
            idle = [u for u in current if u.state in {SentinelState.PATROLLING, SentinelState.DOCKED}]
            candidates = idle + [u for u in current if u not in idle]
            for u in candidates[: abs(diff)]:
                if self.retire_unit(u.unit_id):
                    retired_ids.append(u.unit_id)

        res = {
            "ok": True,
            "caste": cid,
            "count": sum(1 for u in self.units.values() if u.caste == cid),
            "spawned": spawned_ids,
            "retired": retired_ids,
        }
        self.telemetry.record(
            "INFO",
            unit_id="HIVE-CORE",
            caste=cid,
            phase="SWARM SCALE",
            message=(
                f"Scaled {cid.upper()} caste to {res['count']} units "
                f"(+{len(spawned_ids)} spawned, -{len(retired_ids)} retired)."
            ),
            details=res,
        )
        return res

    def scale_caste_delta(self, caste: str, delta: int) -> dict[str, Any]:
        """Increment or decrement a caste pool by delta (+1 / -1) from the Overseer HUD."""
        cid = caste.strip().lower()
        current_count = sum(1 for u in self.units.values() if u.caste == cid)
        target = max(1, min(current_count + int(delta), self.max_total_units))
        return self.scale_caste(cid, target, tier=self.default_tier)

    def heal_tripwire_roots(self) -> dict[str, Any]:
        """Retired command: runtime source rollback is not an operational control."""
        return {"ok": False, "error": "Self-heal has been removed. Use an integrity inspection; restore source through a reviewed versioned change."}

    async def neutralize_target(self, **kwargs: Any) -> dict[str, Any]:
        """Retired visual action: deleting a node cannot establish containment."""
        return {"ok": False, "neutralized": False, "error": "Visual neutralization is disabled. Inspect the finding and use an explicit application policy operation."}

    def _acquire_unit(self, caste: str, preferred_id: str | None = None) -> SentinelUnit:
        if self.emp.is_tripped:
            raise RuntimeError("EMP Kill-Switch is currently active. Restore swarm before dispatching.")
        cid = caste.strip().lower()
        if preferred_id and preferred_id in self.units:
            u = self.units[preferred_id]
            if u.caste != cid:
                raise ValueError(f"Unit {preferred_id} belongs to caste {u.caste}, not {cid}")
            return u

        # Pick an idle unit in PATROLLING state that is not already a wingman in another pack
        for u in self.units.values():
            if u.caste == cid and u.state == SentinelState.PATROLLING and u.pack_role == "SOLO":
                return u

        # Auto-scale if allowed and under max capacity
        if self.auto_scale and len(self.units) < self.max_total_units:
            return self.spawn_unit(cid, tier=self.default_tier)

        # Fallback to any unit of that caste
        for u in self.units.values():
            if u.caste == cid:
                return u

        return self.spawn_unit(cid, tier=self.default_tier)

    def _recruit_pack(self, alpha: SentinelUnit, *, max_wingmen: int = 2) -> list[SentinelUnit]:
        """Group same-caste patrolling units into a pack around Alpha and share its doctrine label."""
        pack_id = f"PACK-{alpha.unit_id}-{int(time.monotonic() * 1000) % 100000}"
        alpha.pack_id = pack_id
        alpha.pack_role = "ALPHA"
        alpha.pack_slot = 0

        wingmen: list[SentinelUnit] = []
        for u in self.units.values():
            if len(wingmen) >= max_wingmen:
                break
            if (
                u.unit_id != alpha.unit_id
                and u.caste == alpha.caste
                and u.state == SentinelState.PATROLLING
                and u.pack_role == "SOLO"
            ):
                wingmen.append(u)

        total_pack = 1 + len(wingmen)
        alpha.pack_size = total_pack
        for idx, w in enumerate(wingmen, start=1):
            w.pack_id = pack_id
            w.pack_role = "WINGMAN"
            w.pack_slot = idx
            w.pack_size = total_pack
        return wingmen

    def _release_pack(self, pack_id: str | None) -> None:
        """Release all units in a Sentinel Pack back to solo orbital patrol."""
        if not pack_id:
            return
        for u in self.units.values():
            if u.pack_id == pack_id:
                is_wingman = u.pack_role == "WINGMAN"
                u.pack_id = None
                u.pack_role = "SOLO"
                u.pack_slot = 0
                u.pack_size = 1
                if is_wingman and u.state != SentinelState.EMP_DISABLED:
                    u.transition(
                        SentinelState.PATROLLING,
                        task=f"Patrolling {u.caste} sector",
                        laser_active=False,
                        carrying_orb=False,
                    )

    def _sync_pack_wingmen(self) -> None:
        """Copy the alpha state, target, laser flag, and doctrine label onto wingmen."""
        alphas: dict[str, SentinelUnit] = {
            u.pack_id: u
            for u in self.units.values()
            if u.pack_id and u.pack_role == "ALPHA"
        }
        for u in self.units.values():
            if u.pack_role != "WINGMAN" or not u.pack_id:
                continue
            alpha = alphas.get(u.pack_id)
            if (
                alpha is None
                or alpha.state in {SentinelState.PATROLLING, SentinelState.DOCKED, SentinelState.EMP_DISABLED}
            ):
                u.pack_id = None
                u.pack_role = "SOLO"
                u.pack_slot = 0
                u.pack_size = 1
                if u.state != SentinelState.EMP_DISABLED:
                    u.transition(
                        SentinelState.PATROLLING,
                        task=f"Patrolling {u.caste} sector",
                        laser_active=False,
                        carrying_orb=False,
                    )
                continue

            u.state = alpha.state
            u.target_node_id = alpha.target_node_id
            u.target_position = list(alpha.target_position) if alpha.target_position else None
            u.laser_active = alpha.laser_active
            u.laser_target = list(alpha.laser_target) if alpha.laser_target else None
            u.laser_kind = alpha.laser_kind
            u.carrying_orb = alpha.carrying_orb
            u.doctrine = alpha.doctrine
            u.current_task = f"[{alpha.doctrine} PACK] Wingman -> {alpha.unit_id}"

    async def dispatch_task(
        self,
        caste: str,
        task_payload: dict[str, Any],
        *,
        unit_id: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch a narrow task to a Pack Alpha Sentinel + automatically recruited Swarm Wingmen."""
        if self.emp.is_tripped:
            return {"ok": False, "error": "EMP Kill-Switch active"}

        cid = caste.strip().lower()
        method = str(task_payload.get("method") or "").strip().upper()
        if method and method != "GET":
            send_url = str(
                task_payload.get("url")
                or task_payload.get("target")
                or task_payload.get("path")
                or ""
            )
            verdict = check_send_allowed(method, method=method, url=send_url)
            if not verdict.allowed:
                return {
                    "ok": False,
                    "parked": True,
                    "error": verdict.reason or "queued for operator sign-off",
                }
            if verdict.token:
                parked_send = self._authorize_work(
                    verdict.token,
                    send_url or cid,
                    f"send {method}",
                )
                if parked_send is not None:
                    return parked_send
        token, target = self._token_for_task(cid, task_payload)
        parked = self._authorize_work(token, target, f"dispatch {cid}")
        if parked is not None:
            return parked
        handler = self.registry.get(cid)
        unit = self._acquire_unit(cid, preferred_id=unit_id)
        desired_wingmen = 3 if cid in {"warden", "sanitizer"} else 2
        wingmen = self._recruit_pack(unit, max_wingmen=desired_wingmen)
        pack_id = unit.pack_id
        doctrine = unit.resolve_active_doctrine()

        action_label = str(
            task_payload.get("action")
            or task_payload.get("query")
            or task_payload.get("target")
            or task_payload.get("url")
            or cid
        )[:80]

        level_map = {
            "harvester": "HARVEST",
            "sanitizer": "SANITIZE",
            "warden": "WARDEN",
            "tripwire": "TRIPWIRE",
        }
        lvl = level_map.get(cid, "INFO")
        pack_tag = f"{1 + len(wingmen)}-Sentinel {doctrine} Pack ({unit.unit_id}" + (
            f" + {', '.join(w.unit_id for w in wingmen)})" if wingmen else ")"
        )

        self.telemetry.record(
            lvl,
            unit_id=unit.unit_id,
            caste=cid,
            phase=doctrine,
            message=f"{pack_tag} deployed for {cid}:{action_label}",
        )

        async def _run() -> dict[str, Any]:
            try:
                res = await handler.execute(
                    unit,
                    task_payload,
                    bus=self.bus,
                    ledger=self.ledger,
                    nodes=self.nodes,
                )
            finally:
                self._release_pack(pack_id)

            ok = bool(res.get("ok", not res.get("quarantined")))
            if res.get("quarantined"):
                self.telemetry.record(
                    "CRITICAL",
                    unit_id=unit.unit_id,
                    caste=cid,
                    phase="HUNTER-KILLER QUARANTINE",
                    message=f"Hostile payload surrounded & quarantined by {pack_tag} from {res.get('source', action_label)}",
                    details={"max_severity": res.get("max_severity")},
                )
            else:
                fail_phase = "HARVEST SOURCE WARN" if cid == "harvester" else "HUNTER-KILLER BLOCK"
                self.telemetry.record(
                    lvl if ok else ("WARN" if cid == "harvester" else "ALERT"),
                    unit_id=unit.unit_id,
                    caste=cid,
                    phase="PACK COMPLETE" if ok else fail_phase,
                    message=(
                        f"{pack_tag} finished {cid}:{action_label} "
                        f"(ok={ok}, title={str(res.get('title') or res.get('error') or res.get('status') or '')[:60]})"
                    ),
                )
            return res

        task = self.emp.track_task(asyncio.create_task(_run()))
        try:
            return await task
        except asyncio.CancelledError:
            self._release_pack(pack_id)
            return {"ok": False, "cancelled_by_emp": True, "unit_id": unit.unit_id}

    async def dispatch_harvest_swarm(
        self,
        question: str,
        targets: list[dict[str, Any]],
        *,
        save_report: bool = True,
        animate: bool = True,
        anim_scale: float = 1.0,
    ) -> dict[str, Any]:
        """Deploy a coordinated swarm of Harvester Sentinels in parallel across multiple targets."""
        if self.emp.is_tripped:
            return {"ok": False, "error": "EMP Kill-Switch active"}

        parked = self._authorize_work("INSPECT_PATH", question[:80], "harvest swarm")
        if parked is not None:
            return parked

        self._mission_counter += 1
        mission_id = f"MSN-{self._mission_counter:04d}"
        t0 = time.perf_counter()

        # Ensure enough Harvester units exist for parallel fan-out
        harvester_pool = [u for u in self.units.values() if u.caste == "harvester"]
        needed = min(len(targets), 16) - len(harvester_pool)
        if needed > 0 and self.auto_scale:
            self.spawn_units("harvester", needed, tier=self.default_tier)

        idle_harvesters = [
            u for u in self.units.values() if u.caste == "harvester" and u.state == SentinelState.PATROLLING
        ]
        all_harvesters = [u for u in self.units.values() if u.caste == "harvester"]
        pool = idle_harvesters if len(idle_harvesters) >= len(targets) else all_harvesters

        self.telemetry.record(
            "HARVEST",
            unit_id="HIVE-CORE",
            caste="harvester",
            phase=f"MISSION {mission_id}",
            message=f"Deploying {len(targets)}-target Harvest Swarm for: '{question[:90]}'",
        )

        await self.bus.publish(
            EventTopic.MISSION_STARTED,
            {
                "mission_id": mission_id,
                "question": question,
                "target_count": len(targets),
            },
        )

        coros = []
        for idx, item in enumerate(targets):
            assigned_unit = pool[idx % len(pool)] if pool else self.spawn_unit("harvester")
            payload = dict(item)
            payload.setdefault("animate", animate)
            payload.setdefault("anim_scale", anim_scale)
            coros.append(
                self.dispatch_task("harvester", payload, unit_id=assigned_unit.unit_id)
            )

        results = await asyncio.gather(*coros)
        elapsed_s = round(time.perf_counter() - t0, 3)

        report_path: str | None = None
        if save_report and results:
            hrv_handler = self.registry.get("harvester")
            if isinstance(hrv_handler, HarvesterCaste):
                saved = hrv_handler.save_harvest_report(question, list(results))
                report_path = str(saved)

        summary = {
            "ok": any(r.get("ok") for r in results),
            "mission_id": mission_id,
            "question": question,
            "elapsed_s": elapsed_s,
            "total_targets": len(targets),
            "succeeded": sum(1 for r in results if r.get("ok")),
            "quarantined": sum(1 for r in results if r.get("quarantined")),
            "failed": sum(1 for r in results if not r.get("ok") and not r.get("quarantined")),
            "report_path": report_path,
            "results": list(results),
            "arelis_warrants": [
                r["arelis_warrant"] for r in results if r.get("ok") and "arelis_warrant" in r
            ],
        }
        self.telemetry.record(
            "HARVEST",
            unit_id="HIVE-CORE",
            caste="harvester",
            phase=f"{mission_id} COMPLETE",
            message=(
                f"Mission {mission_id} finished in {elapsed_s}s: "
                f"{summary['succeeded']} retrieved, {summary['quarantined']} quarantined, "
                f"report={Path(report_path).name if report_path else 'none'}"
            ),
        )
        await self.bus.publish(
            EventTopic.MISSION_COMPLETED,
            {
                "mission_id": mission_id,
                "question": question,
                "elapsed_s": elapsed_s,
                "succeeded": summary["succeeded"],
                "quarantined": summary["quarantined"],
                "report_path": report_path,
            },
        )
        return summary


    async def trigger_emp(self, reason: str = "Overseer Manual EMP Kill-Switch") -> dict[str, Any]:
        self.simulator.clear_banner()
        res = await self.emp.trigger_emp(self.units, reason=reason)
        try:
            self.authority.evaluate_request("EMP_HALT", "swarm", reason)
        except Exception:
            log.warning("EMP halt lease record failed")
        self.telemetry.record(
            "EMP",
            unit_id="EMP-CORE",
            caste="core",
            phase="EMERGENCY HALT",
            message=(
                f"HARDWARE EMP TRIGGERED ({reason}): {res['tasks_cancelled']} tasks cancelled, "
                f"{res['units_disabled']} Sentinels disabled in {res['halt_latency_ms']} ms."
            ),
            details=res,
        )
        return res

    async def restore_from_emp(self) -> dict[str, Any]:
        parked = self._authorize_work("EMP_RESTORE", "swarm", "restore from EMP")
        if parked is not None:
            return parked
        res = await self.emp.restore_swarm(self.units)
        self.telemetry.record(
            "INFO",
            unit_id="EMP-CORE",
            caste="core",
            phase="SWARM RESTORED",
            message=f"EMP lockout cleared. {res['units_restored']} Sentinels restored to orbital patrol.",
            details=res,
        )
        return res

    def _collect_host_telemetry(self) -> dict[str, Any]:
        """Collect real OS hardware, network, socket, and disk inventory metrics from the host."""
        cpu_pct = 0.0
        ram_used_gb = 0.0
        ram_total_gb = 0.0
        ram_pct = 0.0
        net_sent_mb = 0.0
        net_recv_mb = 0.0
        with contextlib.suppress(psutil.Error, OSError):
            cpu_pct = round(float(psutil.cpu_percent(interval=None)), 1)
            vm = psutil.virtual_memory()
            ram_used_gb = round(vm.used / (1024**3), 2)
            ram_total_gb = round(vm.total / (1024**3), 2)
            ram_pct = round(float(vm.percent), 1)
            nio = psutil.net_io_counters()
            if nio:
                net_sent_mb = round(nio.bytes_sent / (1024**2), 2)
                net_recv_mb = round(nio.bytes_recv / (1024**2), 2)

        listening_tcp = 0
        established_tcp = 0
        wan_peers = 0
        lan_peers = 0
        loopback_peers = 0
        banned_peers_count = 0
        banned_peers_list: list[dict[str, Any]] = []
        open_ports_sample: list[str] = []
        remote_peers_sample: list[str] = []
        new_listening_ports: list[str] = []
        with contextlib.suppress(KeyError, psutil.Error, OSError):
            wrd = self.registry.get("warden")
            if isinstance(wrd, WardenCaste):
                l_socks = wrd.scan_listening_sockets()
                listening_tcp = len(l_socks)
                for s in l_socks[:8]:
                    open_ports_sample.append(f":{s['port']} ({s.get('process') or 'os'})")
                sock_snap = wrd.scan_sockets()
                established_tcp = int(sock_snap.get("total_established_tcp", 0))
                wan_peers = int(sock_snap.get("wan_peers_count", 0))
                lan_peers = int(sock_snap.get("lan_peers_count", 0))
                loopback_peers = int(sock_snap.get("loopback_peers_count", 0))
                banned_peers_count = int(sock_snap.get("banned_peers_count", 0))
                banned_peers_list = list(sock_snap.get("banned_peers") or [])
                remote_peers_sample = list(sock_snap.get("remote_peers_sample") or [])
                new_listening_ports = list(sock_snap.get("new_listening_ports") or [])

        immunized_hashes_count = 0
        immunized_hashes_list: list[dict[str, Any]] = []
        with contextlib.suppress(KeyError, OSError):
            san = self.registry.get("sanitizer")
            if isinstance(san, SanitizerCaste):
                immunized_hashes_count = san.immunized_count
                immunized_hashes_list = san.list_immunized_hashes()

        merkle_files = 0
        merkle_shadow_files = 0
        merkle_shadow_bytes = 0
        merkle_roots: dict[str, str] = {}
        with contextlib.suppress(KeyError, OSError):
            trp = self.registry.get("tripwire")
            if isinstance(trp, TripwireCaste):
                for b in trp._baselines.values():
                    merkle_files += len(b.file_hashes)
                    merkle_shadow_files += len(b.shadow_snapshots)
                    merkle_shadow_bytes += int(b.shadow_total_bytes)
                    merkle_roots[b.label] = b.merkle_root[:16]

        h_dir = harvest_dir()
        all_harvest: list[Path] = []
        if h_dir.exists():
            all_harvest = sorted(h_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
        harvest_files = [p.name for p in all_harvest[:12]]

        q_dir = quarantine_dir()
        all_quarantine: list[Path] = []
        if q_dir.exists():
            all_quarantine = sorted(q_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        quarantine_files = [p.name for p in all_quarantine[:12]]

        return {
            "hostname": platform.node() or "ATRIA-HOST",
            "os": f"{platform.system()} {platform.release()}",
            "cpu_percent": cpu_pct,
            "ram_used_gb": ram_used_gb,
            "ram_total_gb": ram_total_gb,
            "ram_percent": ram_pct,
            "net_sent_mb": net_sent_mb,
            "net_recv_mb": net_recv_mb,
            "listening_tcp_count": listening_tcp,
            "established_tcp_count": established_tcp,
            "wan_peers_count": wan_peers,
            "lan_peers_count": lan_peers,
            "loopback_peers_count": loopback_peers,
            "banned_peers_count": banned_peers_count,
            "banned_peers": banned_peers_list,
            "immunized_hashes_count": immunized_hashes_count,
            "immunized_hashes": immunized_hashes_list,
            "open_ports_sample": open_ports_sample,
            "remote_peers_sample": remote_peers_sample,
            "new_listening_ports": new_listening_ports,
            "merkle_files_hashed": merkle_files,
            "merkle_shadow_files": merkle_shadow_files,
            "merkle_shadow_kb": round(merkle_shadow_bytes / 1024.0, 1),
            "merkle_roots": merkle_roots,
            "harvest_reports_on_disk": len(all_harvest),
            "recent_harvest_files": harvest_files,
            "quarantine_files_on_disk": len(all_quarantine),
            "recent_quarantine_files": quarantine_files,
        }

    async def _run_autonomous_patrol_sortie(self) -> None:
        """Dispatch real inspection work for the patrol animation."""
        if self.emp.is_tripped:
            return
        if self.simulator._active_task is not None and not self.simulator._active_task.done():
            return
        self._patrol_tick += 1
        caste = "warden" if self._patrol_tick % 2 == 0 else "tripwire"
        idle = [u for u in self.units.values() if u.caste == caste and u.state == SentinelState.PATROLLING and u.pack_role == "SOLO"]
        if not idle:
            return
        await self.dispatch_task(caste, {"action": "patrol_scan" if caste == "warden" else "verify", "animate": True}, unit_id=idle[0].unit_id)

    def step_world(self, dt: float = 1.0 / 60.0) -> None:
        """Advance all 3D Boids, Pack Wingman synchronization, & steering physics for one simulation tick."""
        if self.emp.is_tripped:
            reason = str(self.emp.status.get("reason") or "EMP Lockout")
            for u in self.units.values():
                if u.state != SentinelState.EMP_DISABLED:
                    u.transition(
                        SentinelState.EMP_DISABLED,
                        task=f"EMP HALTED ({reason})",
                        laser_active=False,
                        carrying_orb=False,
                    )
        else:
            self._sync_pack_wingmen()
        unit_list = list(self.units.values())
        for u in unit_list:
            u.step_kinematics(dt, unit_list, self.nodes)

    def world_snapshot(self) -> dict[str, Any]:
        """Compact 60 Hz world state frame for the 3D Overseer viewport."""
        unit_list = [u.to_dict() for u in self.units.values()]
        by_caste: dict[str, int] = {}
        active_lasers = 0
        total_missions = 0
        total_bytes = 0
        for u in self.units.values():
            by_caste[u.caste] = by_caste.get(u.caste, 0) + 1
            if u.laser_active:
                active_lasers += 1
            total_missions += u.missions_completed
            total_bytes += u.bytes_processed

        return {
            "timestamp": time.time(),
            "theme": self._theme,
            "emp": self.emp.status,
            "active_banner": self.simulator.active_banner,
            "fx_events": self.simulator.pop_recent_fx(),
            "scenarios": list(SCENARIO_CATALOG),
            "host_telemetry": self.host_telemetry,
            "metrics": {
                "total_units": len(unit_list),
                "max_units": self.max_total_units,
                "default_tier": self.default_tier,
                "by_caste": by_caste,
                "active_lasers": active_lasers,
                "active_nodes": len(self.nodes),
                "missions_completed": total_missions,
                "threats_neutralized": 0,  # Deprecated: no measured containment total.
                "security_events": sum(u.security_events for u in self.units.values()),
                "bytes_processed": total_bytes,
                "warrants_minted": len(self.ledger),
            },
            "units": unit_list,
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "castes": self.registry.descriptors(),
            "recent_receipts": self.ledger.recent(limit=16),
            "telemetry_log": self.telemetry.recent(limit=60),
        }

    async def start_background_loops(self, *, hz: int = 60) -> None:
        if self._running:
            return
        self._running = True
        interval = 1.0 / max(10, min(int(hz), 120))

        async def _loop() -> None:
            last = time.perf_counter()
            while self._running:
                now = time.perf_counter()
                dt = now - last
                last = now
                try:
                    self.step_world(dt)
                except Exception:
                    log.exception("Sentinel kinematics tick failed; continuing")
                await asyncio.sleep(interval)

        async def _telemetry_loop() -> None:
            last_merkle_alert_sig = ""
            last_exposure_alert_sig = ""
            last_new_ports_sig = ""
            last_flood_sig = ""
            while self._running:
                await asyncio.sleep(3.0)
                if not self._running:
                    break
                try:
                    wrd = self.registry.get("warden")
                    if isinstance(wrd, WardenCaste):
                        # OS scan off-thread; node mutation on the loop thread (no cross-thread dict races)
                        raw_snap = await asyncio.to_thread(wrd.scan_sockets)
                        b_snap = wrd.apply_bastion_snapshot(self.nodes, raw_snap)
                        exposed = [
                            f":{b['port']} ({b['process']})"
                            for b in (b_snap.get("bastions") or [])
                            if b.get("exposure_warning")
                        ]
                        exp_sig = ",".join(exposed)
                        if exp_sig and exp_sig != last_exposure_alert_sig:
                            last_exposure_alert_sig = exp_sig
                            self.telemetry.record(
                                "CRITICAL",
                                unit_id="SNT-WRD-001",
                                caste="warden",
                                phase="LIVE OS EXPOSURE",
                                message=f"Loopback service exposed on 0.0.0.0/:: across all NICs: {exp_sig}",
                                details={"exposed_ports": exposed},
                            )
                        elif not exp_sig:
                            last_exposure_alert_sig = ""

                        new_ports = list(b_snap.get("new_listening_ports") or [])
                        np_sig = ",".join(new_ports)
                        if np_sig and np_sig != last_new_ports_sig:
                            last_new_ports_sig = np_sig
                            self.telemetry.record(
                                "WARDEN",
                                unit_id="SNT-WRD-001",
                                caste="warden",
                                phase="NEW OS PORT BOUND",
                                message=f"New listening TCP port(s) opened on host since boot: {np_sig}",
                                details={"new_listening_ports": new_ports},
                            )
                        elif not np_sig:
                            last_new_ports_sig = ""

                        flood_peers = list(b_snap.get("flood_peers") or [])
                        fl_sig = ",".join(f"{fp['remote_ip']}:{fp['connections']}" for fp in flood_peers)
                        if fl_sig and fl_sig != last_flood_sig:
                            last_flood_sig = fl_sig
                            self.telemetry.record(
                                "CRITICAL",
                                unit_id="SNT-WRD-001",
                                caste="warden",
                                phase="REMOTE SOCKET FLOOD",
                                message=f"High-concurrency remote peer(s) detected: {fl_sig}",
                                details={"flood_peers": flood_peers},
                            )
                        elif not fl_sig:
                            last_flood_sig = ""

                    trp = self.registry.get("tripwire")
                    if isinstance(trp, TripwireCaste):
                        raw_verdict = await asyncio.to_thread(trp.verify_all)
                        m_verdict = trp.apply_merkle_verdict(self.nodes, raw_verdict)
                        if not m_verdict.get("intact", True):
                            dirty_roots = [
                                f"{r['label']} (mod={len(r.get('modified', []))}, add={len(r.get('added', []))}, del={len(r.get('deleted', []))})"
                                for r in (m_verdict.get("roots") or [])
                                if not r.get("intact", True)
                            ]
                            m_sig = ";".join(dirty_roots)
                            if m_sig and m_sig != last_merkle_alert_sig:
                                last_merkle_alert_sig = m_sig
                                self.telemetry.record(
                                    "CRITICAL",
                                    unit_id="SNT-TRP-001",
                                    caste="tripwire",
                                    phase="LIVE MERKLE BREACH",
                                    message=f"Live filesystem modification detected by BLAKE2b Merkle guard: {m_sig}",
                                    details={"roots": [
                                        {k: v for k, v in r.items() if k != "diffs"}
                                        for r in (m_verdict.get("roots") or [])
                                    ]},
                                )
                        else:
                            last_merkle_alert_sig = ""

                    # 3. Deception Grid: Check Canary honeytokens
                    await asyncio.to_thread(self.deception.audit_canary_integrity)


                    self.host_telemetry = await asyncio.to_thread(self._collect_host_telemetry)
                    if self._running and not self.emp.is_tripped:
                        self.emp.track_task(asyncio.create_task(self._run_autonomous_patrol_sortie()))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("Sentinel telemetry tick failed; continuing")

        self._kinematics_task = asyncio.create_task(_loop())
        self._telemetry_task = asyncio.create_task(_telemetry_loop())

    async def stop_background_loops(self) -> None:
        self._running = False
        pending = [t for t in (self._kinematics_task, self._telemetry_task, *list(self.emp._active_tasks)) if t and not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        with contextlib.suppress(KeyError):
            hrv = self.registry.get("harvester")
            if isinstance(hrv, HarvesterCaste):
                await hrv.close()
