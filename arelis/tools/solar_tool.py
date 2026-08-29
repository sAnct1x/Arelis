"""Instantiate and drive the solar-system laboratory. Physics room."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from arelis.physics.constants import AU_M, BODIES, GM_SUN
from arelis.physics.engine import rebound_available
from arelis.physics.hohmann import hohmann
from arelis.physics.horizons import VectorState
from arelis.physics.ic_store import load_cached, save_cached
from arelis.physics.runtime import get_system, set_system
from arelis.physics.scene import SolarSystem
from arelis.spatial.grant import world_stage_allowed
from arelis.tools.base import ToolResult
from arelis.tools.catalog import CatalogTool, ephemeris_day

WRITE_ACTIONS = frozenset(
    {
        "impulse",
        "add_probe",
        "add_planet",
        "fetch_maps",
        "tracer",
        "l4",
        "epoch",
    }
)


class SolarTool:
    name = "solar"
    description = (
        "True-scale solar-system laboratory in the physics room. "
        "load fetches JPL Horizons VECTORS (SSB, ECLIPJ2000) and runs "
        "REBOUND IAS15. That is the only IC. status reads the HUD. "
        "lock opens the inspect tile; travel flies the camera "
        "(accel, cruise, slow) to an approach standoff — not a burn. "
        "There is no rideable craft; action=craft is inspect. "
        "impulse, add_probe, add_planet, tracer, l4, and epoch change the "
        "universe and need Allow. "
        "realtime locks IAS15 to UTC now (1 sim second per wall second). "
        "It is not a warp of 1× from midnight. "
        "dump writes a cited JSONL receipt under outputs/physics/solar. "
        "Leaving the solar lab does the same automatically. Not a screenshot. "
        "Belt tracers omitted. No GL still. "
        "Do not invent an ephemeris or Euler-step in prose. "
        "Belt tracers are unlabeled particles, not named asteroids. "
        "epoch scrubs a cited solar track; it is not a Gyr of IAS15."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "load",
                    "pause",
                    "resume",
                    "step",
                    "rate",
                    "lock",
                    "impulse",
                    "add_probe",
                    "add_planet",
                    "hohmann",
                    "lagrange",
                    "toggle",
                    "fetch_maps",
                    "craft",
                    "inspect",
                    "realtime",
                    "tracer",
                    "l4",
                    "epoch",
                    "travel",
                    "dump",
                ],
                "description": "What to do",
            },
            "date": {
                "type": "string",
                "description": "Horizons epoch YYYY-MM-DD for load",
            },
            "refresh": {
                "type": "boolean",
                "description": "Skip disk cache and fetch JPL Horizons again",
            },
            "tracers": {
                "type": "integer",
                "description": "Massless belt tracers on load (0-5000, default 800)",
            },
            "name": {
                "type": "string",
                "description": "Body name for lock, impulse, probe parent",
            },
            "dvx": {"type": "number", "description": "Impulse Δvx m/s"},
            "dvy": {"type": "number", "description": "Impulse Δvy m/s"},
            "dvz": {"type": "number", "description": "Impulse Δvz m/s"},
            "r1_au": {"type": "number", "description": "Hohmann inner radius AU"},
            "r2_au": {"type": "number", "description": "Hohmann outer radius AU"},
            "rate": {"type": "number", "description": "Sim seconds per wall second"},
            "epoch_gyr": {
                "type": "number",
                "description": "Gyr from today on the cited solar track (0=now)",
            },
            "flag": {
                "type": "string",
                "enum": [
                    "osculating",
                    "trails",
                    "graphs",
                    "lagrange",
                    "gravity",
                    "magnetic",
                    "wind",
                    "grid",
                    "warp",
                ],
                "description": "toggle which HUD overlay",
            },
        },
        "required": ["action"],
    }

    def __init__(
        self,
        catalog: CatalogTool | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self._catalog = catalog or CatalogTool()
        self._on_progress = on_progress

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action == "hohmann":
            return self._hohmann(kwargs)
        if action == "fetch_maps":
            return await self._fetch_maps()
        if action == "load":
            return await self._load(kwargs)
        if not world_stage_allowed() and action not in {"status"}:
            return ToolResult(
                ok=False,
                output=(
                    "The solar-system stage is source-checkout only. "
                    "The physics room still works for chat and Horizons observer."
                ),
                data={"fail_class": "fail:stage"},
            )
        system = get_system()
        if action == "status":
            return self._status(system)
        if system is None:
            return ToolResult(
                ok=False,
                output="No solar system loaded. Call solar action=load in the physics room.",
                data={"fail_class": "fail:empty"},
            )
        if action == "pause":
            system.paused = True
            return ToolResult(ok=True, output="Paused.", data={"paused": True})
        if action == "resume":
            system.paused = False
            return ToolResult(ok=True, output="Running.", data={"paused": False})
        if action == "step":
            system.step_once()
            return ToolResult(
                ok=True,
                output=f"Stepped. t={system.t:.3e} s.",
                data={"t": system.t},
            )
        if action == "rate":
            system.set_rate(float(kwargs.get("rate") or 1.0))
            return ToolResult(
                ok=True,
                output=f"Rate {system.rate:g} sim-seconds per wall-second.",
                data={"rate": system.rate},
            )
        if action == "realtime":
            system.go_realtime()
            when = ""
            from arelis.physics.attitude import spin_jd
            from arelis.physics.clocks import TT_MINUS_UTC_S, jd_iso
            from arelis.physics.constants import DAY_S

            stamp = jd_iso(spin_jd(system.epoch_jd, system.t) - TT_MINUS_UTC_S / DAY_S)
            if stamp:
                when = f" Sim UTC {stamp}."
            if not system.wall_lock:
                reason = (
                    " This lab is counterfactual."
                    if system.counterfactual
                    else " Needs a Horizons epoch within 400 days of now."
                )
                return ToolResult(
                    ok=True,
                    output=f"1×, not locked to UTC now.{reason}{when}",
                    data={"rate": system.rate, "wall_lock": system.wall_lock, "t": system.t},
                )
            return ToolResult(
                ok=True,
                output=f"Realtime — IAS15 locked to UTC now.{when}",
                data={"rate": system.rate, "wall_lock": system.wall_lock, "t": system.t},
            )
        if action == "craft":
            system.enter_inspect()
            return ToolResult(
                ok=True,
                output=(
                    "Inspect camera. WASD/QE fly. Click a body for a tile. "
                    "Travel to warps. There is no rideable craft."
                ),
                data={"mode": "inspect", "lock": system.lock},
            )
        if action == "inspect":
            system.enter_inspect()
            return ToolResult(
                ok=True,
                output="Inspect camera. WASD flies. Click a body for a tile. Travel to warps.",
                data={"mode": "inspect", "lock": system.lock},
            )
        if action == "tracer":
            try:
                label = system.spawn_tracer()
            except RuntimeError as exc:
                return ToolResult(
                    ok=False, output=str(exc), data={"fail_class": "fail:name"}
                )
            return ToolResult(
                ok=True,
                output=(
                    f"Massless belt tracer {label!r}. Debiased a,e,i, Kirkwood gaps. "
                    "Not a named asteroid. Counterfactual IC."
                ),
                data={"name": label, "counterfactual": True},
            )
        if action == "l4":
            try:
                label = system.spawn_lagrange("L4")
            except RuntimeError as exc:
                return ToolResult(
                    ok=False, output=str(exc), data={"fail_class": "fail:name"}
                )
            return ToolResult(
                ok=True,
                output=(
                    f"Massless {label} at Sun-Earth CR3BP L4, co-rotating. "
                    "Not the N-body equilibrium. Counterfactual IC."
                ),
                data={"name": label, "counterfactual": True},
            )
        if action == "epoch":
            gyr = float(kwargs.get("epoch_gyr") or 0.0)
            system.set_future_gyr(gyr)
            from arelis.physics.evolution import sample

            track = sample(system.future_gyr)
            return ToolResult(
                ok=True,
                output=(
                    f"Deep time +{system.future_gyr:.2f} Gyr. {track.phase}. "
                    f"R={track.r_sun:.2f} R_sun M={track.m_sun:.2f} M_sun. {track.cite}"
                ),
                data={
                    "future_gyr": system.future_gyr,
                    "phase": track.phase,
                    "r_sun": track.r_sun,
                    "m_sun": track.m_sun,
                },
            )
        if action == "lock":
            name = str(kwargs.get("name") or "").strip()
            if system.nbody.find(name) is None:
                return ToolResult(
                    ok=False,
                    output=f"No body named {name!r}.",
                    data={"fail_class": "fail:name"},
                )
            system.lock = name
            system.pending_inspect = name
            return ToolResult(
                ok=True,
                output=f"Inspecting {name}. Camera did not move. Use travel to warp.",
                data={"lock": name, "inspect": name},
            )
        if action == "travel":
            name = str(kwargs.get("name") or "").strip()
            if system.nbody.find(name) is None:
                return ToolResult(
                    ok=False,
                    output=f"No body named {name!r}.",
                    data={"fail_class": "fail:name"},
                )
            system.lock = name
            system.pending_inspect = name
            system.pending_travel = name
            return ToolResult(
                ok=True,
                output=(
                    f"Flying the camera to {name}. Accel, cruise, slow. "
                    "Approach standoff, not an N-body burn."
                ),
                data={"travel": name},
            )
        if action == "impulse":
            return self._impulse(system, kwargs)
        if action == "add_probe":
            return self._probe(system, kwargs)
        if action == "add_planet":
            return self._planet(system, kwargs)
        if action == "lagrange":
            return self._lagrange(system)
        if action == "toggle":
            return self._toggle(system, str(kwargs.get("flag") or ""))
        if action == "dump":
            return self._dump(system)
        return ToolResult(
            ok=False,
            output="Unknown solar action.",
            data={"fail_class": "fail:action"},
        )

    def _hohmann(self, kwargs: dict[str, Any]) -> ToolResult:
        r1 = float(kwargs.get("r1_au") or 1.0) * AU_M
        r2 = float(kwargs.get("r2_au") or 1.523679) * AU_M
        burn = hohmann(r1, r2, GM_SUN)
        return ToolResult(
            ok=True,
            output=(
                f"Hohmann r1={burn.r1 / AU_M:.6f} AU → r2={burn.r2 / AU_M:.6f} AU. "
                f"Δv1={burn.dv1:.3f} m/s Δv2={burn.dv2:.3f} m/s "
                f"TOF={burn.tof_s / 86400.0:.3f} d. Vis-viva, circular coplanar, "
                f"μ=GM_sun. Not a flown trajectory."
            ),
            data={
                "dv1": burn.dv1,
                "dv2": burn.dv2,
                "tof_s": burn.tof_s,
                "a_t": burn.a_t,
            },
        )

    def _progress(self, msg: str) -> None:
        if self._on_progress is not None:
            self._on_progress(msg)

    def _state_from_result(self, data: dict[str, Any]) -> VectorState:
        return VectorState(
            float(data["x"]),
            float(data["y"]),
            float(data["z"]),
            float(data["vx"]),
            float(data["vy"]),
            float(data["vz"]),
            units="SI",
            epoch_jd=float(data["jd"]) if data.get("jd") else None,
        )

    async def _fetch_vectors(
        self, day_iso: str
    ) -> tuple[dict[str, VectorState], list[str]]:
        """Sun first, then planets, then the rest. Stop if the Sun fails."""
        states: dict[str, VectorState] = {}
        errors: list[str] = []
        queue = _vector_fetch_order()
        n = len(queue)
        for i, spec in enumerate(queue, 1):
            self._progress(f"JPL Horizons {spec.name}  {i}/{n}")
            result = await self._catalog.run(
                action="horizons",
                target=spec.horizons_id,
                date=day_iso,
                table="vectors",
            )
            if not result.ok:
                errors.append(f"{spec.name}: {result.output}")
                if spec.name == "Sun":
                    break
                continue
            data = result.data or {}
            try:
                states[spec.name] = self._state_from_result(data)
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{spec.name}: {exc}")
                if spec.name == "Sun":
                    break
        return states, errors

    async def _fetch_maps(self) -> ToolResult:
        if not world_stage_allowed():
            return ToolResult(
                ok=False,
                output="Map cache is for a source checkout.",
                data={"fail_class": "fail:stage"},
            )
        from arelis.physics.maps import MAPS, download_maps, missing_maps

        if not missing_maps():
            have = ", ".join(MAPS)
            return ToolResult(
                ok=True,
                output=(
                    f"Albedo already on disk: {have}. "
                    "Approach/orbit only — not landing DEM."
                ),
                data={"saved": [], "errors": []},
            )
        saved, errors = download_maps()
        if not saved:
            return ToolResult(
                ok=False,
                output="No maps saved. " + "; ".join(errors),
                data={"fail_class": "fail:http", "errors": errors},
            )
        return ToolResult(
            ok=True,
            output=(
                "Saved NASA public-domain albedo maps for "
                + ", ".join(saved)
                + " under models/astro/maps/. Approach/orbit only — not landing DEM."
                + ((" " + "; ".join(errors)) if errors else "")
            ),
            data={"saved": saved, "errors": errors},
        )

    async def _load(self, kwargs: dict[str, Any]) -> ToolResult:
        if not world_stage_allowed():
            return ToolResult(
                ok=False,
                output="The solar-system stage is source-checkout only.",
                data={"fail_class": "fail:stage"},
            )
        if not rebound_available():
            return ToolResult(
                ok=False,
                output=(
                    "REBOUND is not installed. From a checkout: "
                    'pip install -e ".[astro]".'
                ),
                data={"fail_class": "fail:dep"},
            )
        day = str(kwargs.get("date") or "")
        try:
            day_iso = ephemeris_day(day).isoformat()
        except ValueError as exc:
            return ToolResult(
                ok=False,
                output=str(exc),
                data={"fail_class": "fail:parse"},
            )
        n_tr = kwargs.get("tracers")
        tracers = 800 if n_tr is None or n_tr == "" else int(n_tr)
        tracers = min(max(tracers, 0), 5_000)
        refresh = bool(kwargs.get("refresh"))
        cached = load_cached(day_iso)
        complete = cached is not None and all(b.name in cached for b in BODIES)
        states: dict[str, VectorState] = {}
        errors: list[str] = []
        from_cache = False
        if complete and cached is not None and not refresh:
            states = cached
            from_cache = True
            self._progress(f"JPL Horizons VECTORS from disk cache for {day_iso}")
        else:
            states, errors = await self._fetch_vectors(day_iso)
            if all(b.name in states for b in BODIES):
                save_cached(day_iso, states)
        if "Sun" not in states:
            return ToolResult(
                ok=False,
                output=_horizons_fail_output(errors),
                data={"fail_class": "fail:horizons", "errors": errors},
            )
        epoch = f"JPL Horizons VECTORS, {day_iso}"
        if from_cache:
            epoch += " (cached fetch)"
        try:
            system = SolarSystem.from_states(
                states,
                tracers=tracers,
                epoch_tdb=epoch,
                ic_date=day_iso,
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                output=str(exc),
                data={"fail_class": "fail:engine"},
            )
        live = get_system()
        if live is not None and live.counterfactual:
            return ToolResult(
                ok=True,
                output=(
                    "Horizons VECTORS are on disk. "
                    "The live system is counterfactual and was not replaced."
                ),
                data={
                    "cached": from_cache,
                    "date": day_iso,
                    "replaced": False,
                },
            )
        set_system(system)
        if not system.counterfactual:
            system.sync_to_now()
        missing = [b.name for b in BODIES if b.name not in states]
        note = ""
        if missing:
            shown = ", ".join(missing[:8])
            extra = ", …" if len(missing) > 8 else ""
            note = f" Missing VECTOR for {len(missing)}: {shown}{extra}."
        if from_cache:
            note += " Disk cache of the Horizons fetch for this UTC day."
        return ToolResult(
            ok=True,
            output=(
                f"Loaded {len(system.nbody.particles)} particles "
                f"({sum(1 for p in system.nbody.particles if p.massive)} massive, "
                f"{sum(1 for p in system.nbody.particles if p.tracer)} belt tracers). "
                f"Integrator {system.integrator_note}. "
                "True scale. After the first tick this is our N-body, not DE440."
                f"{note}"
            ),
            data={
                "n": len(system.nbody.particles),
                "tracers": tracers,
                "integrator": system.integrator_note,
                "cached": from_cache,
                "date": day_iso,
                "refresh": refresh,
            },
        )

    def _dump(self, system: SolarSystem) -> ToolResult:
        from arelis.physics.export import dump_state

        try:
            folder = dump_state(system, trigger="dump")
        except OSError as exc:
            return ToolResult(
                ok=False,
                output=str(exc),
                data={"fail_class": "fail:io"},
            )
        n = sum(
            1
            for p in system.nbody.particles
            if (not p.tracer) or p.name == system.lock
        )
        omitted = any(p.tracer for p in system.nbody.particles)
        digest = (system.ic_hash[:12] + "...") if system.ic_hash else "(none)"
        tracers = "Belt tracers omitted. " if omitted else ""
        return ToolResult(
            ok=True,
            output=(
                f"Dumped {n} bodies to {folder}. "
                f"ECLIPJ2000, t={system.t:.3e} s, ic_hash={digest}. "
                f"{tracers}No GL still in this bundle."
            ),
            data={
                "path": str(folder),
                "n": n,
                "ic_hash": system.ic_hash,
                "t": system.t,
                "tracers_omitted": omitted,
                "still": False,
            },
        )

    def _status(self, system: SolarSystem | None) -> ToolResult:
        if system is None:
            return ToolResult(
                ok=True,
                output="No solar system loaded.",
                data={"loaded": False, "stage": world_stage_allowed()},
            )
        hud = system.hud_for_lock()
        label = "tracer, not a named asteroid" if hud.get("tracer") else hud.get("kind")
        return ToolResult(
            ok=True,
            output=(
                f"{hud.get('name')} ({label}). t={hud.get('t_s'):.3e} s  "
                f"rate={hud.get('rate')}  residual E={hud.get('energy_residual'):.3e}  "
                f"integrator={hud.get('integrator')}  "
                f"counterfactual={hud.get('counterfactual')}."
            ),
            data=dict(hud),
        )

    def _impulse(self, system: SolarSystem, kwargs: dict[str, Any]) -> ToolResult:
        name = str(kwargs.get("name") or system.lock).strip()
        dv = (
            float(kwargs.get("dvx") or 0.0),
            float(kwargs.get("dvy") or 0.0),
            float(kwargs.get("dvz") or 0.0),
        )
        if not system.impulse(name, dv):
            return ToolResult(
                ok=False,
                output=f"Could not impulse {name!r}.",
                data={"fail_class": "fail:name"},
            )
        return ToolResult(
            ok=True,
            output=(
                f"Impulse on {name}: Δv={dv} m/s. Counterfactual. "
                "Energy and L books reset to the new universe."
            ),
            data={"name": name, "dv": dv, "counterfactual": True},
        )

    def _probe(self, system: SolarSystem, kwargs: dict[str, Any]) -> ToolResult:
        host_name = str(kwargs.get("name") or "").strip()
        if host_name:
            if system.nbody.find(host_name) is None:
                return ToolResult(
                    ok=False,
                    output=f"No body named {host_name!r}.",
                    data={"fail_class": "fail:name"},
                )
            system.lock = host_name
        label = system.spawn_probe()
        return ToolResult(
            ok=True,
            output=(
                f"Massless probe {label!r} on a circular injection around the lock. "
                "Counterfactual IC. Burns do not yank the planets."
            ),
            data={"name": label, "counterfactual": True},
        )

    def _planet(self, system: SolarSystem, kwargs: dict[str, Any]) -> ToolResult:
        a_au = float(kwargs.get("r1_au") or 2.5)
        name = str(kwargs.get("name") or "extra").strip() or "extra"
        label = system.add_planet(a_au * AU_M, name)
        system.lock = label
        return ToolResult(
            ok=True,
            output=(
                f"Added circular extra planet {label!r} at {a_au:g} AU, Earth mass. "
                "Counterfactual. Not a real body."
            ),
            data={"name": label, "a_au": a_au, "counterfactual": True},
        )

    def _lagrange(self, system: SolarSystem) -> ToolResult:
        earth = system.lagrange_sun_earth()
        jup = system.lagrange_sun_jupiter()
        bits = ["CR3BP circular approximation, not the N-body equilibrium."]
        for label, pts in (("Sun-Earth", earth), ("Sun-Jupiter", jup)):
            if not pts:
                continue
            bits.append(label + ": " + ", ".join(pts))
        return ToolResult(
            ok=True,
            output=" ".join(bits),
            data={"sun_earth": {k: list(v) for k, v in earth.items()}},
        )

    def _toggle(self, system: SolarSystem, flag: str) -> ToolResult:
        key = flag.strip().lower()
        if key in {"wind", "parker", "solarwind"}:
            key = "wind"
        val = system.apply_overlay(key)
        if val is None:
            return ToolResult(
                ok=False,
                output=(
                    "toggle flag: osculating, trails, graphs, lagrange, "
                    "gravity, magnetic, wind, grid, or warp."
                ),
                data={"fail_class": "fail:flag"},
            )
        return ToolResult(ok=True, output=f"{key}={val}.", data={key: val})


def _vector_fetch_order():
    sun = [b for b in BODIES if b.name == "Sun"]
    core = [
        b
        for b in BODIES
        if b.name != "Sun" and (b.kind == "planet" or b.name == "Moon")
    ]
    rest = [b for b in BODIES if b.name != "Sun" and b not in core]
    return sun + core + rest


def _horizons_fail_output(errors: list[str]) -> str:
    blob = " ".join(errors)
    if any(code in blob for code in ("503", "429", "502", "504")):
        return (
            "JPL Horizons is busy. Using a Kepler bootstrap if the plate is empty. "
            "Nothing is invented as Horizons."
        )
    if errors:
        return "Horizons did not return a Sun VECTOR. " + errors[0]
    return "load needs a Sun VECTOR."
