"""Deterministic hive responses to host alerts already collected by Sentinel.

This is hive automation on a timer: the same process that scans sockets and
Merkle roots may retask an idle Warden or Tripwire. It is not an Arelis
model decision and does not close that gap. It never installs a firewall
rule, never kills a process, never heals files, and never widens send.

Cooldown is per (kind, signature) on time.monotonic(). Expired entries are
dropped. The table is capped; if it is full of live entries, new signatures
are refused (rate-limited). Evicting a live entry to make room would let
alternating signatures bypass the cooldown.

Host observation (_scan_host_bundle) and a caste dispatch (patrol_scan or
verify) cannot overlap, and each is singleton. Dispatch runs the same
scanners as the observation bundle; overlapping them would multiply host
scans. Cancelling the asyncio waiter does not stop an off-thread scan;
the worker finally releases the scan slot.
"""

from __future__ import annotations

import time
from typing import Any

# Plan choice for this slice: observe and retask only. No auto-spawn,
# intercept, ban, or heal_root. Verbs match the caste execute() branches
# already used by the patrol sortie.
POLICY_ACTIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "exposure": ("warden", {"action": "patrol_scan", "animate": False}),
    "new_ports": ("warden", {"action": "patrol_scan", "animate": False}),
    "flood": ("warden", {"action": "patrol_scan", "animate": False}),
    "merkle": ("tripwire", {"action": "verify", "animate": False}),
    "canary": ("tripwire", {"action": "verify", "animate": False}),
}

POLICY_COOLDOWN_S = 60.0
MAX_POLICY_HISTORY = 32
MAX_COOLDOWN_ENTRIES = 64


class AlertPolicy:
    """Dedup, per-signature cooldown, and exclusive host-work slots."""

    def __init__(
        self,
        *,
        cooldown_s: float = POLICY_COOLDOWN_S,
        max_history: int = MAX_POLICY_HISTORY,
        max_cooldown_entries: int = MAX_COOLDOWN_ENTRIES,
    ) -> None:
        self.cooldown_s = float(cooldown_s)
        self.max_history = int(max_history)
        self.max_cooldown_entries = int(max_cooldown_entries)
        self._cooldown: dict[tuple[str, str], float] = {}
        self._scan = False
        self._dispatch = False
        self.history: list[dict[str, Any]] = []

    def _stamp(self, now: float | None) -> float:
        return time.monotonic() if now is None else now

    def _purge_expired(self, stamp: float) -> None:
        cutoff = stamp - self.cooldown_s
        stale = [key for key, seen in self._cooldown.items() if seen < cutoff]
        for key in stale:
            del self._cooldown[key]

    @property
    def cooldown_size(self) -> int:
        return len(self._cooldown)

    def scan_in_flight(self) -> bool:
        return self._scan

    def begin_scan(self) -> bool:
        """Claim the scan slot. Refuses if a scan or dispatch is already running.

        The worker thread must call end_scan; the awaiting coroutine must not.
        """
        if self._scan or self._dispatch:
            return False
        self._scan = True
        return True

    def end_scan(self) -> None:
        """Clear the scan slot. Called from the worker's finally, not the waiter."""
        self._scan = False

    def dispatch_in_flight(self) -> bool:
        return self._dispatch

    def begin_dispatch(self) -> bool:
        """Claim the dispatch slot. Refuses if a dispatch or scan is already running."""
        if self._dispatch or self._scan:
            return False
        self._dispatch = True
        return True

    def end_dispatch(self) -> None:
        self._dispatch = False

    def should_act(self, kind: str, signature: str, now: float | None = None) -> bool:
        if kind not in POLICY_ACTIONS or not signature:
            return False
        stamp = self._stamp(now)
        self._purge_expired(stamp)
        key = (kind, signature)
        prev = self._cooldown.get(key)
        if prev is not None and (stamp - prev) < self.cooldown_s:
            return False
        if key not in self._cooldown and len(self._cooldown) >= self.max_cooldown_entries:
            return False
        return True

    def mark_seen(self, kind: str, signature: str, now: float | None = None) -> None:
        stamp = self._stamp(now)
        self._purge_expired(stamp)
        key = (kind, signature)
        if key in self._cooldown or len(self._cooldown) < self.max_cooldown_entries:
            self._cooldown[key] = stamp

    def record(self, event: dict[str, Any]) -> None:
        self.history.append(dict(event))
        extra = len(self.history) - self.max_history
        if extra > 0:
            self.history = self.history[extra:]
