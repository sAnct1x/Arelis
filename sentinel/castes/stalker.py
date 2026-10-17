"""ProcessAuditorCaste — Real-Time Host Process & Memory Sentinel."""

from __future__ import annotations

import asyncio
import contextlib
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
        orbit_radius=26.0,
        orbit_y_band=3.0,
        speed_mult=1.1,
        eye_color="#ffd600",
        laser_kind="defense",
        doctrine="HUNTER-KILLER",
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self.suspicious_names = frozenset(
            cfg.get("suspicious_process_names") or _DEFAULT_SUSPICIOUS_NAMES
        )

    def list_processes(self, limit: int = 50) -> list[dict[str, Any]]:
        procs: list[dict[str, Any]] = []
        for p in psutil.process_iter(["pid", "name", "username", "memory_percent", "status"]):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                info = p.info
                procs.append({
                    "pid": info.get("pid"),
                    "name": info.get("name"),
                    "username": info.get("username"),
                    "memory_percent": round(float(info.get("memory_percent") or 0.0), 2),
                    "status": info.get("status"),
                })
                if len(procs) >= limit:
                    break
        return procs

    def inspect_pid(self, pid: int) -> dict[str, Any]:
        try:
            p = psutil.Process(pid)
            with p.oneshot():
                return {
                    "ok": True,
                    "pid": p.pid,
                    "name": p.name(),
                    "exe": p.exe() if hasattr(p, "exe") else "",
                    "cmdline": p.cmdline() if hasattr(p, "cmdline") else [],
                    "status": p.status(),
                    "memory_info": p.memory_info()._asdict() if hasattr(p, "memory_info") else {},
                    "cpu_percent": p.cpu_percent(interval=None),
                    "num_threads": p.num_threads() if hasattr(p, "num_threads") else 1,
                }
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            return {"ok": False, "pid": pid, "error": str(exc)}

    def detect_rogue_processes(self) -> dict[str, Any]:
        flagged: list[dict[str, Any]] = []
        suspicious_parents = frozenset({"winword.exe", "excel.exe", "powerpnt.exe", "acrobat.exe", "wmplayer.exe"})
        script_engines = frozenset({"powershell.exe", "cmd.exe", "wscript.exe", "cscript.exe", "mshta.exe"})

        for p in psutil.process_iter(["pid", "ppid", "name", "cmdline", "exe"]):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pname = (p.info.get("name") or "").lower()
                cmd = " ".join(p.info.get("cmdline") or []).lower()
                exe = (p.info.get("exe") or "").lower()

                # 1. Suspicious executable name or encoded payload
                if pname in self.suspicious_names or "-encodedcommand" in cmd or "-enc " in cmd:
                    flagged.append({
                        "pid": p.info.get("pid"),
                        "name": p.info.get("name"),
                        "reason": "suspicious executable name or encoded commandline",
                    })

                # 2. Living-off-the-land parent-child lineage anomaly
                elif pname in script_engines:
                    try:
                        parent = p.parent()
                        if parent and parent.name().lower() in suspicious_parents:
                            flagged.append({
                                "pid": p.info.get("pid"),
                                "name": p.info.get("name"),
                                "parent_pid": parent.pid,
                                "parent_name": parent.name(),
                                "reason": f"abnormal parent-child execution ({parent.name()} -> {p.name()})",
                            })
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

                # 3. Executable running from temp directory
                if (
                    ("\\temp\\" in exe or "/tmp/" in exe or "\\appdata\\local\\temp\\" in exe)
                    and pname not in {"python.exe", "pytest.exe"}
                    and not any(f["pid"] == p.info.get("pid") for f in flagged)
                ):
                    flagged.append({
                        "pid": p.info.get("pid"),
                        "name": p.info.get("name"),
                        "exe": p.info.get("exe"),
                        "reason": "executable running directly from temporary directory",
                    })


        return {
            "ok": len(flagged) == 0,
            "flagged_count": len(flagged),
            "flagged": flagged,
        }


    def audit_memory(self, threshold_pct: float = 85.0) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        hogs: list[dict[str, Any]] = []
        for p in psutil.process_iter(["pid", "name", "memory_percent"]):
            with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                mpct = float(p.info.get("memory_percent") or 0.0)
                if mpct >= 5.0:
                    hogs.append({
                        "pid": p.info.get("pid"),
                        "name": p.info.get("name"),
                        "memory_percent": round(mpct, 2),
                    })
        hogs.sort(key=lambda x: x["memory_percent"], reverse=True)
        exceeded = vm.percent >= threshold_pct
        return {
            "ok": not exceeded,
            "total_gb": round(vm.total / (1024**3), 2),
            "available_gb": round(vm.available / (1024**3), 2),
            "used_percent": vm.percent,
            "threshold_percent": threshold_pct,
            "exceeded": exceeded,
            "top_consumers": hogs[:10],
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
            lim = int(task_payload.get("limit", 40))
            procs = await asyncio.to_thread(self.list_processes, limit=lim)
            result = {"ok": True, "processes": procs, "count": len(procs)}

        elif op == "process:inspect_pid":
            target_pid = int(task_payload.get("pid", 0))
            result = await asyncio.to_thread(self.inspect_pid, target_pid)

        elif op == "process:detect_rogue":
            result = await asyncio.to_thread(self.detect_rogue_processes)

        elif op == "process:audit_memory":
            thresh = float(task_payload.get("threshold", 85.0))
            result = await asyncio.to_thread(self.audit_memory, threshold_pct=thresh)

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

__all__ = ["StalkerCaste", "ProcessAuditorCaste"]
