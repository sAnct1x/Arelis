"""Find in this chat.

The first test is the comfort-pack fail-first check: select a word, then wrap.
The others cover typing, a formula drawn as an image, and Esc.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextFormat
from PySide6.QtTest import QTest

from arelis.ui.chat_find import ChatFindBar

FRAC = r"\frac{a}{b}"


def _panel():
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.resize(640, 480)
    return panel


def _bar(panel) -> ChatFindBar:
    bar = panel.findChild(ChatFindBar)
    assert bar is not None
    return bar


def test_chat_find_selects_match(qt_app) -> None:
    """FAILFIRST. Main has no find bar, so the import and the selection both fail."""
    chat = _panel()
    chat.add_user("where is the telescope")
    bar = ChatFindBar(chat.view, chat)
    assert bar.find("telescope") is True
    assert chat.view.textCursor().selectedText() == "telescope"
    start = chat.view.textCursor().selectionStart()
    assert bar.find("telescope") is True
    assert chat.view.textCursor().selectedText() == "telescope"
    assert chat.view.textCursor().selectionStart() == start
    del qt_app


def test_typing_highlights_plain_text(qt_app) -> None:
    panel = _panel()
    panel.add_user("alpha telescope beta telescope")
    bar = _bar(panel)
    assert bar.edit.toolTip() == "find in this chat (Ctrl+F)"
    bar.show_find()
    bar.edit.setText("telescope")
    extras = panel.view.extraSelections()
    assert len(extras) == 2
    assert all(extra.cursor.selectedText() == "telescope" for extra in extras)
    assert panel.view.textCursor().selectedText() == "telescope"
    first = panel.view.textCursor().selectionStart()
    assert bar.count.text() == "1 of 2"
    QTest.keyClick(bar.edit, Qt.Key.Key_Return)
    assert panel.view.textCursor().selectedText() == "telescope"
    assert panel.view.textCursor().selectionStart() != first
    assert bar.count.text() == "2 of 2"
    QTest.keyClick(bar.edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert panel.view.textCursor().selectionStart() == first
    assert bar.count.text() == "1 of 2"
    del qt_app


def test_find_formula_image_by_latex(qt_app) -> None:
    panel = _panel()
    panel.begin_assistant()
    panel.finish_assistant(f"See ${FRAC}$ now.")
    assert "\\frac" not in panel.view.toPlainText()
    bar = _bar(panel)
    assert bar.find(FRAC) is True
    cursor = panel.view.textCursor()
    assert cursor.selectedText() == "\ufffc"
    fmt = cursor.charFormat()
    alt = fmt.stringProperty(QTextFormat.Property.ImageAltText)
    assert alt == FRAC
    assert fmt.toolTip() == FRAC
    assert bar.find(r"a}{b}") is True
    assert panel.view.textCursor().selectedText() == "\ufffc"
    assert panel.view.extraSelections()
    del qt_app


def test_escape_clears_find_highlights(qt_app, arelis_window) -> None:
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window.chat.add_user("where is the telescope")
    window.conversation.input.setText("leave this")
    window.act_find.trigger()
    qt_app.processEvents()
    bar = _bar(window.chat)
    assert bar.isVisible()
    assert bar.edit.toolTip() == "find in this chat (Ctrl+F)"
    bar.edit.setText("telescope")
    qt_app.processEvents()
    assert window.chat.view.extraSelections()
    assert window.chat.view.textCursor().selectedText() == "telescope"
    bar.edit.setFocus()
    qt_app.processEvents()
    QTest.keyClick(bar.edit, Qt.Key.Key_Escape)
    qt_app.processEvents()
    assert not bar.isVisible()
    assert window.chat.view.extraSelections() == []
    assert not window.chat.view.textCursor().hasSelection()
    assert window.conversation.input.text() == "leave this"
