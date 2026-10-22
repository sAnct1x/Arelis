"""Pins markdown render, chat bubble replace, inbound notice, and CLI consent."""
from __future__ import annotations

import pytest

from arelis.core.bus import EventBus

# The offscreen qt_app fixture now lives in tests/conftest.py, shared with the
# voice tests rather than defined twice.

# --------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Chat panel: streaming draft, then the rendered answer
# --------------------------------------------------------------------------


def _reply_cells(panel, pos: int) -> list[str]:
    """Plain text of each message cell that starts at or after pos."""
    from PySide6.QtGui import QTextCursor, QTextTable

    from arelis.ui.panels.chat import _marked_bubble

    found: list[str] = []

    def walk(frame) -> None:
        it = frame.begin()
        while not it.atEnd():
            child = it.currentFrame()
            it += 1
            if not isinstance(child, QTextTable):
                continue
            for row in range(child.rows()):
                for col in range(child.columns()):
                    cell = child.cellAt(row, col)
                    if not _marked_bubble(cell.format()):
                        continue
                    start = cell.firstCursorPosition()
                    if start.position() < pos:
                        continue
                    end = cell.lastCursorPosition()
                    start.setPosition(end.position(), QTextCursor.MoveMode.KeepAnchor)
                    found.append(start.selectedText())
            walk(child)

    walk(panel.view.document().rootFrame())
    return found


def _install_qwait_for() -> None:
    """Bind Qt's predicate wait. PySide6 leaves the C++ template out.

    QTest.qWaitFor pumps events until the predicate is true or the timeout
    passes. A fixed qWait cannot see a paint the adaptive timer delayed.
    """
    from PySide6.QtCore import QElapsedTimer
    from PySide6.QtTest import QTest

    if hasattr(QTest, "qWaitFor"):
        return

    def qWaitFor(predicate, timeout: int = 5000) -> bool:
        clock = QElapsedTimer()
        clock.start()
        while not predicate():
            if clock.elapsed() >= timeout:
                return bool(predicate())
            QTest.qWait(10)
        return True

    QTest.qWaitFor = qWaitFor


def test_long_transcript_load_keeps_markdown_stable(qt_app) -> None:
    """L2 soak: History reload of a long mixed thread must not leave raw marks."""
    from arelis.ui.panels.chat import ChatPanel

    messages: list[dict[str, str]] = []
    for i in range(40):
        messages.append({"role": "user", "content": f"turn {i} ask about **item {i}**"})
        messages.append(
            {
                "role": "assistant",
                "content": (
                    f"## Answer {i}\n\n"
                    f"- point one for {i}\n"
                    f"- point two\n\n"
                    f"Use `code_{i}` and a fence:\n\n"
                    f"```python\nprint({i})\n```\n\n"
                    f"**Sources:**\n\n"
                    f"1. Example (https://example.com/{i})"
                ),
            }
        )
    panel = ChatPanel()
    panel.load_messages(messages)
    text = panel.view.toPlainText()
    assert text.count("you") >= 40
    assert text.count("arelis") >= 40
    assert "Answer 0" in text and "Answer 39" in text
    assert "print(39)" in text
    # Rendered: markdown markers should not litter the surface.
    assert "**Sources:**" not in text
    assert "```" not in text
    assert "## Answer" not in text
    html = panel.view.toHtml()
    assert "https://example.com/39" in html
    # Live stream + finish on top of a long loaded thread still paints cleanly.
    # The plate is the cell. It stays unborn until visible words arrive, and
    # those words are inside it. The caret is what shows during the wait.
    # Whitespace has no cell to wait for, so that paint runs now. Visible
    # words wait on the paint. A long transcript can stretch that timer
    # out to 2000 ms. The caret blinks every 530 ms, so it is held on
    # for that wait. Otherwise the glyph check can land in the off half.
    from PySide6.QtTest import QTest

    _install_qwait_for()

    panel.add_user("one more")
    panel.begin_assistant()
    qt_app.processEvents()
    assert "▍" in panel.view.toPlainText()
    assert _reply_cells(panel, panel._anchor) == []
    panel.append_delta("   ")
    panel._stream_paint.stop()
    panel._repaint_stream()
    assert _reply_cells(panel, panel._anchor) == []
    assert "▍" in panel.view.toPlainText()
    panel.append_delta("partial **bold**")
    panel.append_delta(" more")
    panel._caret_timer.stop()
    panel._caret_on = True
    QTest.qWaitFor(lambda: len(_reply_cells(panel, panel._anchor)) == 1, 3000)
    cells = _reply_cells(panel, panel._anchor)
    assert len(cells) == 1
    assert "partial" in cells[0] and "bold" in cells[0] and "more" in cells[0]
    assert "▍" in cells[0]
    panel.finish_assistant("final **bold** and `x`\n\n- ok")
    live = panel.view.toPlainText()
    assert "one more" in live
    assert "**bold**" not in live
    assert "final" in live and "bold" in live


