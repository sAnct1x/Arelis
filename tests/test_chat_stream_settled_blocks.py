"""A streaming reply rewrites only its unsettled tail, not every block on each token."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _first_block(panel):
    from PySide6.QtGui import QTextCursor

    cursor = QTextCursor(panel.view.document())
    cursor.movePosition(QTextCursor.MoveOperation.End)
    cursor.movePosition(QTextCursor.MoveOperation.PreviousBlock)
    return cursor.currentTable().cellAt(0, 0).firstCursorPosition().block()


def test_streaming_leaves_finished_paragraphs_alone(qt_app):
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.resize(380, 400)
    panel.show()
    panel.begin_assistant()
    panel.append_delta("## First\n\nThe opening paragraph is done.\n\nThe second one is")
    panel._flush_stream_paint()
    first = _first_block(panel)
    first.setUserState(7)  # a full rewrite of the bubble would drop this block
    for word in " still streaming in, word by word, as the model writes".split(" "):
        panel.append_delta(word + " ")
        panel._flush_stream_paint()
    assert _first_block(panel).userState() == 7
    assert "word by word" in panel.view.toPlainText()
    panel.finish_assistant()
    assert "The second one is still streaming in" in panel.view.toPlainText()
