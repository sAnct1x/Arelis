"""Settings > Memory is reachable and usable without a mouse, from the Filament chat."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAccessible, QAccessibleActionInterface
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from arelis.memory.store import MemoryStore


def _named(iface, name: str, acc=None) -> list:
    """Every accessibility interface under iface whose Name is name."""
    if acc is None:
        acc = []
    if iface is None:
        return acc
    if iface.text(QAccessible.Text.Name) == name:
        acc.append(iface)
    for i in range(iface.childCount()):
        _named(iface.child(i), name, acc)
    return acc


def _one(root, name: str, role=None):
    found = _named(QAccessible.queryAccessibleInterface(root), name)
    if role is not None:
        found = [f for f in found if f.role() == role]
    assert len(found) == 1, f"{name!r}: {len(found)} matches"
    return found[0]


def _press(iface) -> None:
    act = iface.actionInterface()
    assert act is not None
    press = QAccessibleActionInterface.pressAction()
    assert press in act.actionNames()
    act.doAction(press)
    QTest.qWait(200)  # Press is an animateClick.


def _select(row) -> None:
    """UIA SelectionItem.Select: the list's selection interface picks the row."""
    table = row.parent()
    table.selectionInterface().clear()
    assert table.selectionInterface().select(row)
    QTest.qWait(50)


def test_settings_memory_is_reachable_and_operable_by_keyboard_and_ui_automation(
    arelis_window, qt_app, tmp_path
) -> None:
    """Ctrl+, from the Filament chat opens Settings; edit and forget work without a mouse.

    Filament hides the Settings button, so QA drives Settings > Memory with Ctrl+,
    and UI Automation. Rows were named with their dates line, the edit box had
    no name and kept Tab, and the list ignored Enter and Delete.
    """
    # A UIA client is attached, so Qt sends the list-reset events that drop stale rows.
    was_active = QAccessible.isActive()
    QAccessible.setActive(True)
    try:
        _drive(arelis_window, qt_app, tmp_path)
    finally:
        QAccessible.setActive(was_active)


def _drive(arelis_window, qt_app, tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    keep = store.add_fact("My finder scope is a 9x50 finder", source="explicit", status="active")
    drop = store.add_fact("My mount is an EQ5", source="explicit", status="active")
    w = arelis_window(
        {
            "ui": {
                "default_width": 900,
                "default_height": 650,
                "theme": "night",
                "filament_ack": True,
            }
        }
    )
    w.store = store
    w.show()
    qt_app.processEvents()
    w._choose_theme("filament", True)
    w.filament._filament_set_chat_open(True)
    QTest.qWait(300)
    tile = w._filament_chat_tile
    tile.activateWindow()
    message = _one(tile, "Message").object()
    message.setFocus()
    QTest.qWait(100)

    seen: list[str] = []

    def fill_edit() -> None:
        try:
            box = QApplication.activeModalWidget()
            field = _one(box, "Fact text").object()
            field.selectAll()
            QTest.keyClicks(field, "My finder scope is a 9x50 right angle finder")
            QTest.keyClick(field, Qt.Key.Key_Tab)
            assert QApplication.focusWidget() is not field
            _press(_one(box, "Save"))
            seen.append("edited")
        except Exception as exc:  # a slot cannot raise into the test
            seen.append(f"edit failed: {exc!r}")
            box = QApplication.activeModalWidget()
            if box is not None:
                box.reject()

    def drive_settings() -> None:
        dlg = QApplication.activeModalWidget()
        try:
            assert dlg is not None and dlg.windowTitle() == "Settings"
            seen.append("settings")
            _press(_one(dlg, "memory", QAccessible.Role.PageTab))
            facts = _one(dlg, "Active facts").object()
            assert facts.isVisible()
            _select(_one(dlg, "My finder scope is a 9x50 finder"))
            facts.setFocus()
            QTimer.singleShot(300, fill_edit)
            QTest.keyClick(facts, Qt.Key.Key_Return)
            _select(_one(dlg, "My mount is an EQ5"))
            QTest.keyClick(facts, Qt.Key.Key_Delete)
            assert _named(QAccessible.queryAccessibleInterface(dlg), "My mount is an EQ5") == []
            _press(_one(dlg, "Close"))
        except Exception as exc:
            seen.append(f"settings failed: {exc!r}")
            if dlg is not None:
                dlg.reject()

    QTimer.singleShot(400, drive_settings)
    QTest.keyClick(message, Qt.Key.Key_Comma, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(1500)  # the timer runs even when Ctrl+, opened nothing

    assert seen == ["settings", "edited"]
    texts = {f["id"]: f["text"] for f in store.list_facts(status="active")}
    assert texts == {keep: "My finder scope is a 9x50 right angle finder"}
    assert drop not in texts
    store.close()
