"""Software emergency stop for Sentinel.

When triggered by the human Overseer or Arelis, the EMP immediately:
1. Cancels all active asyncio mission tasks across all Sentinel castes.
2. Closes external HTTP connection pools for registered clients.
3. Transitions every SentinelUnit into EMP_DISABLED (lasers off, thrusters cut).
4. Broadcasts an EMP_TRIGGERED shockwave event to the 3D Overseer viewport.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from sentinel.core.bus import EventBus, EventTopic
from sentinel.core.fsm import SentinelState, SentinelUnit
from sentinel.paths import emp_flag_path

log = logging.getLogger("sentinel.emp")

_EMP_FLAG_VALUE = "1"


def write_emp_flag(path: Path | None = None) -> None:
    """Atomically persist the software stop. Same-dir temp file, then replace."""
    dest = path or emp_flag_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.tmp")
    tmp.write_text(f"{_EMP_FLAG_VALUE}\n", encoding="utf-8")
    tmp.replace(dest)


def clear_emp_flag(path: Path | None = None) -> None:
    dest = path or emp_flag_path()
    dest.unlink(missing_ok=True)


def load_emp_flag(path: Path | None = None) -> bool:
    """Return True only for a well-formed persisted stop.

    Missing or corrupt files are not tripped. The flag is a positive assertion
    that EMP is active. A fresh data dir has no file and must boot enabled.
    Restore clears by deleting the file. Garbage is not a proven trigger.
    """
    dest = path or emp_flag_path()
    try:
        raw = dest.read_text(encoding="utf-8")
    except OSError:
        return False
    return raw.strip() == _EMP_FLAG_VALUE


class EMPController:
    """Tracked-task cancellation and registered-client shutdown controller."""

    def __init__(self, bus: EventBus, *, tripped: bool = False) -> None:
        self._bus = bus
        self._armed = True
        self._tripped = tripped
        self._tripped_at: float | None = None
        self._tripped_reason: str = "Persisted EMP stop" if tripped else ""
        self._active_tasks: set[asyncio.Task[Any]] = set()
        self._close_callbacks: list[Any] = []

    @property
    def is_tripped(self) -> bool:
        return self._tripped

    @property
    def status(self) -> dict[str, Any]:
        return {
            "armed": self._armed,
            "tripped": self._tripped,
            "tripped_at": self._tripped_at,
            "reason": self._tripped_reason,
            "active_tasks_tracked": len(self._active_tasks),
        }

    def track_task(self, task: asyncio.Task[Any]) -> asyncio.Task[Any]:
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)
        return task

    def register_closer(self, closer: Any) -> None:
        self._close_callbacks.append(closer)

    async def trigger_emp(
        self,
        units: dict[str, SentinelUnit],
        *,
        reason: str = "Overseer Manual EMP Kill-Switch",
    ) -> dict[str, Any]:
        """Execute immediate EMP blast: cancel all tasks, close sockets, disable units."""
        t0 = time.perf_counter()
        self._tripped = True
        self._tripped_at = time.time()
        self._tripped_reason = reason
        try:
            write_emp_flag()
        except OSError:
            log.exception("Failed to persist EMP stop flag")

        tasks_to_cancel = list(self._active_tasks)
        cancelled_count = 0
        for t in tasks_to_cancel:
            if not t.done():
                t.cancel()
                cancelled_count += 1

        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
        self._active_tasks.clear()

        for closer in self._close_callbacks:
            try:
                res = closer()
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                log.exception("Error running EMP closer")

        disabled_units = 0
        for unit in units.values():
            unit.transition(
                SentinelState.EMP_DISABLED,
                task=f"EMP HALTED ({reason})",
                laser_active=False,
                carrying_orb=False,
            )
            disabled_units += 1

        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        summary = {
            "ok": True,
            "tripped": True,
            "reason": reason,
            "tasks_cancelled": cancelled_count,
            "units_disabled": disabled_units,
            "halt_latency_ms": elapsed_ms,
        }
        await self._bus.publish(EventTopic.EMP_TRIGGERED, summary)
        log.warning("EMP TRIGGERED (%s): %d tasks cancelled, %d units disabled in %.3f ms",
                    reason, cancelled_count, disabled_units, elapsed_ms)
        return summary

    async def restore_swarm(self, units: dict[str, SentinelUnit]) -> dict[str, Any]:
        """Clear EMP lockout and return all Sentinel units to PATROLLING formation."""
        self._tripped = False
        self._tripped_reason = ""
        try:
            clear_emp_flag()
        except OSError:
            log.exception("Failed to clear EMP stop flag")
        restored = 0
        for unit in units.values():
            if unit.state == SentinelState.EMP_DISABLED:
                unit.transition(
                    SentinelState.PATROLLING,
                    task=f"Patrolling {unit.caste} ring",
                    laser_active=False,
                    carrying_orb=False,
                    force_restore=True,
                )
                restored += 1
        summary = {"ok": True, "tripped": False, "units_restored": restored}
        await self._bus.publish(EventTopic.EMP_RESET, summary)
        return summary