def test_message_wash_is_one_translucent_coat(qt_app) -> None:
    """Bright stuff behind a message has to dim, without a solid black plate.

    A CSS background paints once per line. ``bgcolor`` is one rectangle and
    it drops alpha. The cell brush is a single coat that keeps its alpha.
    """
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPalette, QTextFormat, QTextTable
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from arelis.ui.panels.chat import (
        ChatPanel,
        _assistant_bubble_html,
        _user_bubble_html,
    )
    from arelis.ui.theme import color

    html = _assistant_bubble_html("line one\n\nline two")
    assert "<table" in html
    assert 'width="82%"' in html
    assert 'id="bubble"' in html
    assert "bgcolor=" not in html
    assert "background-color:" not in html
    user = _user_bubble_html("hey there")
    assert 'id="bubble"' in user
    assert "bgcolor=" not in user
    assert "background-color:" not in user

    host = QWidget()
    host.setFixedSize(640, 420)
    palette = host.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(255, 220, 40))
    host.setPalette(palette)
    host.setAutoFillBackground(True)
    layout = QVBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    panel = ChatPanel()
    panel.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    panel.view.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
    panel.view.viewport().setAutoFillBackground(False)
    panel.view.setStyleSheet(
        "QTextBrowser { background: transparent; border: none; color: #f8f1ea; }"
    )
    layout.addWidget(panel)
    host.show()
    panel.add_user("hey there")
    panel.finish_assistant(
        "this answer wraps across the wash so the coat can be read behind the words"
    )
    qt_app.processEvents()

    want = color("bubble_wash").getRgb()
    found = 0

    def walk(frame) -> None:
        nonlocal found
        it = frame.begin()
        while not it.atEnd():
            child = it.currentFrame()
            it += 1
            if not isinstance(child, QTextTable):
                continue
            for row in range(child.rows()):
                for col in range(child.columns()):
                    fmt = child.cellAt(row, col).format()
                    name = fmt.property(QTextFormat.Property.AnchorName)
                    if not name or "bubble" not in name:
                        continue
                    found += 1
                    assert fmt.background().color().getRgb() == want
                    assert want[3] < 255
            walk(child)

    walk(panel.view.document().rootFrame())
    assert found >= 2

    image = QImage(host.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(255, 220, 40))
    painter = QPainter(image)
    host.render(painter, QPoint(0, 0))
    painter.end()
    alpha = want[3] / 255
    yellow = (255, 220, 40)
    single = tuple(round(want[i] * alpha + yellow[i] * (1 - alpha)) for i in range(3))
    plate = single_n = 0
    width, height = image.width(), image.height()
    for y in range(0, height, 2):
        for x in range(0, width, 2):
            pixel = image.pixelColor(x, y)
            rgb = (pixel.red(), pixel.green(), pixel.blue())
            if max(abs(rgb[i] - want[i]) for i in range(3)) <= 8:
                plate += 1
            elif max(abs(rgb[i] - single[i]) for i in range(3)) <= 18:
                single_n += 1
    assert plate == 0
    assert single_n > 80
    assert panel.view.cursorWidth() == 0


# --------------------------------------------------------------------------
# Slash command output and the CLI confirm gate
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_asks_before_writing_on_a_terminal(monkeypatch) -> None:
    """The CLI used to auto-allow every write with only a printed notice."""
    from arelis.cli import CliPrinter

    printer = CliPrinter(EventBus(), interactive=True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert await printer._decide("write data/x.txt") == ("skip", False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert await printer._decide("write data/x.txt") == ("allow", False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "a")
    assert await printer._decide("write data/x.txt") == ("allow_turn", True)


