"""Hung-turn ceiling. The 8s busy watchdog only arms after Stop.

A tool that never returns used to shimmer forever. This arms when the turn
starts, paints the remaining time on the existing progress line, and unlocks
through the same cancel path Stop uses — with a hung message, not "stop
requested". Confirm wait is a person, not a hang, so the ceiling pauses.
"""

from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import QTimer

from arelis.ui.window_const import (
    HUNG_TURN_MAX_S,
    HUNG_TURN_S,
    HUNG_TURN_TICK_MS,
)

_LEFT_SUFFIX = re.compile(r"(?:\s+\d+:\d{2} left)+$")

HUNG_MESSAGE = "Turn stopped because it hung."


def hung_turn_ms(config: dict[str, Any] | None) -> int:
    raw = ((config or {}).get("ui") or {}).get("hung_turn_s", HUNG_TURN_S)
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        seconds = float(HUNG_TURN_S)
    if seconds <= 0:
        return 0
    seconds = min(seconds, float(HUNG_TURN_MAX_S))
    return max(1, int(seconds * 1000))


def format_hung_left(remaining_s: int) -> str:
    remaining_s = max(0, int(remaining_s))
    return f"{remaining_s // 60}:{remaining_s % 60:02d} left"


def ensure_hung_timers(window) -> None:
    if getattr(window, "_hung_watchdog", None) is not None:
        return
    ceiling = QTimer(window)
    ceiling.setSingleShot(True)
    ceiling.timeout.connect(window._on_hung_turn)
    window._hung_watchdog = ceiling
    tick = QTimer(window)
    tick.setInterval(HUNG_TURN_TICK_MS)
    tick.timeout.connect(window._on_hung_tick)
    window._hung_tick = tick


def arm_hung_turn(window) -> None:
    """Start the ceiling. Called from idle→busy, not after Stop."""
    ms = hung_turn_ms(getattr(window, "config", None))
    window._hung_paused_ms = None
    if ms <= 0:
        disarm_hung_turn(window)
        return
    ensure_hung_timers(window)
    window._hung_watchdog.start(ms)
    window._hung_tick.start()
    paint_hung_countdown(window)


def disarm_hung_turn(window) -> None:
    window._hung_paused_ms = None
    timer = getattr(window, "_hung_watchdog", None)
    if timer is not None:
        timer.stop()
    tick = getattr(window, "_hung_tick", None)
    if tick is not None:
        tick.stop()


def pause_hung_turn(window) -> None:
    """Allow card is the user's turn. Do not count that as hung."""
    timer = getattr(window, "_hung_watchdog", None)
    if timer is None or not timer.isActive():
        return
    window._hung_paused_ms = max(1, int(timer.remainingTime()))
    timer.stop()
    tick = getattr(window, "_hung_tick", None)
    if tick is not None:
        tick.stop()


def resume_hung_turn(window) -> None:
    leftover = getattr(window, "_hung_paused_ms", None)
    window._hung_paused_ms = None
    if leftover is None or not getattr(window, "_turn_busy", False):
        return
    if getattr(window, "_force_quit", False) or getattr(window, "_disposed", False):
        return
    ensure_hung_timers(window)
    window._hung_watchdog.start(int(leftover))
    window._hung_tick.start()
    paint_hung_countdown(window)


def paint_hung_countdown(window) -> None:
    timer = getattr(window, "_hung_watchdog", None)
    if timer is None or not timer.isActive() or not getattr(window, "_turn_busy", False):
        return
    ms = int(timer.remainingTime())
    if ms < 0:
        return
    remaining_s = (ms + 999) // 1000
    current = ""
    progress = getattr(getattr(window, "chat", None), "progress", None)
    if progress is not None:
        current = str(progress.text() or "")
    base = _LEFT_SUFFIX.sub("", current).rstrip()
    if not base:
        base_fn = getattr(window, "_busy_status_line", None)
        base = base_fn() if callable(base_fn) else ""
    if not base:
        return
    window.chat.show_progress(f"{base}  {format_hung_left(remaining_s)}")


def on_hung_tick(window) -> None:
    if getattr(window, "_force_quit", False) or getattr(window, "_disposed", False):
        return
    paint_hung_countdown(window)


def on_hung_turn(window) -> None:
    """Ceiling hit. Same cancel as Stop, then unlock immediately."""
    if getattr(window, "_force_quit", False) or getattr(window, "_disposed", False):
        return
    if getattr(window, "_confirm_waiting", False):
        arm_hung_turn(window)
        return
    if not getattr(window, "_turn_busy", False):
        return
    window._cancel_turn(schedule_next=True, reason="hung")
    window._assistant_streaming = False
    window._set_busy(False)
