"""One thinking line, a quiet window, her face from the first screen."""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, QRect


def _plain(window) -> str:
    return window.chat.view.toPlainText()


def _thought_lines(window) -> str:
    lines: list[str] = []
    for thought in window.chat._thoughts:
        lines.extend(thought.lines)
        if thought.stream:
            lines.append(thought.stream)
    return "\n".join(lines)


class _PaintCount(QObject):
    def __init__(self, window) -> None:
        super().__init__()
        self.window = window
        self.panel = window.persona_panel
        self.avatar = window.persona_panel.avatar
        self.window_paints = 0
        self.full_window = 0
        self.panel_paints = 0
        self.full_panel = 0
        self.caption_paints = 0
        self.avatar_paints = 0
        self.on = False

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if not self.on or event.type() != QEvent.Type.Paint:
            return False
        rect = event.rect()
        if obj is self.window:
            self.window_paints += 1
            if rect.width() >= self.window.width() - 2 and rect.height() >= self.window.height() - 2:
                self.full_window += 1
        elif obj is self.panel:
            self.panel_paints += 1
            if rect.width() >= self.panel.width() - 2 and rect.height() >= self.panel.height() - 2:
                self.full_panel += 1
            caption = QRect(0, max(0, self.panel.height() - 92), self.panel.width(), 92)
            if caption.intersects(rect) and not self.avatar.geometry().contains(rect):
                self.caption_paints += 1
        elif obj is self.avatar:
            self.avatar_paints += 1
        return False


def _watch(qt_app, window, seconds: float) -> _PaintCount:
    counter = _PaintCount(window)
    qt_app.installEventFilter(counter)
    counter.on = True
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qt_app.processEvents()
        time.sleep(0.01)
    counter.on = False
    qt_app.removeEventFilter(counter)
    return counter


def test_one_thinking_line_and_the_stop_button(arelis_window, qt_app) -> None:
    """The collapsed thought line is the only thinking cue, and stop still works."""
    from arelis.core.events import Event, EventType
    from arelis.ui.event_host import dispatch_event

    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window._set_busy(True)
    window._show_model_loading("fast")
    qt_app.processEvents()
    placeholder = window.conversation.input.placeholderText()
    assert "thinking" not in placeholder.lower()
    progress = window.chat.progress.text()
    assert "thinking" not in progress.lower()
    assert window.chat.progress.isHidden()
    shown = _plain(window)
    assert "Thinking for" in shown
    assert "✦" not in shown
    assert window.conversation.stop_btn.isVisible()

    dispatch_event(
        window,
        Event(EventType.TOOL_START, {"tool": "weather", "args": {}}),
    )
    qt_app.processEvents()
    assert "checking the weather" in _thought_lines(window)
    assert "checking the weather" not in window.chat.progress.text()
    assert "thinking" not in window.chat.progress.text().lower()

    window.conversation.stop_btn.click()
    qt_app.processEvents()
    assert "stop requested" in _thought_lines(window) or "stop requested" in _plain(window)

    window._set_busy(False)
    qt_app.processEvents()
    assert "Thought for" in _plain(window)
    assert "Thinking for" not in _plain(window)


def test_nothing_sits_in_the_bottom_right(arelis_window, qt_app, caplog) -> None:
    """Timing and the thinking caption stay off the glass. The log still gets the line."""
    import logging

    window = arelis_window()
    window.show()
    window.persona_dock.show()
    qt_app.processEvents()
    window._set_busy(True)
    qt_app.processEvents()
    assert window.persona_panel.caption_text() == ""
    line = "timing total=1.2s model=1.0s prefill=0.8s"
    with caplog.at_level(logging.INFO, logger="arelis.ui.panels.thinking"):
        window.thinking.append(line, kind="trace")
        window.thinking.extend_stream("timing total=9.0s model=8.0s")
    qt_app.processEvents()
    assert "timing total" in caplog.text
    assert window.persona_panel.status_text() == ""
    assert "timing" not in window.chat.progress.text().lower()
    assert "timing total" not in _plain(window)
    assert "timing total" not in _thought_lines(window)
    window._set_busy(False)
    qt_app.processEvents()
    assert window.persona_panel.status_text() == ""
    assert window.persona_panel.caption_text() != "thinking"


def test_she_is_on_the_welcome_screen_and_bake_is_not_during_the_turn(
    arelis_window, qt_app
) -> None:
    """Her dock is up before the first message, and the bake does not start mid-turn."""
    window = arelis_window()
    calls: list[bool] = []
    avatar = window.persona_panel.avatar
    original = avatar._start_bake

    def wrapped() -> None:
        calls.append(bool(window._turn_busy))
        original()

    avatar._start_bake = wrapped  # type: ignore[method-assign]
    window.resize(1440, 900)
    window.show()
    end = time.monotonic() + 0.7
    while time.monotonic() < end:
        qt_app.processEvents()
        time.sleep(0.01)
    assert not window.persona_dock.isHidden()
    assert window.chat.empty.isVisible()
    welcome = window.persona_dock.geometry()
    assert welcome.width() >= 220
    assert calls and not any(calls)
    calls.clear()
    window.chat.add_user("hello")
    window._set_busy(True)
    for _ in range(6):
        qt_app.processEvents()
    chatting = window.persona_dock.geometry()
    assert abs(welcome.x() - chatting.x()) <= 4
    assert abs(welcome.width() - chatting.width()) <= 4
    assert calls == []


