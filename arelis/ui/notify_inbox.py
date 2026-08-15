"""Floating glass inbox — View → notifications. Not a dock."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arelis.ui.glass import GlassFrame, advance_rim_pulse
from arelis.ui.icons import window_close_icon
from arelis.ui.panels.notifications import NotificationsPanel
from arelis.ui.theme import GLASS


class NotificationsInboxWindow(QWidget):
    """Frameless smoked plate. Appears, then goes away."""

    closed = Signal()

    def __init__(self, panel: NotificationsPanel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NotificationsInbox")
        self.setWindowTitle("Notifications")
        self.resize(360, 480)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self._drag_origin: QPoint | None = None
        self._rim_pulse = QTimer(self)
        self._rim_pulse.setInterval(100)
        self._rim_pulse.timeout.connect(self._tick_rim_pulse)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        plate = GlassFrame(
            self,
            object_name="NotifyInboxGlass",
            fill_alpha=int(GLASS.get("fill_float", 255)),
            radius=float(GLASS.get("radius", 16.0)),
            pulse_rim=False,
        )
        outer.addWidget(plate)

        root = QVBoxLayout(plate)
        root.setContentsMargins(16, 12, 16, 14)
        root.setSpacing(10)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("notifications")
        heading.setObjectName("SettingsHeading")
        heading.setCursor(Qt.CursorShape.OpenHandCursor)
        heading.setToolTip("Drag to move")
        heading.installEventFilter(self)
        head.addWidget(heading, stretch=1)
        close_btn = QToolButton()
        close_btn.setObjectName("SettingsClose")
        close_btn.setIcon(window_close_icon(12))
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setToolTip("Close")
        close_btn.clicked.connect(self.close)
        head.addWidget(close_btn)
        root.addLayout(head)

        self.panel = panel
        panel.setParent(plate)
        root.addWidget(panel, stretch=1)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        self._rim_pulse.start()

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._rim_pulse.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closed.emit()
        super().closeEvent(event)

    def _tick_rim_pulse(self) -> None:
        advance_rim_pulse(0.1)
        for frame in self.findChildren(GlassFrame):
            frame.update()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
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
