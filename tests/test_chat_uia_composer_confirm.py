"""Composer and confirm buttons must be reachable from the Qt accessibility tree."""

from __future__ import annotations

from PySide6.QtGui import QAccessible, QAccessibleActionInterface
from PySide6.QtTest import QTest

from arelis.ui.panels.conversation import ConversationStage


def _walk(iface, acc=None):
    """Collect every named accessibility interface under iface, by name."""
    if acc is None:
        acc = {}
    if iface is None:
        return acc
    name = iface.text(QAccessible.Text.Name)
    if name:
        acc.setdefault(name, []).append(iface)
    for i in range(iface.childCount()):
        _walk(iface.child(i), acc)
    return acc


def _press(iface) -> None:
    act = iface.actionInterface()
    assert act is not None
    press = QAccessibleActionInterface.pressAction()
    assert press in act.actionNames()
    act.doAction(press)
    # QAccessibleWidget.Press uses animateClick, which fires after a short timer.
    QTest.qWait(200)


def test_composer_and_confirm_buttons_are_reachable_by_ui_automation(qt_app) -> None:
    """A UIA client can find Message, Allow, and Deny by name and press the buttons."""
    stage = ConversationStage(default_role="fast")
    decided: list[tuple[str, str, bool]] = []
    try:
        stage.resize(800, 600)
        stage.show()
        # A confirm card appears mid-turn, after a message has left idle.
        stage.chat.add_user("please read notes.txt")
        stage._place_composer(False)
        stage.confirm.decided.connect(
            lambda confirm_id, decision, batch: decided.append(
                (confirm_id, decision, batch)
            )
        )
        stage.confirm.ask(
            "c1",
            "read_file",
            "read_file(path=notes.txt)",
            headline="read notes.txt",
            batch_ok=False,
            persist_ok=False,
        )
        qt_app.processEvents()

        root = QAccessible.queryAccessibleInterface(stage)
        assert root is not None
        found = _walk(root)

        message = found.get("Message") or []
        assert len(message) == 1
        assert message[0].role() == QAccessible.Role.EditableText
        assert message[0].object() is stage.input

        allow = found.get("Allow") or []
        deny = found.get("Deny") or []
        assert len(allow) == 1
        assert len(deny) == 1
        assert allow[0].role() == QAccessible.Role.Button
        assert deny[0].role() == QAccessible.Role.Button
        assert allow[0].object() is stage.confirm.allow_btn
        assert deny[0].object() is stage.confirm.skip_btn

        _press(allow[0])
        qt_app.processEvents()
        assert decided == [("c1", "allow", False)]

        decided.clear()
        stage.confirm.ask(
            "c2",
            "read_file",
            "read_file(path=notes.txt)",
            headline="read notes.txt",
            batch_ok=False,
            persist_ok=False,
        )
        qt_app.processEvents()
        found = _walk(QAccessible.queryAccessibleInterface(stage))
        deny = found.get("Deny") or []
        assert len(deny) == 1
        _press(deny[0])
        qt_app.processEvents()
        assert decided == [("c2", "skip", False)]
    finally:
        stage.deleteLater()
        qt_app.processEvents()
