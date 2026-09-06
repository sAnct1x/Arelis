"""One-message mail tile — open a notice, read the body, send a reply."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arelis.ui.glass import GlassFrame, seal_tool_window
from arelis.ui.icons import window_close_icon
from arelis.ui.theme import GLASS, METRICS, SPACE, space_box
from arelis.ui.window_resize import enable_win32_resize_frame, handle_native_resize


class MailPeekWindow(QWidget):
    """Frameless reader for one inbound email."""

    reply_requested = Signal(str, str, str)  # to, subject, body
    closed = Signal()

    def __init__(
        self,
        *,
        sender: str,
        subject: str,
        body: str,
        reply_to: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.reply_to = reply_to
        self.subject = subject
        self.setObjectName("MailPeek")
        self.setWindowTitle(subject or sender or "mail")
        self.resize(420, 520)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        seal_tool_window(self, round_corners=True)
        self._drag_origin: QPoint | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        plate = GlassFrame(
            self,
            object_name="NotifyInboxGlass",
            fill_alpha=int(GLASS.get("fill_float", 255)),
            radius=float(GLASS["radius"]),
            pulse_rim=False,
            round_cutout=True,
        )
        outer.addWidget(plate)
        root = QVBoxLayout(plate)
        root.setContentsMargins(*space_box("plate", "inset"))
        root.setSpacing(SPACE["gap"])

        head = QHBoxLayout()
        self.heading = QLabel(subject or "(no subject)")
        self.heading.setObjectName("SettingsHeading")
        self.heading.setWordWrap(True)
        self.heading.setCursor(Qt.CursorShape.OpenHandCursor)
        self.heading.installEventFilter(self)
        head.addWidget(self.heading, stretch=1)
        close_btn = QToolButton()
        close_btn.setObjectName("SettingsClose")
        close_btn.setIcon(window_close_icon(12))
        close_btn.setFixedSize(METRICS["chrome"], METRICS["chrome"])
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.close)
        head.addWidget(close_btn)
        root.addLayout(head)

        self.from_label = QLabel(sender)
        self.from_label.setObjectName("InstrumentHint")
        self.from_label.setWordWrap(True)
        self.from_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self.from_label)

        self.body = QPlainTextEdit()
        self.body.setObjectName("MailPeekBody")
        self.body.setReadOnly(True)
        self.body.setPlainText(body)
        root.addWidget(self.body, stretch=1)

        self.reply_edit = QLineEdit()
        self.reply_edit.setObjectName("InstrumentSearch")
        self.reply_edit.setPlaceholderText("reply…")
        self.reply_edit.setFixedHeight(28)
        self.reply_edit.returnPressed.connect(self._reply)
        send = QPushButton("send")
        send.setObjectName("InstrumentAction")
        send.setFixedHeight(28)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.clicked.connect(self._reply)
        row = QHBoxLayout()
        row.addWidget(self.reply_edit, stretch=1)
        row.addWidget(send)
        root.addLayout(row)

        self.status = QLabel("")
        self.status.setObjectName("InstrumentHint")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        enable_win32_resize_frame(self)

    def nativeEvent(self, eventType, message):  # type: ignore[override]
        handled = handle_native_resize(self, eventType, message)
        if handled is not None:
            return handled
        return super().nativeEvent(eventType, message)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closed.emit()
        super().closeEvent(event)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def _reply(self) -> None:
        text = self.reply_edit.text().strip()
        if not text or not self.reply_to:
            return
        subject = self.subject or ""
        if subject and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        self.reply_edit.clear()
        self.status.setText("sending…")
        self.reply_requested.emit(self.reply_to, subject, text)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if watched is self.heading:
            if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
                if event.button() == Qt.MouseButton.LeftButton:
                    self._drag_origin = (
                        event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    )
                    return True
            if event.type() == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
                    self.move(event.globalPosition().toPoint() - self._drag_origin)
                    return True
            if event.type() == QEvent.Type.MouseButtonRelease:
                self._drag_origin = None
        return super().eventFilter(watched, event)
