"""Pinned chats stay at the top, and Ctrl+Shift+F lands in search.

On main the list kept input order, so the newer unpinned chat stayed first.
The search focus helper did not exist yet.
"""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog

from arelis.ui.panels.history import PIN_MARK, HistoryPanel
from arelis.ui.quick_switch import QuickSwitch


def test_history_panel_puts_pinned_first(qt_app) -> None:
    panel = HistoryPanel()
    panel.set_sessions(
        [
            {"id": "a", "title": "new one", "started_at": "2026-10-10T10:00:00"},
            {
                "id": "b",
                "title": "kept",
                "started_at": "2026-10-01T10:00:00",
                "pinned": True,
            },
        ]
    )
    assert panel.list.item(0).data(Qt.ItemDataRole.UserRole) == "b"
    assert panel.list.item(1).data(Qt.ItemDataRole.UserRole) == "a"
    assert "pinned" in panel.list.item(0).toolTip()
    assert PIN_MARK in panel.list.item(0).text()
    assert "pinned" not in panel.list.item(1).toolTip()
    assert panel.recent_sessions(3)[0] == ("b", "kept")
    assert panel.new_btn.toolTip() == "Start a fresh conversation (Ctrl+N)"
    assert panel.search.toolTip() == "search titles and messages (Ctrl+Shift+F)"
    del qt_app


def test_ctrl_shift_f_and_ctrl_f_focus_their_own_fields(qt_app, arelis_window) -> None:
    """Each chord lands in its own field, and launch focus does not steal it."""
    from arelis.ui.chat_find import ChatFindBar

    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window.conversation.input.setFocus()
    qt_app.processEvents()

    QTest.keyClick(
        window.conversation.input,
        Qt.Key.Key_F,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
    )
    qt_app.processEvents()
    assert window.history_dock.isVisible()
    assert window.history.search.hasFocus()
    window.conversation.focus_input()
    assert window.history.search.hasFocus()

    QTest.keyClick(
        window.history.search,
        Qt.Key.Key_F,
        Qt.KeyboardModifier.ControlModifier,
    )
    qt_app.processEvents()
    bar = window.chat.findChild(ChatFindBar)
    assert bar is not None and bar.isVisible()
    assert bar.edit.hasFocus()
    assert not window.history.search.hasFocus()
    window.conversation.focus_input()
    assert bar.edit.hasFocus()


def test_quick_switch_opens_the_pinned_match(qt_app) -> None:
    panel = HistoryPanel()
    panel.set_sessions(
        [
            {"id": "a", "title": "new one", "started_at": "2026-10-10T10:00:00"},
            {
                "id": "b",
                "title": "kept",
                "started_at": "2026-10-01T10:00:00",
                "pinned": True,
            },
        ]
    )
    dialog = QuickSwitch(SimpleNamespace(history=panel))
    dialog.show()
    qt_app.processEvents()
    assert dialog.list.item(0).data(Qt.ItemDataRole.UserRole) == "b"
    dialog.search.setText("new")
    qt_app.processEvents()
    assert dialog.list.count() == 1
    assert dialog.list.item(0).data(Qt.ItemDataRole.UserRole) == "a"
    dialog.search.returnPressed.emit()
    assert dialog.chosen_id == "a"
    assert dialog.result() == QDialog.DialogCode.Accepted
    dialog.close()
