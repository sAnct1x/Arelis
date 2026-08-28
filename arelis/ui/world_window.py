"""Floating world plate — physics room only. Calendar-class chrome."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from arelis.spatial.scene import WorldScene
from arelis.ui.glass import GlassFrame, advance_rim_pulse, seal_tool_window
from arelis.ui.icons import (
    window_close_icon,
    window_maximize_icon,
    window_minimize_icon,
)
from arelis.ui.panels.solar import SolarPanel
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


class WorldPause(QWidget):
    """Esc overlay. Settings is a stub. Exit returns to the chooser."""

    resume_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorldPause")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(12)
        layout.addStretch(1)
        title = QLabel("paused")
        title.setObjectName("SettingsHeading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel("Esc resumes. Exit leaves the plate.")
        hint.setObjectName("InstrumentHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        resume = QPushButton("resume")
        resume.setObjectName("WorldPauseResume")
        resume.setCursor(Qt.CursorShape.PointingHandCursor)
        resume.setFixedWidth(240)
        resume.clicked.connect(self.resume_requested.emit)
        layout.addWidget(resume, alignment=Qt.AlignmentFlag.AlignHCenter)
        settings = QPushButton("Settings")
        settings.setObjectName("WorldPauseSettings")
        settings.setEnabled(False)
        settings.setToolTip("Later.")
        settings.setFixedWidth(240)
        layout.addWidget(settings, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.exit_btn = QPushButton("Exit")
        self.exit_btn.setObjectName("WorldPauseExit")
        self.exit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.exit_btn.setToolTip("Back to hands or solar system")
        self.exit_btn.setFixedWidth(240)
        self.exit_btn.clicked.connect(self.exit_requested.emit)
        layout.addWidget(self.exit_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        from PySide6.QtGui import QColor, QPainter

        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(6, 8, 12, 200))
        super().paintEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            win = self.window()
            escape = getattr(win, "_escape", None)
            if callable(escape):
                escape()
            event.accept()
            return
        super().keyPressEvent(event)


class WorldChooser(QWidget):
    """First page behind World: hands sandbox or the solar lab."""

    hands_requested = Signal()
    solar_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorldChooser")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(12)
        layout.addStretch(1)
        title = QLabel("Where to?")
        title.setObjectName("SettingsHeading")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel(
            "Hands is the tracking sandbox — polygons, g = 2.4, not metres.\n"
            "Solar system is the lab. The plate fills now; one Horizons fetch "
            "replaces the catalog if JPL answers."
        )
        hint.setObjectName("InstrumentHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        hands = QPushButton("hands")
        hands.setObjectName("WorldChooserHands")
        hands.setCursor(Qt.CursorShape.PointingHandCursor)
        hands.setToolTip("Palm tracking tutorial. Not the solar system.")
        hands.setFixedWidth(240)
        hands.clicked.connect(self.hands_requested.emit)
        layout.addWidget(hands, alignment=Qt.AlignmentFlag.AlignHCenter)
        solar = QPushButton("solar system")
        solar.setObjectName("WorldChooserSolar")
        solar.setCursor(Qt.CursorShape.PointingHandCursor)
        solar.setToolTip("True-scale N-body. Catalog first, then one Horizons fetch.")
        solar.setFixedWidth(240)
        solar.clicked.connect(self.solar_requested.emit)
        layout.addWidget(solar, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)


class WorldWindow(QWidget):
    """Frameless plate. Hide, do not destroy. Leave Physics must hide it."""

    closed = Signal()

    def __init__(self, scene: WorldScene, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("WorldWindow")
        self.setWindowTitle("world")
        self.resize(1280, 800)
        self.setMinimumSize(720, 480)
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
        self.heading = QLabel("world")
        self.heading.setObjectName("SettingsHeading")
        self.heading.setCursor(Qt.CursorShape.OpenHandCursor)
        self.heading.setToolTip("Physics room · drag to move")
        self.heading.installEventFilter(self)
        head.addWidget(self.heading, stretch=1)
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

        self.stack = QStackedWidget(plate)
        self.chooser = WorldChooser(plate)
        self.panel = WorldPanel(scene, plate)
        self.solar = SolarPanel(plate)
        self.stack.addWidget(self.chooser)
        self.stack.addWidget(self.panel)
        self.stack.addWidget(self.solar)
        self.chooser.hands_requested.connect(self.enter_hands)
        self.chooser.solar_requested.connect(self.enter_solar)
        self.solar.toy_requested.connect(self.enter_hands)
        self.stack.setCurrentWidget(self.chooser)
        root.addWidget(self.stack, stretch=1)
        self.pause = WorldPause(plate)
        self.pause.hide()
        self.pause.resume_requested.connect(self._resume_lab)
        self.pause.exit_requested.connect(self._exit_lab)
        self._pause_was = True
        self.stack.installEventFilter(self)
        self._sync = QTimer(self)
        self._sync.setInterval(250)
        self._sync.timeout.connect(self._sync_heading)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self._escape()
            event.accept()
            return
        super().keyPressEvent(event)

    def solar_active(self) -> bool:
        return self.stack.currentWidget() is self.solar

    def hands_active(self) -> bool:
        return self.stack.currentWidget() is self.panel

    def _end_solar_visit(self) -> None:
        """Write the IAS15 receipt on the way out. No-op if we were not in the lab."""
        if not self.solar_active():
            return
        from arelis.physics.export import dump_on_leave

        dump_on_leave(camera=self.solar.camera_state())

    def show_chooser(self) -> None:
        self._end_solar_visit()
        self.pause.hide()
        self.solar.menu_up = False
        self.panel.menu_up = False
        self.stack.setCurrentWidget(self.chooser)
        self._sync_heading()

    def enter_hands(self) -> None:
        self._end_solar_visit()
        self.stack.setCurrentWidget(self.panel)
        self.panel.refresh()
        self._sync_heading()

    def enter_solar(self) -> None:
        from arelis.ui.solar_gl import gl_wanted, trace

        trace(f"enter_solar gl_wanted={gl_wanted()}")
        self.solar._ensure_ic()
        self.stack.setCurrentWidget(self.solar)
        self.solar.setFocus(Qt.FocusReason.OtherFocusReason)
        self._sync_heading()

    def _sync_heading(self) -> None:
        page = self.stack.currentWidget()
        if page is self.solar:
            self.heading.setText("solar system")
        elif page is self.panel:
            self.heading.setText("hands")
        else:
            self.heading.setText("world")

    def _escape(self) -> None:
        if self.pause.isVisible():
            self._resume_lab()
            return
        if self.stack.currentWidget() is self.chooser:
            self.close()
            return
        self._show_pause()

    def _show_pause(self) -> None:
        from arelis.physics.runtime import get_system

        self.pause.setGeometry(self.stack.geometry())
        self.pause.raise_()
        self.pause.show()
        self.pause.setFocus(Qt.FocusReason.OtherFocusReason)
        self.solar.menu_up = True
        self.panel.menu_up = True
        system = get_system()
        if system is not None:
            self._pause_was = system.paused
            system.paused = True

    def _resume_lab(self) -> None:
        from arelis.physics.runtime import get_system

        self.pause.hide()
        self.solar.menu_up = False
        self.panel.menu_up = False
        system = get_system()
        if system is not None:
            system.paused = self._pause_was

    def _exit_lab(self) -> None:
        self._resume_lab()
        self.show_chooser()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        enable_win32_resize_frame(self)
        self.setMouseTracking(True)
        self._sync_max_icon()
        self._rim_pulse.start()
        self._sync.start()
        self._sync_heading()

    def changeEvent(self, event) -> None:  # type: ignore[override]
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_max_icon()
            if not (self.isMaximized() or self.isFullScreen()):
                enable_win32_resize_frame(self)

    def hideEvent(self, event) -> None:  # type: ignore[override]
        if self.solar_active():
            self.show_chooser()
        self._rim_pulse.stop()
        self._sync.stop()
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
        stack = getattr(self, "stack", None)
        pause = getattr(self, "pause", None)
        if (
            stack is not None
            and pause is not None
            and watched is stack
            and event.type() == QEvent.Type.Resize
        ):
            pause.setGeometry(stack.geometry())
        if watched is not self.heading:
            return super().eventFilter(watched, event)
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
