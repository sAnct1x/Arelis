"""Read-only Sentinel tools for the model: status, units, logs, castes.

Every call goes through ``arelis.sentinel_client`` (held token, bound loopback
endpoint, 3 s limit, fail soft). No control op and no EMP restore is reachable
from here. Filters mirror the Overseer: ``sentinel_logs`` uses the same rules
as ``matchesLogFilter`` in sentinel/ui/overseer/telemetry_ws.js.
"""

from __future__ import annotations

import importlib.util
import json
from typing import Any

from arelis import sentinel_client
from arelis.tools.base import ToolResult

BUILT_IN_CASTES = ("harvester", "warden", "sanitizer", "tripwire")
LOG_FILTERS = ("all", "threat", "sanitize", "harvest", "tripwire")
_LOG_LIMIT_MAX = 60
_LIST_MAX = 50
_THREAT_LEVELS = frozenset({"THREAT", "BLOCK", "CRITICAL", "WARDEN", "ALERT", "EMP"})


def sentinel_available() -> bool:
    """True when the Sentinel package (and its client) can be imported."""
    try:
        return importlib.util.find_spec("sentinel.bridge.client") is not None
    except (ImportError, ValueError):
        return False


def _fail(reply: dict[str, Any]) -> ToolResult:
    return ToolResult(ok=False, output=str(reply.get("error") or sentinel_client.UNREACHABLE))


def _snapshot() -> tuple[dict[str, Any] | None, ToolResult | None]:
    reply = sentinel_client.snapshot()
    if not reply.get("ok"):
        return None, _fail(reply)
    snap = reply.get("snapshot")
    if not isinstance(snap, dict):
        return None, ToolResult(ok=False, output=sentinel_client.REFUSED)
    return snap, None


def log_matches(entry: dict[str, Any], filt: str, query: str) -> bool:
    """Same rule as the Overseer console filter and search box."""
    lvl = str(entry.get("level") or "").upper()
    cat = str(entry.get("caste") or "").lower()
    src = str(entry.get("unit_id") or "").upper()
    if filt == "threat":
        if not (lvl in _THREAT_LEVELS or "warden" in cat):
            return False
    elif filt == "sanitize":
        if not (lvl == "SANITIZE" or "sanitize" in cat or "SAN" in src):
            return False
    elif filt == "harvest":
        if not (lvl in ("HARVEST", "WARRANT") or "harvest" in cat or "HRV" in src):
            return False
    elif filt == "tripwire":
        if not (lvl == "TRIPWIRE" or "tripwire" in cat or "TRP" in src):
            return False
    if query:
        hay = " ".join(
            [
                str(entry.get("unit_id") or ""),
                str(entry.get("caste") or ""),
                str(entry.get("phase") or ""),
                str(entry.get("message") or ""),
                json.dumps(entry.get("details") or {}),
            ]
        ).lower()
        if query not in hay:
            return False
    return True


class SentinelStatusTool:
    name = "sentinel_status"
    description = "Sentinel swarm: running, EMP stop, units per caste. read only"
    risk = "read"
    parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        snap, err = _snapshot()
        if err is not None:
            return err
        emp = snap.get("emp") or {}
        metrics = snap.get("metrics") or {}
        by_caste = dict(metrics.get("by_caste") or {})
        total = int(metrics.get("total_units") or 0)
        tripped = bool(emp.get("tripped"))
        parts = [
            "EMP stop is ON" + (f" ({emp.get('reason')})" if emp.get("reason") else "")
            if tripped
            else "EMP stop is off",
            f"{total} units of max {metrics.get('max_units', '?')}",
        ]
        if by_caste:
            parts.append(", ".join(f"{k} {v}" for k, v in sorted(by_caste.items())))
        return ToolResult(
            ok=True,
            output=". ".join(parts) + ".",
            data={"emp_tripped": tripped, "total_units": total, "by_caste": by_caste},
        )


