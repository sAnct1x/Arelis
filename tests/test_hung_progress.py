"""Fail-first: hung means no progress, not a long turn (10Q Q8 and Q10).

Events go through the real BusBridge -> dispatch_event wiring, the same path
launch.py uses, so a helper-only reset cannot hide a miss.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest

from arelis.core.events import Event, EventType


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


def test_silent_stream_is_still_a_hang(arelis_window, qt_app) -> None:
    window = arelis_window(_cfg(idle=0.2, first=0.4))
    window._set_busy(True)
    QTest.qWait(700)
    assert window._turn_busy is False
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


def test_prefill_gets_the_first_token_allowance(arelis_window, qt_app) -> None:
    window = arelis_window(_cfg(idle=0.2, first=1.0))
    window._set_busy(True)
    QTest.qWait(600)           # past the idle gap, inside the first-token allowance
    assert window._turn_busy, "a silent prefill was judged by the idle gap"


def test_tool_result_restarts_the_first_token_allowance(arelis_window, qt_app) -> None:
    window = arelis_window(_cfg(idle=0.2, first=0.6))
    window._set_busy(True)
    window.bridge.event_arrived.emit(Event(EventType.THINKING, {"text": "x", "stream": True}))
    QTest.qWait(100)
    window.bridge.event_arrived.emit(Event(EventType.TOOL_RESULT, {"tool": "vision", "ok": True, "data": {}}))
    QTest.qWait(400)           # next round prefills: longer than idle, shorter than first
    assert window._turn_busy


def test_cap_still_ends_a_runaway_thinker(arelis_window, qt_app) -> None:
    window = arelis_window(_cfg(idle=0.3, first=0.3, cap=0.8))
    window._set_busy(True)
    drip = _drip(window, EventType.THINKING, {"text": "hmm ", "stream": True})
    QTest.qWait(1300)
    drip.stop()
    assert window._turn_busy is False
    assert _hung_shown(window)
