"""Live mission coordination and visual events; no scripted operational outcomes."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sentinel.core.hive import SwarmHive

SCENARIO_CATALOG = [
    {
        "id": "live_research_swarm",
        "title": "Research requested topic",
        "description": "Retrieve arXiv and Wikipedia sources for your query.",
    },
    {
        "id": "live_os_security_sweep",
        "title": "Inspect sockets and file integrity",
        "description": "Observe host sockets and compare registered file baselines; this does not install firewall rules.",
    },
]


class SimulationDirector:
    """Compatibility name retained for bridge clients; executes live jobs only."""

    def __init__(self, hive: SwarmHive) -> None:
        self.hive = hive
        self.active_banner: dict[str, Any] | None = None
        self.fx_events: list[dict[str, Any]] = []
        self._active_task: asyncio.Task[Any] | None = None
        self.last_result: dict[str, Any] | None = None

    def pop_recent_fx(self) -> list[dict[str, Any]]:
        now = time.time()
        self.fx_events = [fx for fx in self.fx_events if now - fx.get("at", 0) < 2.5]
        return list(self.fx_events)

    def emit_fx(
        self,
        kind: str,
        position: list[float],
        *,
        color: str = "#ff2a3a",
        label: str = "",
        target: list[float] | None = None,
    ) -> None:
        fx_id = f"fx-{int(time.time() * 1000)}-{len(self.fx_events)}"
        pos_list = list(position)
        tgt_list = list(target) if target else None
        self.fx_events.append(
            {
                "id": fx_id,
                "fx_id": fx_id,
                "kind": kind,  # "explosion" | "packet_salvo" | "scan_wave" | "shield_impact" | "orb_deposit"
                "position": pos_list,
                "origin": pos_list,
                "target": tgt_list,
                "color": color,
                "label": label,
                "at": time.time(),
            }
        )

    def _set_banner(self, level: str, title: str, subtitle: str, phase: str) -> None:
        sev_map = {"warn": "warning", "ok": "sanitize", "critical": "critical", "info": "info"}
        self.active_banner = {
            "level": level,
            "severity": sev_map.get(level, level),
            "title": title,
            "subtitle": subtitle,
            "phase": phase,
            "updated_at": time.time(),
        }

    def clear_banner(self) -> None:
        self.active_banner = None

    async def run_scenario(self, scenario_id: str, *, query: str = "") -> dict[str, Any]:
        if scenario_id == "live_research_swarm":
            return await self.run_live_mission("multi", query)
        if scenario_id == "live_os_security_sweep":
            return await self.run_live_mission("security_audit", query)
        return {"ok": False, "error": "Scripted scenarios are not operational missions."}

    async def run_live_mission(self, mode: str, query: str) -> dict[str, Any]:
        if self.hive.emp.is_tripped:
            return {"ok": False, "error": "Emergency stop is active"}
        mode = (mode or "multi").strip().lower()
        query = (query or "").strip()
        if mode not in {"multi", "arxiv", "wikipedia", "horizons", "security_audit"}:
            return {"ok": False, "error": "Unknown mission mode"}
        if mode != "security_audit" and not query:
            return {"ok": False, "error": "Enter a research topic or Horizons target."}
        if self._active_task is not None and not self._active_task.done():
            return {"ok": False, "error": "An observed mission is already running."}
        self.last_result = None
        self._active_task = self.hive.emp.track_task(asyncio.create_task(self._run(mode, query)))
        return {"ok": True, "status": "launched", "mode": mode, "query": query}

    async def _run(self, mode: str, query: str) -> None:
        self._set_banner(
            "info", "SENTINELS WORKING", query or "Inspecting sockets and file baselines", "RUNNING"
        )
        try:
            if mode == "security_audit":
                sockets = await self.hive.dispatch_task("warden", {"action": "patrol_scan"})
                integrity = await self.hive.dispatch_task("tripwire", {"action": "verify"})
                intact = integrity.get("intact") is True
                roots = integrity.get("roots") or []
                result = {
                    "ok": bool(sockets.get("ok")) and intact and bool(roots),
                    "socket_result": sockets,
                    "integrity_result": integrity,
                }
                detail = f"Socket inspection ok={bool(sockets.get('ok'))}; {len(roots)} roots checked; intact={intact}. Observation, not host-wide enforcement."
            else:
                targets: list[dict[str, Any]]
                if mode == "multi":
                    targets = [
                        {"action": "arxiv", "query": query, "max_results": 4},
                        {"action": "wikipedia", "query": query},
                    ]
                elif mode == "horizons":
                    targets = [{"action": "horizons", "target": query}]
                elif mode == "wikipedia" and query.startswith("https://"):
                    targets = [{"action": "url", "url": query}]
                else:
                    targets = [{"action": mode, "query": query}]
                result = await self.hive.dispatch_harvest_swarm(
                    query, targets, save_report=True, animate=True
                )
                raw_succeeded = result.get("succeeded", 0)
                succeeded = int(raw_succeeded) if isinstance(raw_succeeded, (int, str, float)) else 0
                raw_total = result.get("total_targets", len(targets))
                total = int(raw_total) if isinstance(raw_total, (int, str, float)) else len(targets)
                result = dict(result, ok=total > 0 and succeeded == total)
                detail = f"{succeeded}/{total} sources retrieved; {result.get('quarantined', 0)} quarantined; {result.get('failed', 0)} failed."
                if succeeded:
                    self.emit_fx("orb_deposit", [0.0, 0.0, 0.0], label="SOURCES RETRIEVED")
            if self.hive.emp.is_tripped:
                raise asyncio.CancelledError
            self.last_result = result
            self._set_banner(
                "ok" if result.get("ok") else "warn",
                "MISSION COMPLETE" if result.get("ok") else "MISSION NEEDS ATTENTION",
                detail,
                "COMPLETE",
            )
        except asyncio.CancelledError:
            self.last_result = {"ok": False, "cancelled": True}
            self._set_banner(
                "warn",
                "MISSION STOPPED",
                "Work was cancelled; completion is not claimed.",
                "STOPPED",
            )
            raise
        except Exception as exc:  # noqa: BLE001 - background job must report unexpected failures
            self.last_result = {"ok": False, "error": type(exc).__name__}
            self._set_banner("warn", "MISSION FAILED", type(exc).__name__, "FAILED")