class SentinelListTool:
    name = "sentinel_list"
    description = "Sentinel units. filter by caste, state, or query text. read only"
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "caste": {"type": "string", "description": "Caste id, e.g. warden."},
            "state": {"type": "string", "description": "FSM state, e.g. PATROLLING."},
            "query": {"type": "string", "description": "Text in id, task, or doctrine."},
        },
    }

    async def run(
        self, caste: str = "", state: str = "", query: str = "", **kwargs: Any
    ) -> ToolResult:
        del kwargs
        snap, err = _snapshot()
        if err is not None:
            return err
        c = str(caste or "").strip().lower()
        s = str(state or "").strip().upper()
        q = str(query or "").strip().lower()
        rows = []
        for u in snap.get("units") or []:
            if c and str(u.get("caste") or "").lower() != c:
                continue
            if s and str(u.get("state") or "").upper() != s:
                continue
            if q:
                hay = " ".join(
                    str(u.get(k) or "")
                    for k in (
                        "unit_id",
                        "caste",
                        "state",
                        "current_task",
                        "doctrine",
                        "target_node_id",
                    )
                ).lower()
                if q not in hay:
                    continue
            rows.append(
                {
                    k: u.get(k)
                    for k in (
                        "unit_id",
                        "caste",
                        "tier",
                        "state",
                        "current_task",
                        "missions_completed",
                    )
                }
            )
        shown = rows[:_LIST_MAX]
        if not rows:
            return ToolResult(ok=True, output="No units match.", data={"units": [], "total": 0})
        lines = [
            f"{r['unit_id']} {r['caste']} {r['state']}"
            + (f": {r['current_task']}" if r.get("current_task") else "")
            for r in shown
        ]
        more = f"\n{len(rows) - len(shown)} more not shown." if len(rows) > len(shown) else ""
        return ToolResult(
            ok=True,
            output="\n".join(lines) + more,
            data={"units": shown, "total": len(rows)},
        )


class SentinelLogsTool:
    name = "sentinel_logs"
    description = "Sentinel event log, newest first. read only"
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "filter": {"type": "string", "enum": list(LOG_FILTERS)},
            "query": {"type": "string", "description": "Text to search for."},
            "limit": {"type": "integer", "description": "Max entries, default 20."},
        },
    }

    async def run(
        self, filter: str = "all", query: str = "", limit: Any = 20, **kwargs: Any
    ) -> ToolResult:
        del kwargs
        filt = str(filter or "all").strip().lower()
        if filt not in LOG_FILTERS:
            return ToolResult(
                ok=False, output="filter must be one of " + "|".join(LOG_FILTERS) + "."
            )
        try:
            n = max(1, min(int(limit), _LOG_LIMIT_MAX))
        except (TypeError, ValueError):
            n = 20
        snap, err = _snapshot()
        if err is not None:
            return err
        q = str(query or "").strip().lower()
        logs = [e for e in snap.get("telemetry_log") or [] if isinstance(e, dict)]
        hits = [e for e in logs if log_matches(e, filt, q)][::-1][:n]
        if not hits:
            return ToolResult(ok=True, output="No log entries match.", data={"entries": []})
        lines = [
            f"{e.get('iso_time', '')} {e.get('level', '')} "
            f"{e.get('unit_id', '')}: {e.get('message', '')}"
            for e in hits
        ]
        return ToolResult(ok=True, output="\n".join(lines), data={"entries": hits})


class SentinelCastesTool:
    name = "sentinel_castes"
    description = "Sentinel castes, built-in and custom, with capabilities. read only"
    risk = "read"
    parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        reply = sentinel_client.command("list_castes")
        if not reply.get("ok"):
            return _fail(reply)
        counts = dict(reply.get("counts") or {})
        rows = []
        for d in reply.get("castes") or []:
            cid = str(d.get("caste_id") or "")
            rows.append(
                {
                    "caste_id": cid,
                    "built_in": cid in BUILT_IN_CASTES,
                    "purpose": d.get("single_purpose") or "",
                    "capabilities": list(d.get("allowed_capabilities") or []),
                    "units": int(counts.get(cid, 0)),
                }
            )
        if not rows:
            return ToolResult(ok=True, output="No castes registered.", data={"castes": []})
        lines = [
            f"{r['caste_id']} ({'built-in' if r['built_in'] else 'custom'}, {r['units']} units): "
            + ", ".join(r["capabilities"])
            for r in rows
        ]
        return ToolResult(ok=True, output="\n".join(lines), data={"castes": rows})


def sentinel_tools() -> list[Any]:
    """The read tools, or none when the Sentinel package is not installed."""
    if not sentinel_available():
        return []
    return [SentinelStatusTool(), SentinelListTool(), SentinelLogsTool(), SentinelCastesTool()]
