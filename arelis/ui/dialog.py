"""Frameless glass dialogs — the in-app answer to QMessageBox.

A native message box is a light grey Windows plate with a system font on it,
and over a black void it reads as a different program interrupting this one.
Everything here is the same glass the rest of the app is made of, so a question
looks like Arelis asking it.

`GlassDialog` is the plate: frameless, draggable by its heading, closed by
Escape. `confirm()` is the one-line question on top of it, and it is the only
confirm in the app — three near-identical copies of this were what the delete
prompts used to be.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from arelis.ui.glass import GlassFrame, advance_rim_pulse, seal_tool_window
from arelis.ui.icons import window_close_icon
from arelis.ui.theme import GLASS, METRICS

_HEADING = "GlassDialogHeading"


class GlassDialog(QDialog):
    """Frameless amber plate with a draggable heading and a close affordance.

    Subclasses fill `body`, a plain QVBoxLayout inside the glass. Buttons go in
    `footer`, which is right-aligned and already spaced.
    """

    def __init__(
        self,
        heading: str,
        *,
        parent: QWidget | None = None,
        width: int = 420,
        closable: bool = True,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("GlassDialog")
        self.setWindowTitle(heading)
        self.setModal(True)
        self.setMinimumWidth(width)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
            | Qt.WindowType.Window
        )
        seal_tool_window(self, round_corners=True)
        self._drag_origin: QPoint | None = None
        self._rim_pulse = QTimer(self)
        self._rim_pulse.setInterval(100)
        self._rim_pulse.timeout.connect(self._tick_rim_pulse)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.panel = GlassFrame(
            self,
            object_name="GlassDialogGlass",
            fill_alpha=int(GLASS.get("fill_settings", 255)),
            radius=float(GLASS["radius"]),
            pulse_rim=False,
            round_cutout=True,
        )
        outer.addWidget(self.panel)

        root = QVBoxLayout(self.panel)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        title = QLabel(heading)
        title.setObjectName(_HEADING)
        title.setCursor(Qt.CursorShape.OpenHandCursor)
        title.setToolTip("Drag to move")
        title.installEventFilter(self)
        head.addWidget(title, stretch=1)
        if closable:
            close_btn = QPushButton()
            close_btn.setObjectName("SettingsClose")
            close_btn.setIcon(window_close_icon(12))
            close_btn.setFixedSize(METRICS["chrome"], METRICS["chrome"])
            close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            close_btn.setToolTip("Close")
            # Escape already rejects; without this the button would also answer
            # Enter, which is the accept key everywhere else in the dialog.
            close_btn.setAutoDefault(False)
            close_btn.setDefault(False)
            close_btn.clicked.connect(self.reject)
            head.addWidget(close_btn)
        root.addLayout(head)

        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        root.addLayout(self.body, stretch=1)

        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(0, 0, 0, 0)
        self.footer.setSpacing(8)
        self.footer.addStretch(1)
        root.addLayout(self.footer)

    def add_text(self, text: str, *, role: str = "DialogBody") -> QLabel:
        label = QLabel(text)
        label.setObjectName(role)
        label.setWordWrap(True)
        self.body.addWidget(label)
        return label

    def add_button(
        self,
        text: str,
        *,
        primary: bool = False,
        destructive: bool = False,
        leading: bool = False,
    ) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("DialogPrimary" if primary else "DialogButton")
        if destructive:
            btn.setProperty("tone", "danger")
        btn.setMinimumHeight(METRICS["row"])
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Qt hands Enter to the first auto-default button it finds, which is
        # whichever was added first. Every caller here decides deliberately.
        btn.setAutoDefault(False)
        btn.setDefault(False)
        if leading:
            self.footer.insertWidget(0, btn)
        else:
            self.footer.addWidget(btn)
        return btn

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._rim_pulse.start()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._rim_pulse.stop()
        super().hideEvent(event)

    def _tick_rim_pulse(self) -> None:
        advance_rim_pulse(0.1)
        for frame in self.findChildren(GlassFrame):
            frame.update()

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        name = obj.objectName() if hasattr(obj, "objectName") else ""
        if name == _HEADING and isinstance(event, QMouseEvent):
            if (
                event.type() == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._drag_origin = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                return True
            if (
                event.type() == QEvent.Type.MouseMove
                and self._drag_origin is not None
                and bool(event.buttons() & Qt.MouseButton.LeftButton)
            ):
                self.move(event.globalPosition().toPoint() - self._drag_origin)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_origin = None
                return True
        return super().eventFilter(obj, event)


class ConfirmDialog(GlassDialog):
    """A question with two answers, one of which may destroy something.

    The cancel button holds focus even when it is not the accept action. A
    modal that lands with "Delete" under the cursor and under the Enter key is
    a data-loss bug wearing a dialog, and these are reached by a keyboard
    shortcut often enough that the first keypress after it opens is a coin flip.
    """

    def __init__(
        self,
        heading: str,
        message: str,
        *,
        parent: QWidget | None = None,
        detail: str = "",
        confirm_text: str = "Confirm",
        cancel_text: str = "Cancel",
        destructive: bool = False,
    ) -> None:
        super().__init__(heading, parent=parent, width=400)
        self.add_text(message)
        if detail:
            self.add_text(detail, role="DialogWarning" if destructive else "DialogNote")
        self.cancel_btn = self.add_button(cancel_text)
        self.confirm_btn = self.add_button(
            confirm_text, primary=not destructive, destructive=destructive
        )
        self.cancel_btn.clicked.connect(self.reject)
        self.confirm_btn.clicked.connect(self.accept)
        self.cancel_btn.setFocus()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        # Enter confirms wherever focus happens to be, because that is what the
        # key means in a two-answer dialog — but only Enter, never Space, which
        # would fire whichever button is focused and defeat the safe default.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept()
            return
        super().keyPressEvent(event)


def notice(
    parent: QWidget | None,
    heading: str,
    message: str,
    *,
    detail: str = "",
    warning: bool = False,
) -> None:
    """Tell the user something and wait for them to acknowledge it."""
    dialog = GlassDialog(heading, parent=parent, width=380)
    dialog.add_text(message, role="DialogWarning" if warning else "DialogBody")
    if detail:
        dialog.add_text(detail, role="DialogNote")
    ok = dialog.add_button("OK", primary=True)
    ok.clicked.connect(dialog.accept)
    ok.setFocus()
    dialog.exec()


def confirm(
    parent: QWidget | None,
    heading: str,
    message: str,
    *,
    detail: str = "",
    confirm_text: str = "Confirm",
    cancel_text: str = "Cancel",
    destructive: bool = False,
) -> bool:
    """Ask, block, and return whether the user said yes."""
    dialog = ConfirmDialog(
        heading,
        message,
        parent=parent,
        detail=detail,
        confirm_text=confirm_text,
        cancel_text=cancel_text,
        destructive=destructive,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted
