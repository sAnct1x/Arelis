from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QDockWidget, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from arelis.ui.chrome import FloatingDockTitleBar
from arelis.ui.glass import GlassFrame
from arelis.ui.theme import COLORS, GLASS

# How far the pointer must travel on the header before a docked panel pops out.
_UNDOCK_DRAG_PX = 24
_DOCKED_FILL_ALPHA = int(GLASS.get("fill_docked", 62))
# Floating: opaque void plate — no compositing the chat HWND through the float.
_FLOATING_FILL_ALPHA = int(GLASS.get("fill_float", 255))


class InstrumentPanel(GlassFrame):
    """Glass dock body: docked drag header, floating continuous-plate chrome.

    The parent QDockWidget keeps a zero-height title bar always. Undocked window
    chrome (min/max/close) lives in-panel so the tile is one void slab.
    """

    def __init__(self, title: str, body: QWidget, parent=None) -> None:
        super().__init__(
            parent,
            object_name="GlassDockContent",
            fill_alpha=_DOCKED_FILL_ALPHA,
            radius=float(GLASS["radius"]),
            pulse_rim=False,
        )
        self._title = title
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 8, 10, 10)
        self._layout.setSpacing(8)

        self._float_chrome = FloatingDockTitleBar(title, self)
        self._float_chrome.hide()
        self._layout.addWidget(self._float_chrome)

        self._docked_head = QWidget()
        self._docked_head.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        head = QHBoxLayout(self._docked_head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("InstrumentTitle")
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self.title_label.setCursor(Qt.CursorShape.OpenHandCursor)
        self.title_label.setToolTip("drag to undock · double-click to dock/float")
        head.addWidget(self.title_label)
        head.addStretch(1)
        self._layout.addWidget(self._docked_head)

        self._body_host = QWidget()
        self._body_host.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        body_layout = QVBoxLayout(self._body_host)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(body)
        self._layout.addWidget(self._body_host, stretch=1)

        self.title_label.installEventFilter(self)
        self._press_global: QPoint | None = None
        self._drag_offset: QPoint | None = None
        self._float_wired = False
        QTimer.singleShot(0, self._wire_float_fill)

    def _dock(self) -> QDockWidget | None:
        widget = self.parentWidget()
        while widget is not None:
            if isinstance(widget, QDockWidget):
                return widget
            widget = widget.parentWidget()
        return None

    def _wire_float_fill(self) -> None:
        if self._float_wired:
            return
        dock = self._dock()
        if dock is None:
            return
        dock.topLevelChanged.connect(self._on_floating_changed)
        self._float_wired = True
        self._on_floating_changed(dock.isFloating())

    def apply_floating_look(self, floating: bool) -> None:
        """Public so app chrome can force the floating void layout."""
        self._apply_floating_look(bool(floating))

    def _apply_floating_look(self, floating: bool) -> None:
        self.set_fill_alpha(_FLOATING_FILL_ALPHA if floating else _DOCKED_FILL_ALPHA)
        # Floating = opaque HWND plate (no chat composite). Docked can stay glass.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, not floating)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, floating)
        self.setAutoFillBackground(bool(floating))

        if floating:
            self._layout.setContentsMargins(0, 0, 0, 0)
            self._layout.setSpacing(0)
            self._body_host.layout().setContentsMargins(10, 8, 10, 10)
            self._float_chrome.set_title(self._title)
            self._float_chrome.show()
            self._docked_head.hide()
            dock = self._dock()
            if dock is not None:
                self._float_chrome.sync_window_state(dock)
        else:
            self._layout.setContentsMargins(10, 8, 10, 10)
            self._layout.setSpacing(8)
            self._body_host.layout().setContentsMargins(0, 0, 0, 0)
            self._float_chrome.hide()
            self._docked_head.show()
            self.title_label.setVisible(True)

        shell = self.parentWidget()
        if shell is not None and not isinstance(shell, QDockWidget):
            if floating:
                shell.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
                shell.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
                shell.setAutoFillBackground(True)
                shell.setStyleSheet(f"background-color: {COLORS['plate']};")
            else:
                shell.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                shell.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
                shell.setAutoFillBackground(False)
                shell.setStyleSheet("")

        dock = self._dock()
        if dock is not None:
            dock.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, not floating)
            dock.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, floating)
            if floating and dock.graphicsEffect() is not None:
                dock.setGraphicsEffect(None)
            if not floating:
                dock.setStyleSheet("")
        self.update()

    def _on_floating_changed(self, floating: bool) -> None:
        # Keep docked drag header until mouse-up so undock gestures keep capture.
        if floating and self._press_global is not None:
            self.set_fill_alpha(_FLOATING_FILL_ALPHA)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
            dock = self._dock()
            if dock is not None:
                dock.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
                if dock.graphicsEffect() is not None:
                    dock.setGraphicsEffect(None)
            return
        self._apply_floating_look(bool(floating))

    def eventFilter(self, watched, event) -> bool:
        if watched is not self.title_label or not isinstance(event, QMouseEvent):
            return super().eventFilter(watched, event)
        dock = self._dock()
        if dock is None:
            return super().eventFilter(watched, event)

        kind = event.type()
        if kind == QMouseEvent.Type.MouseButtonDblClick:
            dock.setFloating(not dock.isFloating())
            return True
        if kind == QMouseEvent.Type.MouseButtonPress:
            if event.button() != Qt.MouseButton.LeftButton:
                return False
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = self._press_global - dock.frameGeometry().topLeft()
            return True
        if kind == QMouseEvent.Type.MouseMove:
            if self._press_global is None:
                return False
            current = event.globalPosition().toPoint()
            if not dock.isFloating():
                travelled = (current - self._press_global).manhattanLength()
                if travelled < _UNDOCK_DRAG_PX:
                    return True
                dock.setFloating(True)
                self._drag_offset = QPoint(dock.width() // 2, 12)
            dock.move(current - (self._drag_offset or QPoint()))
            return True
        if kind == QMouseEvent.Type.MouseButtonRelease:
            self._press_global = None
            self._drag_offset = None
            if dock.isFloating():
                self._apply_floating_look(True)
            return True
        return super().eventFilter(watched, event)
