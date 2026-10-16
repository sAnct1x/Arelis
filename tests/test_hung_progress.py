"""Fail-first: hung means no progress, not a long turn (10Q Q8 and Q10).

Events go through the real BusBridge -> dispatch_event wiring, the same path
launch.py uses, so a helper-only reset cannot hide a miss.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest

from arelis.core.events import Event, EventType
from arelis.llm.prompt_progress import prompt_read_from_chunk, prompt_read_position


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
    """The clock follows real progress, not the last tool call.

    A running tool outlives the gap. After it returns, a prompt read that
    keeps moving forward does too. The same cursor again is not progress,
    and silence after that is the hang. A phase line is not a token.
    """
    assert prompt_read_position(
        "slot print_timing: id  0 | task 2313 | "
        "prompt processing, n_tokens = 4096, progress = 0.27"
    ) == 4096
    assert prompt_read_position(
        'msg="Prompt processing progress" processed=2048 total=109972'
    ) == 2048
    assert prompt_read_position("prompt processing, n_tokens = 4096") == 4096
    assert prompt_read_position("not a progress line") is None
    assert prompt_read_from_chunk({"prompt_eval_completed": 512}) == 512
    assert prompt_read_from_chunk({"prompt_eval_count": 512}) is None

    window = arelis_window(_cfg(idle=0.3, first=0.3))
    window._set_busy(True)
    window.bridge.event_arrived.emit(
        Event(EventType.TOOL_START, {"tool": "python", "args": {}})
    )
    window.bridge.event_arrived.emit(
        Event(EventType.THINKING, {"text": "phase=model role=fast hold_paint=1"})
    )
    QTest.qWait(1000)
    assert window._turn_busy, "turn was cut while a tool was still running"
    assert not _hung_shown(window)

    window.bridge.event_arrived.emit(
        Event(EventType.TOOL_RESULT, {"tool": "python", "ok": True, "output": "ok"})
    )
    pos = {"n": 0}

    def tick() -> None:
        pos["n"] += 512
        window.bridge.event_arrived.emit(
            Event(EventType.THINKING, {"prompt_read": pos["n"]})
        )

    drip = QTimer(window)
    drip.timeout.connect(tick)
    drip.start(50)
    QTest.qWait(1000)
    drip.stop()
    assert window._turn_busy, "turn was cut while the prompt read moved forward"
    assert not _hung_shown(window)

    window.bridge.event_arrived.emit(
        Event(EventType.THINKING, {"prompt_read": pos["n"]})
    )
    QTest.qWait(900)
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


