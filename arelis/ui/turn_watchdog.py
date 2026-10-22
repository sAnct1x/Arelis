"""Hung-turn ceiling. The 8s busy watchdog only arms after Stop.

A tool that never returns used to shimmer forever. This arms when the turn
starts. The clock restarts on real progress: a streamed token, tool-argument
progress (same idle gap as a token), or a tool that is still running. A
phase line is not a token, an empty thinking event is not one either, a
cut-short note is not one, and the last tool call is not the clock. Silence
with none of those is a stall. The allowances are unchanged. The remaining
time stays off the shimmer, "thinking…" is the status, not a countdown.
Confirm wait is a person, not a hang, so the ceiling pauses.

When the ceiling hits and the turn already has tool results, she closes
from that work instead of being cancelled. A shorter grace clock then
hard-stops only if that close never comes back. Nothing gathered yet
still cancels like Stop, worded as a hang. The absolute cap still bounds
a tool that never returns.
"""

from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import QTimer

from arelis.core.events import EventType
from arelis.ui.status_copy import WRAPUP_STATUS
from arelis.ui.window_const import (
    HUNG_CLOSE_GRACE_S,
    HUNG_FIRST_TOKEN_S,
    HUNG_TURN_CAP_S,
    HUNG_TURN_MAX_S,
    HUNG_TURN_S,
)

# A status line or a confirm reply is life, but the next token is not due yet,
# so these restart the longer first-token allowance. Tool-argument progress
# is handled with streamed tokens (the idle gap). REPLY_NOTE stays out: a
# cut-short note is not proof the model is still writing.
_STEP_EVENTS = frozenset({EventType.TOOL_CONFIRM_REPLY, EventType.STATUS})

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


def _seconds_ms(config: dict[str, Any] | None, key: str, default: float) -> int:
    raw = ((config or {}).get("ui") or {}).get(key, default)
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        seconds = float(default)
    if seconds <= 0:
        return 0
    return max(1, int(min(seconds, float(HUNG_TURN_MAX_S)) * 1000))


def hung_first_token_ms(config: dict[str, Any] | None) -> int:
    return _seconds_ms(config, "hung_first_token_s", HUNG_FIRST_TOKEN_S)


def hung_idle_ms(config: dict[str, Any] | None) -> int:
    """ui.hung_turn_s: longest silence while tokens are streaming."""
    return hung_turn_ms(config)


def hung_cap_ms(config: dict[str, Any] | None) -> int:
    return _seconds_ms(config, "hung_turn_cap_s", HUNG_TURN_CAP_S)


def _cap_left_ms(window) -> int | None:
    started = getattr(window, "_hung_started", None)
    cap = getattr(window, "_hung_cap_ms", 0)
    if started is None or not cap:
        return None
    return max(1, cap - int((time.monotonic() - started) * 1000))


def _restart(window, allowance_ms: int) -> None:
    left = _cap_left_ms(window)
    ms = allowance_ms if allowance_ms > 0 else (left or 0)
    if left is not None:
        ms = min(ms, left) if ms else left
    if ms <= 0:
        return
    window._hung_watchdog.start(int(ms))


def _payload(event) -> dict[str, Any]:
    raw = getattr(event, "payload", None)
    return raw if isinstance(raw, dict) else {}


def _streamed_token(event) -> bool:
    """A token that actually arrived.

    A phase line has no stream flag. An empty thinking event, including one
    marked stream, has no text. Neither is progress.
    """
    kind = getattr(event, "type", None)
    payload = _payload(event)
    if kind == EventType.ASSISTANT_DELTA:
        return bool(payload.get("text"))
    if kind == EventType.ASSISTANT_RETRACT:
        return True
    if kind != EventType.THINKING or not payload.get("stream"):
        return False
    return bool(str(payload.get("text") or "").strip())


def _clear_progress(window) -> None:
    window._hung_tool_running = False


