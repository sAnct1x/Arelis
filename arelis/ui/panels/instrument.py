from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QDockWidget, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from arelis.ui.chrome import FloatingDockTitleBar
from arelis.ui.dock_surface import (
    DOCKED_FILL_ALPHA,
    apply_dock_chrome,
    begin_drag_undock,
    end_drag_undock,
)
from arelis.ui.glass import GlassFrame
from arelis.ui.theme import GLASS

# How far the pointer must travel on the header before a docked panel pops out.
_UNDOCK_DRAG_PX = 24


class InstrumentPanel(GlassFrame):
    """Glass dock body: docked drag header, floating continuous-plate chrome.

    Owns which header is showing and the margins around it. Does not own its own
    translucency — ``arelis.ui.dock_surface`` writes that for the whole dock
    subtree at once, and this panel used to be one of six writers fighting it.

    The parent QDockWidget keeps a zero-height title bar always. Undocked window
    chrome (min/max/close) lives in-panel so the tile is one void slab.
    """

    def __init__(self, title: str, body: QWidget, parent=None) -> None:
        super().__init__(
            parent,
            object_name="GlassDockContent",
            fill_alpha=DOCKED_FILL_ALPHA,
            radius=float(GLASS["radius"]),
            pulse_rim=False,
            surface_owned=True,
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

    def _dock(self) -> QDockWidget | None:
        widget = self.parentWidget()
        while widget is not None:
            if isinstance(widget, QDockWidget):
                return widget
            widget = widget.parentWidget()
        return None

    def set_floating_layout(self, floating: bool) -> None:
        """Swap header chrome and inner margins for the docked/floating look.

        Called by ``apply_dock_surface``. Writes no surface attributes.
        """
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
                # Ask for the surface now and the window flags later: swapping
                # flags re-creates the HWND, which drops the grab this drag is
                # running on. The float is never translucent in the meantime.
                begin_drag_undock(dock)
                dock.setFloating(True)
                self._drag_offset = QPoint(dock.width() // 2, 12)
            dock.move(current - (self._drag_offset or QPoint()))
            return True
        if kind == QMouseEvent.Type.MouseButtonRelease:
            self._press_global = None
            self._drag_offset = None
            if end_drag_undock(dock):
                apply_dock_chrome(dock, dock.isFloating())
            return True
        return super().eventFilter(watched, event)
