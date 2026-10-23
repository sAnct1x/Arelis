"""The live thinking timer must not yank the chat scrollbar."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest


def _panel(qt_app):
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.resize(480, 240)
    panel.show()
    qt_app.processEvents()
    for i in range(16):
        panel.add_user("user line " + str(i) + " " + ("word " * 12))
        panel.begin_assistant()
        panel.finish_assistant("reply line " + str(i) + " " + ("word " * 12))
    qt_app.processEvents()
    QTest.qWait(80)
    return panel


def _settle(qt_app) -> None:
    qt_app.processEvents()
    QTest.qWait(80)
    qt_app.processEvents()


def _stream(panel, qt_app, text: str) -> None:
    panel.append_delta(text)
    panel._flush_stream_paint()
    qt_app.processEvents()


def test_thought_timer_tick_keeps_scroll_position(qt_app) -> None:
    """Thought ticks and a live reply stay at the bottom, and stop if the user scrolls up."""
    panel = _panel(qt_app)
    bar = panel.view.verticalScrollBar()
    assert bar.maximum() > 200

    panel.mark_turn(True)
    thought = panel._live_thought()
    assert thought is not None
    thought.started = time.monotonic() - 4
    panel._repaint_thought(thought)
    _settle(qt_app)
    assert "Thinking for 4s" in panel.view.toPlainText()

    bar.setValue(bar.maximum())
    _settle(qt_app)
    assert bar.value() == bar.maximum()
    thought.started = time.monotonic() - 9
    panel._tick_thought()
    _settle(qt_app)
    assert "Thinking for 9s" in panel.view.toPlainText()
    assert bar.value() == bar.maximum()

    parked = max(0, bar.maximum() - 200)
    bar.setValue(parked)
    _settle(qt_app)
    parked = bar.value()
    assert parked < bar.maximum() - 48
    thought.started = time.monotonic() - 12
    panel._tick_thought()
    _settle(qt_app)
    assert "Thinking for 12s" in panel.view.toPlainText()
    assert bar.value() == parked

    bar.setValue(bar.maximum())
    _settle(qt_app)
    panel.begin_assistant()
    qt_app.processEvents()
    for i in range(8):
        _stream(panel, qt_app, "stream " + str(i) + " " + ("word " * 16) + "\n")
        assert bar.value() == bar.maximum()

    # QTextBrowser grows max after the paint pin. A follower has to move
    # with that range change, or the last line sits off-screen.
    late = bar.maximum() + 80
    bar.setMaximum(late)
    qt_app.processEvents()
    assert bar.value() == bar.maximum()
    assert bar.maximum() == late

    bar.setValue(bar.maximum())
    qt_app.processEvents()
    assert bar.value() == bar.maximum()
    _stream(panel, qt_app, "more " * 24 + "\n")
    assert bar.value() == bar.maximum()

    parked = max(0, bar.maximum() - 200)
    bar.setValue(parked)
    qt_app.processEvents()
    parked = bar.value()
    assert parked < bar.maximum() - 48
    _stream(panel, qt_app, "after scroll up " * 20 + "\n")
    _settle(qt_app)
    assert bar.value() == parked
    del qt_app
