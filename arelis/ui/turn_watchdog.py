"""Hung-turn ceiling. The 8s busy watchdog only arms after Stop.

A tool that never returns used to shimmer forever. This arms when the turn
starts and paints the remaining time on the progress line. Confirm wait is
a person, not a hang, so the ceiling pauses.

When the ceiling hits and the turn already has tool results, she closes
from that work instead of being cancelled. A shorter grace clock then
hard-stops only if that close never comes back. Nothing gathered yet
still cancels like Stop, worded as a hang.
"""

from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import QTimer

from arelis.ui.status_copy import WRAPUP_STATUS
from arelis.ui.window_const import (
    HUNG_CLOSE_GRACE_S,
    HUNG_TURN_MAX_S,
    HUNG_TURN_S,
    HUNG_TURN_TICK_MS,
)

_LEFT_SUFFIX = re.compile(r"(?:\s+\d+:\d{2} left)+$")

HUNG_MESSAGE = "Turn stopped because it hung."
WRAPUP_NOTE = "wrapping up with what I have"


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


def arm_hung_turn(window, *, ms: int | None = None) -> None:
    """Start the ceiling. Called from idle→busy, not after Stop.

    ``ms`` is the grace clock after a close has been asked for. The full
    ceiling is the default.
    """
    if ms is None:
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
    window._hung_closing = False
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


def _live_agent_loop(window):
    orch = getattr(window, "orchestrator", None)
    if orch is None:
        return None
    return getattr(orch, "_agent_loop", None)


def _has_gathered(loop) -> bool:
    """True when a close has something to tie together."""
    if loop is None or getattr(loop, "terminal_sent", False):
        return False
    if getattr(loop, "_in_close", False):
        return False
    if getattr(loop, "tools_used", None):
        return True
    return bool(getattr(loop, "_trace", None))


def _hard_hung(window) -> None:
    window._cancel_turn(schedule_next=True, reason="hung")
    window._assistant_streaming = False
    window._set_busy(False)


def _begin_close(window, loop) -> None:
    request = getattr(loop, "request_close", None)
    if not callable(request):
        _hard_hung(window)
        return
    request()
    window.thinking.append(WRAPUP_NOTE, kind="status")
    window.chat.show_progress(WRAPUP_STATUS)
    arm_hung_turn(window, ms=HUNG_CLOSE_GRACE_S * 1000)
    window._hung_closing = True


def on_hung_turn(window) -> None:
    """Ceiling hit. Close from work in hand, or cancel if there is none.

    A second hit while that close is still running is a real hang.
    """
    if getattr(window, "_force_quit", False) or getattr(window, "_disposed", False):
        return
    if getattr(window, "_confirm_waiting", False):
        arm_hung_turn(window)
        return
    if not getattr(window, "_turn_busy", False):
        return
    if getattr(window, "_hung_closing", False):
        _hard_hung(window)
        return
    loop = _live_agent_loop(window)
    if _has_gathered(loop):
        _begin_close(window, loop)
        return
    _hard_hung(window)