def _past_cap(window) -> bool:
    started = getattr(window, "_hung_started", None)
    cap = int(getattr(window, "_hung_cap_ms", 0) or 0)
    if started is None or cap <= 0:
        return False
    return (time.monotonic() - started) * 1000 >= cap


def note_turn_progress(window, event) -> None:
    """Push the hang clock out on real progress.

    A streamed token, or tool-argument progress that carries a sentence,
    resets to the idle gap. A tool that is in flight, a tool result, or a
    status line resets to the first-token allowance, because the next token
    is not due yet. A trace line such as ``phase=model``, a thinking event
    with no text, an empty argument-progress line, and a cut-short note do
    not. The absolute cap is never extended.
    """
    timer = getattr(window, "_hung_watchdog", None)
    if timer is None or not timer.isActive():
        return
    if not getattr(window, "_turn_busy", False) or getattr(window, "_hung_closing", False):
        return
    kind = getattr(event, "type", None)
    config = getattr(window, "config", None)
    if kind == EventType.TOOL_START:
        window._hung_tool_running = True
        _restart(window, hung_first_token_ms(config))
        return
    if kind == EventType.TOOL_RESULT:
        window._hung_tool_running = False
        _restart(window, hung_first_token_ms(config))
        return
    if _streamed_token(event):
        _restart(window, hung_idle_ms(config))
        return
    # Every 64 new argument characters. That is work, same as a token, so
    # the idle gap starts over. The 600s cap is applied inside _restart.
    if kind == EventType.TOOL_ARG_PROGRESS and str(_payload(event).get("message") or "").strip():
        _restart(window, hung_idle_ms(config))
        return
    if kind in _STEP_EVENTS:
        _restart(window, hung_first_token_ms(config))


def ensure_hung_timers(window) -> None:
    if getattr(window, "_hung_watchdog", None) is not None:
        return
    ceiling = QTimer(window)
    ceiling.setSingleShot(True)
    ceiling.timeout.connect(window._on_hung_turn)
    window._hung_watchdog = ceiling


def arm_hung_turn(window, *, ms: int | None = None) -> None:
    """Start the ceiling. Called from idle→busy, not after Stop.

    ``ms`` is the grace clock after a close has been asked for. The full
    ceiling is the default.
    """
    window._hung_paused_ms = None
    if ms is None:
        config = getattr(window, "config", None)
        if hung_turn_ms(config) <= 0:
            disarm_hung_turn(window)
            return
        window._hung_started = time.monotonic()
        window._hung_cap_ms = hung_cap_ms(config)
        ensure_hung_timers(window)
        _restart(window, hung_first_token_ms(config))
        return
    if ms <= 0:
        disarm_hung_turn(window)
        return
    ensure_hung_timers(window)
    window._hung_watchdog.start(ms)


def disarm_hung_turn(window) -> None:
    window._hung_paused_ms = None
    window._hung_closing = False
    _clear_progress(window)
    timer = getattr(window, "_hung_watchdog", None)
    if timer is not None:
        timer.stop()


def pause_hung_turn(window) -> None:
    """Allow card is the user's turn. Do not count that as hung."""
    timer = getattr(window, "_hung_watchdog", None)
    if timer is None or not timer.isActive():
        return
    window._hung_paused_ms = max(1, int(timer.remainingTime()))
    timer.stop()


def resume_hung_turn(window) -> None:
    leftover = getattr(window, "_hung_paused_ms", None)
    window._hung_paused_ms = None
    if leftover is None or not getattr(window, "_turn_busy", False):
        return
    if getattr(window, "_force_quit", False) or getattr(window, "_disposed", False):
        return
    ensure_hung_timers(window)
    window._hung_watchdog.start(int(leftover))


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
    # Still inside a tool call. That is progress, until the whole-turn cap.
    if getattr(window, "_hung_tool_running", False) and not _past_cap(window):
        _restart(window, hung_first_token_ms(getattr(window, "config", None)))
        return
    loop = _live_agent_loop(window)
    if _has_gathered(loop):
        _begin_close(window, loop)
        return
    _hard_hung(window)
