"""Sentinel tools for the model: four reads and five controls.

Reads: status, units, logs, castes. Controls: deploy (spawn_units), stop
(retire_unit, or scale_caste by a count or to 0), retask (dispatch_task), mission
(deploy_harvest_swarm) and emp (emp_halt). There is no restore tool: only
Christopher can undo an emergency stop. The bridge keeps its own send block,
caps and AuthorityGate; nothing here bypasses them.

Every call goes through ``arelis.sentinel_client`` (held token, bound loopback
endpoint, 3 s limit, fail soft). No control op and no EMP restore is reachable
from here. Filters mirror the Overseer: ``sentinel_logs`` uses the same rules
as ``matchesLogFilter`` in sentinel/ui/overseer/telemetry_ws.js.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import time
from typing import Any

from arelis import sentinel_client
from arelis.tools.base import ToolResult

BUILT_IN_CASTES = ("harvester", "warden", "sanitizer", "tripwire", "stalker", "cryptarch")
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


async def _snapshot() -> tuple[dict[str, Any] | None, ToolResult | None]:
    # The client blocks on a worker join for up to its 3 s limit. Run it off
    # the event loop so other tasks and cancellation keep moving.
    reply = await asyncio.to_thread(sentinel_client.snapshot)
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
        snap, err = await _snapshot()
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
        snap, err = await _snapshot()
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
        snap, err = await _snapshot()
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
        reply = await asyncio.to_thread(sentinel_client.command, "list_castes")
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


MAX_DEPLOY = 50
COMMAND_ACTIONS = ("deploy", "stop", "retask", "mission")

# Advertised capability -> the payload the caste's handler actually acts on.
# Only capabilities with a real execute() branch are here; anything else is
# refused instead of falling through to a handler default.
# (caste, capability): (fixed payload, key that takes target or None,
#                       target required, extra payload keys allowed)
RETASK_MAP: dict[tuple[str, str], tuple[dict[str, Any], str | None, bool, frozenset[str]]] = {
    ("harvester", "fetch_url"): ({"action": "url"}, "url", True, frozenset()),
    ("harvester", "query_arxiv"): ({"action": "arxiv"}, "query", True, frozenset({"max_results"})),
    ("harvester", "query_horizons"): ({"action": "horizons"}, "target", True, frozenset()),
    ("harvester", "query_wikipedia"): ({"action": "wikipedia"}, "query", True, frozenset()),
    ("warden", "scan_sockets"): ({"action": "patrol_scan"}, None, False, frozenset()),
    ("warden", "verify_egress"): ({"action": "verify_egress"}, "url", True, frozenset()),
    ("warden", "intercept_threat"): (
        {"action": "intercept"},
        "source_ip",
        True,
        frozenset({"label", "reason", "port"}),
    ),
    ("tripwire", "register_watch_root"): (
        {"action": "register"},
        "path",
        True,
        frozenset({"label"}),
    ),
    ("tripwire", "verify_integrity"): ({"action": "verify"}, None, False, frozenset()),
    ("sanitizer", "sanitize_text"): (
        {"capability": "sanitize_text", "is_html": False},
        "text",
        True,
        frozenset({"source"}),
    ),
    ("sanitizer", "sanitize_html"): (
        {"capability": "sanitize_html", "is_html": True},
        "text",
        True,
        frozenset({"source"}),
    ),
    ("sanitizer", "inspect_archive"): (
        {"capability": "inspect_archive"},
        "data",
        True,
        frozenset({"source"}),
    ),
    ("stalker", "process:list"): (
        {"capability": "process:list"},
        None,
        False,
        frozenset({"limit"}),
    ),
    ("stalker", "process:inspect_pid"): (
        {"capability": "process:inspect_pid"},
        "pid",
        True,
        frozenset(),
    ),
    ("stalker", "process:detect_rogue"): (
        {"capability": "process:detect_rogue"},
        None,
        False,
        frozenset(),
    ),
    ("stalker", "process:audit_memory"): (
        {"capability": "process:audit_memory"},
        None,
        False,
        frozenset({"threshold"}),
    ),
    ("cryptarch", "crypto:hash_verify"): (
        {"capability": "crypto:hash_verify"},
        "data",
        True,
        frozenset({"expected", "digest", "algorithm"}),
    ),
    ("cryptarch", "crypto:entropy_calc"): (
        {"capability": "crypto:entropy_calc"},
        "data",
        True,
        frozenset({"threshold"}),
    ),
    ("cryptarch", "crypto:hmac_validate"): (
        {"capability": "crypto:hmac_validate"},
        "data",
        True,
        frozenset({"key", "expected_hmac", "algorithm"}),
    ),
    ("cryptarch", "crypto:merkle_proof"): (
        {"capability": "crypto:merkle_proof"},
        "data",
        True,
        frozenset({"root_hash", "proof_path", "algorithm"}),
    ),
}


async def _call(op: str, **kwargs: Any) -> dict[str, Any]:
    """One bridge op off the event loop (the client blocks up to 3 s)."""
    return await asyncio.to_thread(sentinel_client.command, op, **kwargs)


def _refuse(message: str) -> ToolResult:
    return ToolResult(ok=False, output=message)


async def _known_caste(raw: Any) -> tuple[str, dict[str, Any], ToolResult | None]:
    """(caste id, its descriptor) if the bridge lists it, else a clean refusal."""
    cid = str(raw or "").strip().lower()
    if not cid:
        return "", {}, _refuse("caste is required.")
    reply = await _call("list_castes")
    if not reply.get("ok"):
        return "", {}, _fail(reply)
    by_id = {str(d.get("caste_id") or ""): d for d in reply.get("castes") or []}
    if cid not in by_id:
        return "", {}, _refuse(f"Unknown caste {cid!r}. Known: {', '.join(by_id)}.")
    desc = dict(by_id[cid])
    try:
        desc["units"] = int((reply.get("counts") or {}).get(cid, 0))
    except (TypeError, ValueError):
        desc["units"] = 0
    return cid, desc, None


def build_retask_payload(
    caste: str, descriptor: dict[str, Any], capability: str, target: str, payload: dict[str, Any]
) -> tuple[dict[str, Any] | None, str]:
    """Handler payload for a supported capability, or (None, reason)."""
    cap = capability.strip().lower()
    if cap not in set(descriptor.get("allowed_capabilities") or []):
        return None, f"{caste} does not have capability {cap!r}."
    entry = RETASK_MAP.get((caste, cap))
    if entry is None:
        return None, f"{caste} cannot be tasked with {cap!r} from here."
    fixed, target_key, needs_target, extras = entry
    unknown = sorted(set(payload) - extras)
    if unknown:
        return None, f"payload keys not allowed for {cap}: {', '.join(unknown)}."
    task = dict(payload)
    if target_key is not None:
        if needs_target and not target:
            return None, f"{cap} needs a target."
        task[target_key] = target
    elif target:
        return None, f"{cap} takes no target."
    task.update(fixed)
    return task, ""


class SentinelCommandTool:
    """One normal-control tool. EMP stays separate (sentinel_emp)."""

    name = "sentinel_command"
    description = "Command sentinels: deploy, stop, retask, or start a research mission."
    risk = "write"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(COMMAND_ACTIONS)},
            "caste": {"type": "string"},
            "count": {"type": "integer"},
            "unit_id": {"type": "string"},
            "capability": {"type": "string"},
            "target": {"type": "string"},
            "payload": {"type": "object"},
            "question": {"type": "string"},
        },
        "required": ["action"],
    }

    _ARGS = {
        "deploy": {"caste", "count"},
        "stop": {"unit_id", "caste", "count"},
        "retask": {"caste", "capability", "target", "payload"},
        "mission": {"question"},
    }

    async def run(self, action: str = "", **kwargs: Any) -> ToolResult:
        act = str(action or "").strip().lower()
        if act not in COMMAND_ACTIONS:
            return _refuse("action must be one of " + "|".join(COMMAND_ACTIONS) + ".")
        given = {k for k, v in kwargs.items() if v not in (None, "", {})}
        extra = sorted(given - self._ARGS[act])
        if extra:
            return _refuse(f"{act} does not take: {', '.join(extra)}.")
        return await getattr(self, "_" + act)(**{k: kwargs[k] for k in given})

    async def _deploy(self, caste: str = "", count: Any = 1) -> ToolResult:
        if isinstance(count, bool):
            return _refuse("count must be a whole number.")
        try:
            n = int(count)
        except (TypeError, ValueError):
            return _refuse("count must be a whole number.")
        if not 1 <= n <= MAX_DEPLOY:
            return _refuse(f"count must be 1 to {MAX_DEPLOY}.")
        cid, _desc, err = await _known_caste(caste)
        if err is not None:
            return err
        reply = await _call("spawn_units", caste=cid, count=n)
        if not reply.get("ok"):
            return _fail(reply)
        spawned = [str(u.get("unit_id") or "") for u in reply.get("spawned") or []]
        note = "" if len(spawned) == n else " The swarm is at its unit limit."
        return ToolResult(
            ok=True,
            output=f"Deployed {len(spawned)} {cid}.{note}",
            data={"spawned": spawned, "total_units": reply.get("total_units")},
        )

    async def _stop(self, unit_id: str = "", caste: str = "", count: Any = None) -> ToolResult:
        uid = str(unit_id or "").strip()
        if bool(uid) == bool(str(caste or "").strip()):
            return _refuse("Give exactly one of unit_id or caste.")
        n: int | None = None
        if count not in (None, ""):
            if uid:
                return _refuse("count is for a caste stand-down, not a unit.")
            if isinstance(count, bool):
                return _refuse("count must be a whole number.")
            try:
                n = int(count)
            except (TypeError, ValueError):
                return _refuse("count must be a whole number.")
            if n < 1:
                return _refuse("count must be at least 1.")
        if uid:
            reply = await _call("retire_unit", unit_id=uid)
            if not reply.get("ok"):
                return _fail(reply) if reply.get("error") else _refuse(f"No unit {uid}.")
            return ToolResult(ok=True, output=f"Retired {uid}.", data={"unit_id": uid})
        cid, desc, err = await _known_caste(caste)
        if err is not None:
            return err
        if n is None:
            target = 0
        else:
            target = max(0, int(desc.get("units") or 0) - n)
        reply = await _call("scale_caste", caste=cid, target_count=target)
        if not reply.get("ok"):
            return _fail(reply)
        retired = reply.get("retired") or []
        if isinstance(retired, list):
            n_retired = len(retired)
        else:
            try:
                n_retired = int(retired)
            except (TypeError, ValueError):
                n_retired = 0
        try:
            remaining = int(reply["count"])
        except (KeyError, TypeError, ValueError):
            remaining = None
        if n is None:
            output = f"Stood down every {cid} ({n_retired} retired)."
        elif remaining is None:
            output = f"Stood down {n_retired} {cid}."
        else:
            output = f"Stood down {n_retired} {cid}; {remaining} remain."
        return ToolResult(
            ok=True,
            output=output,
            data={
                "caste": cid,
                "retired": retired if isinstance(retired, list) else [],
                "retired_count": n_retired,
                "remaining": remaining,
            },
        )

    async def _retask(
        self, caste: str = "", capability: str = "", target: str = "", payload: Any = None
    ) -> ToolResult:
        if not str(capability or "").strip():
            return _refuse("capability is required.")
        if payload is not None and not isinstance(payload, dict):
            return _refuse("payload must be an object.")
        cid, desc, err = await _known_caste(caste)
        if err is not None:
            return err
        task, why = build_retask_payload(
            cid, desc, str(capability), str(target or "").strip(), dict(payload or {})
        )
        if task is None:
            return _refuse(why)
        reply = await _call("dispatch_task", caste=cid, payload=task)
        result = reply.get("result") if isinstance(reply.get("result"), dict) else {}
        if not reply.get("ok"):
            msg = str(result.get("error") or reply.get("error") or sentinel_client.REFUSED)
            return ToolResult(ok=False, output=msg, data={"result": result})
        return ToolResult(ok=True, output=f"{cid} did {capability}.", data={"result": result})

    async def _mission(self, question: str = "") -> ToolResult:
        q = str(question or "").strip()
        if not q:
            return _refuse("question is required.")
        if q.upper().startswith("REQ-"):
            ref = q.upper()
            reply = await _call("mission_status", mission_ref=ref)
            if not reply.get("ok"):
                return _fail(reply)
            status = reply.get("status")
            if status == "running":
                started = float(reply.get("started_at") or 0)
                elapsed = f"{time.time() - started:.1f}" if started else "?"
                return ToolResult(
                    ok=True,
                    output=f"Mission {ref} is in flight ({elapsed}s elapsed).",
                    data=reply,
                )
            elif status == "done":
                succeeded = reply.get("succeeded", 0)
                total = reply.get("total_targets", 0)
                report = reply.get("report_path") or "none"
                warrants = reply.get("arelis_warrants") or []
                lines = [
                    f"Mission {ref} completed: {succeeded}/{total} targets harvested.",
                    f"Dossier: {report}",
                ]
                if warrants:
                    lines.append(f"Warrants: {len(warrants)} verified citations.")
                return ToolResult(ok=True, output="\n".join(lines), data=reply)
            else:
                err = reply.get("error") or "failed"
                return ToolResult(
                    ok=False,
                    output=f"Mission {ref} {status}: {err}",
                    data=reply,
                )
        targets = [
            {"action": "arxiv", "query": q, "max_results": 4},
            {"action": "wikipedia", "query": q},
        ]
        reply = await _call("start_harvest_mission", question=q, targets=targets)
        if not reply.get("ok"):
            return _fail(reply)
        ref = str(reply.get("mission_ref") or "")
        return ToolResult(
            ok=True,
            output=(
                f"Mission {ref} accepted and running, not finished. "
                "Its result or failure lands in sentinel_logs (harvest)."
            ),
            data={"mission_ref": ref, "status": reply.get("status")},
        )


class SentinelEmpTool:
    name = "sentinel_emp"
    description = "Emergency stop for every sentinel. Only Christopher can undo it."
    risk = "write"
    parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        reply = await _call("emp_halt", reason="Arelis emergency stop")
        if not reply.get("ok"):
            return _fail(reply)
        return ToolResult(ok=True, output="Emergency stop is on.", data={"emp": reply.get("emp")})


def sentinel_tools() -> list[Any]:
    """The Sentinel tools, or none when the Sentinel package is not installed."""
    if not sentinel_available():
        return []
    return [
        SentinelStatusTool(),
        SentinelListTool(),
        SentinelLogsTool(),
        SentinelCastesTool(),
        SentinelCommandTool(),
        SentinelEmpTool(),
    ]
