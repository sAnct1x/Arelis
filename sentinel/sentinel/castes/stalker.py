"""ProcessAuditorCaste. Lists and inspects host processes and RAM use.

The HUNTER-KILLER doctrine value is a motion and pack label.
execute() does not kill, terminate, quarantine, or signal processes.
detect_rogue_processes() findings are name and path heuristics, not proof.
audit_memory() reads host RAM totals and process percents via psutil; it
does not dump or scan process memory. Command lines are not returned.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import time
from typing import Any

import psutil

from sentinel.castes.base import CasteDescriptor, CasteHandler
from sentinel.core.bus import EventBus
from sentinel.core.fsm import SentinelState, SentinelUnit, WorldNode
from sentinel.core.receipts import ReceiptLedger

_DEFAULT_SUSPICIOUS_NAMES = frozenset({
    "nc.exe",
    "ncat.exe",
    "mimikatz.exe",
    "psexec.exe",
    "cobaltstrike.exe",
    "hydra.exe",
})

MAX_LIST = 80
MAX_CONNECTIONS = 16
MAX_CHILDREN = 16
MAX_FLAGGED = 40
MAX_TOP_CONSUMERS = 10
SCAN_BUDGET_S = 1.5


def _remember_top(
    heap: list[tuple[float, int, dict[str, Any]]],
    score: float,
    rec: dict[str, Any],
    *,
    limit: int = MAX_TOP_CONSUMERS,
) -> None:
    """Keep at most `limit` records, ranked by score. Heap never grows past limit."""
    key = (score, int(rec.get("pid") or 0), rec)
    if len(heap) < limit:
        heapq.heappush(heap, key)
    elif score > heap[0][0]:
        heapq.heapreplace(heap, key)


def _record_flag(flagged: list[dict[str, Any]], item: dict[str, Any]) -> bool:
    """Append one heuristic hit if under MAX_FLAGGED. False means the cap blocked it."""
    if len(flagged) >= MAX_FLAGGED:
        return False
    flagged.append(item)
    return True


class StalkerCaste(CasteHandler):
    """Narrow Sentinel caste specialized in real-time host process and memory auditing."""

    descriptor = CasteDescriptor(
        caste_id="stalker",
        code_prefix="STK",
        title="Host Process Stalker",
        single_purpose="Audits running host processes, memory thresholds, orphan processes, and rogue executable paths",
        allowed_capabilities=frozenset([
            "process:list",
            "process:inspect_pid",
            "process:detect_rogue",
            "process:audit_memory",
        ]),
        version="1.1.0",
        orbit_radius=13.0,
        orbit_y_band=3.0,
        speed_mult=1.1,
        eye_color="#ffd600",
        laser_kind="defense",
        # Motion and pack label only. The execute path lists and inspects processes.
        doctrine="HUNTER-KILLER",
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.suspicious_names = frozenset(
            cfg.get("suspicious_process_names") or _DEFAULT_SUSPICIOUS_NAMES
        )

    def list_processes(self, limit: int = 50) -> dict[str, Any]:
        cap = max(1, min(int(limit), MAX_LIST))
        procs: list[dict[str, Any]] = []
        partial = False
        truncated = False
        deadline = time.monotonic() + SCAN_BUDGET_S
        for p in psutil.process_iter(["pid", "name", "username", "memory_percent", "status"]):
            if time.monotonic() >= deadline:
                partial = True
                break
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                info = p.info
                procs.append({
                    "pid": info.get("pid"),
                    "name": info.get("name"),
                    "username": info.get("username"),
                    "memory_percent": round(float(info.get("memory_percent") or 0.0), 2),
                    "status": info.get("status"),
                })
                if len(procs) >= cap:
                    truncated = True
                    break
        return {
            "processes": procs,
            "count": len(procs),
            "partial": partial,
            "truncated": truncated,
            "limit": cap,
        }

    def inspect_pid(self, pid: int) -> dict[str, Any]:
        if not isinstance(pid, int) or pid <= 0:
            return {"ok": False, "pid": pid, "error": "unknown"}
        errors: list[str] = []

        def _note(field: str, exc: BaseException) -> None:
            if isinstance(exc, psutil.AccessDenied):
                errors.append(f"{field}: access denied")
            elif isinstance(exc, psutil.NoSuchProcess):
                errors.append(f"{field}: process disappeared")
            else:
                errors.append(f"{field}: unknown")

        try:
            p = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return {"ok": False, "pid": pid, "error": "process disappeared"}
        except psutil.AccessDenied:
            return {"ok": False, "pid": pid, "error": "access denied"}
        except (ValueError, TypeError, psutil.Error):
            return {"ok": False, "pid": pid, "error": "unknown"}

        out: dict[str, Any] = {
            "ok": True,
            "pid": pid,
            "name": "",
            "exe": "",
            "status": "",
            "ppid": None,
            "parent": None,
            "children": [],
            "remote_endpoints": [],
            "num_threads": 1,
        }
        try:
            out["name"] = p.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error) as exc:
            _note("name", exc)
        try:
            out["exe"] = p.exe() if hasattr(p, "exe") else ""
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error) as exc:
            _note("exe", exc)
        try:
            out["status"] = p.status()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error) as exc:
            _note("status", exc)
        try:
            out["ppid"] = p.ppid()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error) as exc:
            _note("ppid", exc)
        try:
            parent = p.parent()
            if parent is not None:
                parent_row = {"pid": parent.pid, "name": "", "exe": ""}
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
                    parent_row["name"] = parent.name()
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
                    parent_row["exe"] = parent.exe()
                out["parent"] = parent_row
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error) as exc:
            _note("parent", exc)
        truncated_fields: list[str] = []
        try:
            kids: list[dict[str, Any]] = []
            raw_kids = list(p.children(recursive=False))
            if len(raw_kids) > MAX_CHILDREN:
                truncated_fields.append("children")
                raw_kids = raw_kids[:MAX_CHILDREN]
            for child in raw_kids:
                row = {"pid": child.pid, "name": ""}
                with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
                    row["name"] = child.name()
                kids.append(row)
            out["children"] = kids
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error) as exc:
            _note("children", exc)

        def _map_remote_endpoints(conns: Any) -> list[dict[str, Any]]:
            endpoints: list[dict[str, Any]] = []
            for conn in conns:
                raddr = getattr(conn, "raddr", None)
                if not raddr:
                    continue
                ip = getattr(raddr, "ip", None) or (raddr[0] if isinstance(raddr, tuple) else "")
                port = getattr(raddr, "port", None)
                if port is None and isinstance(raddr, tuple) and len(raddr) > 1:
                    port = raddr[1]
                if not ip:
                    continue
                if len(endpoints) >= MAX_CONNECTIONS:
                    if "remote_endpoints" not in truncated_fields:
                        truncated_fields.append("remote_endpoints")
                    break
                endpoints.append({
                    "ip": ip,
                    "port": port,
                    "status": getattr(conn, "status", ""),
                })
            return endpoints

        try:
            # Primary: process-scoped enumeration (unchanged contract).
            if hasattr(p, "net_connections"):
                conns = p.net_connections(kind="inet")
            else:
                conns = p.connections(kind="inet")
            endpoints = _map_remote_endpoints(conns)
            # Windows child Process.net_connections can silently return []
            # while the same pid still has remotes in the system inet table.
            # Fall back once, filtered by exact pid; never invent endpoints.
            if not endpoints:
                try:
                    system = psutil.net_connections(kind="inet")
                except (psutil.AccessDenied, psutil.Error) as exc:
                    _note("connections", exc)
                else:
                    matched = [
                        conn
                        for conn in system
                        if getattr(conn, "pid", None) == pid
                    ]
                    endpoints = _map_remote_endpoints(matched)
            out["remote_endpoints"] = endpoints
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error) as exc:
            _note("connections", exc)
        try:
            out["num_threads"] = p.num_threads() if hasattr(p, "num_threads") else 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error) as exc:
            _note("threads", exc)
        if truncated_fields:
            out["truncated"] = True
            out["truncated_fields"] = truncated_fields
        if errors:
            out["partial"] = True
            out["errors"] = errors
        if not out["name"] and any(e.startswith("name:") for e in errors):
            out["partial"] = True
        return out

    def detect_rogue_processes(self) -> dict[str, Any]:
        flagged: list[dict[str, Any]] = []
        partial = False
        truncated = False
        deadline = time.monotonic() + SCAN_BUDGET_S
        suspicious_parents = frozenset({
            "winword.exe", "excel.exe", "powerpnt.exe", "acrobat.exe", "wmplayer.exe",
        })
        script_engines = frozenset({
            "powershell.exe", "cmd.exe", "wscript.exe", "cscript.exe", "mshta.exe",
        })

        for p in psutil.process_iter(["pid", "ppid", "name", "cmdline", "exe"]):
            if time.monotonic() >= deadline:
                partial = True
                break
            if len(flagged) >= MAX_FLAGGED:
                truncated = True
                break
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pname = (p.info.get("name") or "").lower()
                cmd = " ".join(p.info.get("cmdline") or []).lower()
                exe = (p.info.get("exe") or "").lower()

                # Heuristic: suspicious executable name or encoded payload
                if pname in self.suspicious_names or "-encodedcommand" in cmd or "-enc " in cmd:
                    if not _record_flag(flagged, {
                        "pid": p.info.get("pid"),
                        "name": p.info.get("name"),
                        "heuristic": True,
                        "reason": "suspicious executable name or encoded commandline",
                    }):
                        truncated = True
                        break

                # Heuristic: living-off-the-land parent-child lineage
                elif pname in script_engines:
                    try:
                        parent = p.parent()
                        if parent and parent.name().lower() in suspicious_parents:
                            if not _record_flag(flagged, {
                                "pid": p.info.get("pid"),
                                "name": p.info.get("name"),
                                "parent_pid": parent.pid,
                                "parent_name": parent.name(),
                                "heuristic": True,
                                "reason": (
                                    f"abnormal parent-child execution "
                                    f"({parent.name()} -> {p.name()})"
                                ),
                            }):
                                truncated = True
                                break
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                # Heuristic: executable running from temp directory.
                # A process can also match the name branch; each hit is recorded
                # separately and each append is capped so 39 + two reasons stays 40.
                if (
                    ("\\temp\\" in exe or "/tmp/" in exe or "\\appdata\\local\\temp\\" in exe)
                    and pname not in {"python.exe", "pytest.exe"}
                ):
                    if not _record_flag(flagged, {
                        "pid": p.info.get("pid"),
                        "name": p.info.get("name"),
                        "exe": p.info.get("exe"),
                        "heuristic": True,
                        "reason": "executable running directly from temporary directory",
                    }):
                        truncated = True
                        break

        return {
            "ok": True,
            "heuristic": True,
            "flagged_count": len(flagged),
            "flagged": flagged,
            "partial": partial,
            "truncated": truncated,
        }

    def audit_memory(self, threshold_pct: float = 85.0) -> dict[str, Any]:
        """Host RAM totals and process percents. Not a process-memory dump."""
        thresh = min(99.0, max(1.0, float(threshold_pct)))
        vm = psutil.virtual_memory()
        heap: list[tuple[float, int, dict[str, Any]]] = []
        deadline = time.monotonic() + SCAN_BUDGET_S
        partial = False
        for p in psutil.process_iter(["pid", "name", "memory_percent"]):
            if time.monotonic() >= deadline:
                partial = True
                break
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                mpct = float(p.info.get("memory_percent") or 0.0)
                if mpct >= 5.0:
                    rec = {
                        "pid": p.info.get("pid"),
                        "name": p.info.get("name"),
                        "memory_percent": round(mpct, 2),
                    }
                    _remember_top(heap, rec["memory_percent"], rec)
        top = [item[2] for item in sorted(heap, key=lambda row: row[0], reverse=True)]
        exceeded = vm.percent >= thresh
        return {
            "ok": True,
            "scope": "host_ram",
            "total_gb": round(vm.total / (1024**3), 2),
            "available_gb": round(vm.available / (1024**3), 2),
            "used_percent": vm.percent,
            "threshold_percent": thresh,
            "exceeded": exceeded,
            "top_consumers": top,
            "partial": partial,
        }

    async def execute(
        self,
        unit: SentinelUnit,
        task_payload: dict[str, Any],
        *,
        bus: EventBus,
        ledger: ReceiptLedger,
        nodes: dict[str, WorldNode],
    ) -> dict[str, Any]:
        op = str(task_payload.get("capability") or task_payload.get("action") or "process:list").strip()
        self.descriptor.assert_capability(op)

        # 1. State machine transitions
        unit.transition(
            SentinelState.VECTORING,
            task=f"[PROCESS] Vectoring -> {op}",
            target_position=[22.0, 3.0, 10.0],
        )
        await asyncio.sleep(0.04)

        unit.transition(
            SentinelState.ENGAGED_DEFENSE,
            task=f"[PROCESS] Auditing host: {op}",
            laser_active=True,
            laser_kind=self.descriptor.laser_kind,
        )

        t0 = time.perf_counter()
        result: dict[str, Any] = {}

        if op == "process:list":
            try:
                lim = int(task_payload.get("limit", 40))
            except (TypeError, ValueError):
                lim = 40
            listed = await asyncio.to_thread(self.list_processes, limit=lim)
            result = {"ok": True, **listed}

        elif op == "process:inspect_pid":
            raw_pid = task_payload.get("pid", 0)
            try:
                target_pid = int(raw_pid)
            except (TypeError, ValueError):
                result = {"ok": False, "pid": raw_pid, "error": "unknown"}
            else:
                result = await asyncio.to_thread(self.inspect_pid, target_pid)

        elif op == "process:detect_rogue":
            result = await asyncio.to_thread(self.detect_rogue_processes)

        elif op == "process:audit_memory":
            try:
                thresh = float(task_payload.get("threshold", 85.0))
            except (TypeError, ValueError):
                thresh = 85.0
            result = await asyncio.to_thread(self.audit_memory, threshold_pct=thresh)

        else:
            result = {"ok": False, "error": f"unsupported capability {op}"}

        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        unit.missions_completed += 1
        unit.bytes_processed += len(str(result))

        # 2. Return to patrol
        unit.transition(
            SentinelState.RETURNING,
            task=f"[PROCESS] Completed {op}",
            laser_active=False,
        )
        await asyncio.sleep(0.02)
        unit.transition(
            SentinelState.PATROLLING,
            task="Patrolling stalker sector",
            laser_active=False,
        )

        ok = bool(result.get("ok", True))
        receipt = ledger.mint(
            unit_id=unit.unit_id,
            caste=self.descriptor.caste_id,
            kind="defense",
            source=f"sentinel://process/{op}",
            span=f"Process Sentinel executed {op} (ok={ok}, duration={duration_ms}ms)",
            ok=ok,
            metadata={
                "capability": op,
                "duration_ms": duration_ms,
                "result_summary": {k: v for k, v in result.items() if k != "processes"},
            },
        )

        return {
            "ok": ok,
            "caste": self.descriptor.caste_id,
            "unit_id": unit.unit_id,
            "capability": op,
            "duration_ms": duration_ms,
            "result": result,
            "receipt": receipt.to_dict(),
        }


ProcessAuditorCaste = StalkerCaste

__all__ = ["ProcessAuditorCaste", "StalkerCaste"]
