"""In-app dialogs: frameless, themed, and safe under the keyboard."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QDialog

from arelis.ui.dialog import ConfirmDialog, GlassDialog
from arelis.ui.first_run import FirstRunDialog
from arelis.ui.glass import GlassFrame


def _press(widget, key: Qt.Key) -> None:
    widget.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


def test_glass_dialog_is_frameless_and_on_glass(qt_app) -> None:
    dialog = GlassDialog("Question")
    try:
        flags = dialog.windowFlags()
        assert flags & Qt.WindowType.FramelessWindowHint
        assert dialog.findChildren(GlassFrame)
    finally:
        dialog.deleteLater()


def test_confirm_never_lands_on_the_destroying_answer(qt_app) -> None:
    dialog = ConfirmDialog(
        "Delete conversation",
        "Delete “fringe run 3”?",
        detail="This cannot be undone.",
        confirm_text="Delete",
        destructive=True,
    )
    try:
        dialog.show()
        qt_app.processEvents()
        assert dialog.focusWidget() is dialog.cancel_btn
        assert not dialog.confirm_btn.isDefault()
        assert dialog.confirm_btn.property("tone") == "danger"
    finally:
        dialog.deleteLater()


def test_confirm_answers_enter_and_escape(qt_app) -> None:
    yes = ConfirmDialog("Q", "Go ahead?")
    try:
        _press(yes, Qt.Key.Key_Return)
        assert yes.result() == QDialog.DialogCode.Accepted
    finally:
        yes.deleteLater()

    no = ConfirmDialog("Q", "Go ahead?")
    try:
        _press(no, Qt.Key.Key_Escape)
        assert no.result() == QDialog.DialogCode.Rejected
    finally:
        no.deleteLater()


def test_first_run_is_the_same_glass_as_everything_else(qt_app, tmp_path: Path) -> None:
    dialog = FirstRunDialog(tmp_path / "Arelis")
    try:
        assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert dialog.findChildren(GlassFrame)
        # The chosen path is the one thing a user has to be able to read.
        assert str(tmp_path / "Arelis") in dialog._path_label.text()
        assert dialog._path_label.objectName() == "DialogPath"
        assert dialog.root == tmp_path / "Arelis"
    finally:
        dialog.deleteLater()
