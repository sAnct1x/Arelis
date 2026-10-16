"""Fail-first: hung means no progress, not a long turn (10Q Q8 and Q10).

Events go through the real BusBridge -> dispatch_event wiring, the same path
launch.py uses, so a helper-only reset cannot hide a miss.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest

from arelis.core.events import Event, EventType
from arelis.ui.window_const import HUNG_TURN_CAP_S


def _cfg(idle: float, first: float, cap: float = 30.0) -> dict:
    return {"ui": {"default_width": 800, "default_height": 600,
                   "hung_turn_s": idle, "hung_first_token_s": first,
                   "hung_turn_cap_s": cap}}


def _drip(window, kind: EventType, payload: dict, every_ms: int = 50):
    timer = QTimer(window)
    timer.timeout.connect(lambda: window.bridge.event_arrived.emit(Event(kind, dict(payload))))
    timer.start(every_ms)
    return timer


def _hung_shown(window) -> bool:
    return "hung" in window.chat.view.toPlainText().lower()


def test_streaming_thinking_is_not_a_hang(arelis_window, qt_app) -> None:
    window = arelis_window(_cfg(idle=0.3, first=0.3))
    window._set_busy(True)
    drip = _drip(window, EventType.THINKING, {"text": "hmm ", "stream": True})
    QTest.qWait(1200)          # four times the idle gap, all of it thinking
    drip.stop()
    assert window._turn_busy, "turn was cut while thinking tokens streamed"
    assert not _hung_shown(window)


def test_streaming_answer_is_not_a_hang(arelis_window, qt_app) -> None:
    window = arelis_window(_cfg(idle=0.3, first=0.3))
    window._set_busy(True)
    drip = _drip(window, EventType.ASSISTANT_DELTA, {"text": "word "})
    QTest.qWait(1200)
    drip.stop()
    assert window._turn_busy
    assert not _hung_shown(window)


def test_stall_clock_follows_progress_not_the_last_tool_call(arelis_window, qt_app) -> None:
    """Real progress is a token or a tool in flight, not the last tool call.

    A phase line does not reset the clock, even when more of them arrive
    for longer than the first-token allowance. An empty thinking event
    does not either. A tool that never returns still dies at the cap.
    The product cap stays 600s; the tool step uses a short one so the
    same check does not wait that long.
    """
    assert HUNG_TURN_CAP_S == 600

    # Repeating a phase line must not refresh the first-token allowance.
    # The wait is several times that allowance so a slow runner still
    # crosses it, and a reset on each line would keep the turn alive.
    window = arelis_window(_cfg(idle=0.4, first=0.6, cap=30.0))
    window._set_busy(True)
    phase = _drip(
        window,
        EventType.THINKING,
        {"text": "phase=model role=fast hold_paint=1"},
        every_ms=80,
    )
    QTest.qWait(2500)
    phase.stop()
    assert window._turn_busy is False, "a phase line reset the stall clock"
    assert _hung_shown(window)

    window = arelis_window(_cfg(idle=0.4, first=0.6, cap=30.0))
    window._set_busy(True)
    drip = _drip(window, EventType.THINKING, {"stream": True}, every_ms=80)
    QTest.qWait(2500)
    drip.stop()
    assert window._turn_busy is False, "an empty thinking event reset the stall clock"
    assert _hung_shown(window)

    window = arelis_window(_cfg(idle=0.4, first=0.4, cap=4.0))
    window._set_busy(True)
    window.bridge.event_arrived.emit(
        Event(EventType.TOOL_START, {"tool": "python", "args": {}})
    )
    QTest.qWait(1500)
    assert window._turn_busy, "turn was cut while a tool was still running"
    assert not _hung_shown(window)
    QTest.qWait(3500)
    assert window._turn_busy is False, "a hung tool outlived the cap"
    assert _hung_shown(window)


def test_silence_after_thinking_is_a_hang(arelis_window, qt_app) -> None:
    window = arelis_window(_cfg(idle=0.3, first=5.0))
    window._set_busy(True)
    drip = _drip(window, EventType.THINKING, {"text": "hmm ", "stream": True})
    QTest.qWait(600)
    drip.stop()
    assert window._turn_busy
    QTest.qWait(700)           # idle gap passes with nothing streaming
    assert window._turn_busy is False
    assert _hung_shown(window)
