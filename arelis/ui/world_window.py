"""Floating world plate — physics room only. Calendar-class chrome."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QMouseEvent, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from arelis.spatial.scene import WorldScene
from arelis.ui.glass import GlassFrame, advance_rim_pulse, seal_tool_window
from arelis.ui.icons import (
    window_close_icon,
    window_maximize_icon,
    window_minimize_icon,
)
from arelis.ui.panels.world import WorldPanel
from arelis.ui.theme import GLASS, METRICS
from arelis.ui.window_resize import (
    cursor_for_hit,
    enable_win32_resize_frame,
    handle_native_resize,
    hit_test_resize,
    try_system_resize,
)


def _chrome_btn(obj: str, icon, slot, *, tooltip: str = "") -> QPushButton:
    btn = QPushButton()
    btn.setObjectName(obj)
    btn.setIcon(icon)
    btn.setFixedSize(METRICS["chrome"] + 4, METRICS["chrome"] - 2)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFlat(True)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.clicked.connect(slot)
    return btn


class WorldWindow(QWidget):
    """Frameless plate. Hide, do not destroy. Leave Physics must hide it."""

    closed = Signal()

    def __init__(self, scene: WorldScene, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorldWindow")
        self.setWindowTitle("world")
        self.resize(960, 640)
        self.setMinimumSize(480, 360)
        self.setWindowFlags(
            Qt.WindowType.Tool
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

        plate = GlassFrame(
            self,
            object_name="WorldWindowGlass",
            fill_alpha=int(GLASS.get("fill_float", 255)),
            radius=float(GLASS["radius"]),
            pulse_rim=False,
            round_cutout=True,
        )
        outer.addWidget(plate)

        root = QVBoxLayout(plate)
        root.setContentsMargins(16, 8, 10, 14)
        root.setSpacing(8)

        head = QHBoxLayout()
        heading = QLabel("world")
        heading.setObjectName("SettingsHeading")
        heading.setCursor(Qt.CursorShape.OpenHandCursor)
        heading.setToolTip("Physics room · drag to move")
        heading.installEventFilter(self)
        head.addWidget(heading, stretch=1)
        self.min_btn = _chrome_btn("ChromeMin", window_minimize_icon(14), self._minimize)
        self.max_btn = _chrome_btn("ChromeMax", window_maximize_icon(14), self._maximize)
        close_btn = QToolButton()
        close_btn.setObjectName("SettingsClose")
        close_btn.setIcon(window_close_icon(12))
        close_btn.setFixedSize(METRICS["row"], METRICS["row"])
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setToolTip("Hide world (strip or Ctrl+8)")
        close_btn.clicked.connect(self.close)
        head.addWidget(self.min_btn)
        head.addWidget(self.max_btn)
        head.addWidget(close_btn)
        root.addLayout(head)

        self.panel = WorldPanel(scene, plate)
        root.addWidget(self.panel, stretch=1)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.close)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        enable_win32_resize_frame(self)
        self.setMouseTracking(True)
        self._sync_max_icon()
        self._rim_pulse.start()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_max_icon()
            if not (self.isMaximized() or self.isFullScreen()):
                enable_win32_resize_frame(self)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        self._rim_pulse.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self.closed.emit()
        super().closeEvent(event)

    def nativeEvent(self, eventType, message):
        handled = handle_native_resize(self, eventType, message)
        if handled is not None:
            return handled
        return super().nativeEvent(eventType, message)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if try_system_resize(self, event.globalPosition().toPoint()):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        shape = cursor_for_hit(hit_test_resize(self))
        if shape is not None:
            self.setCursor(shape)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def _minimize(self) -> None:
        self.showMinimized()

    def _maximize(self) -> None:
        if self.isMaximized() or self.isFullScreen():
            self.showNormal()
        else:
            self.showMaximized()
        self._sync_max_icon()

    def _sync_max_icon(self) -> None:
        restore = self.isMaximized() or self.isFullScreen()
        self.max_btn.setIcon(window_maximize_icon(14, restore=restore))

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
                if not self.isMaximized() and not self.isFullScreen():
                    self.move(event.globalPosition().toPoint() - self._drag_origin)
                return True
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._drag_origin = None
        return super().eventFilter(watched, event)
