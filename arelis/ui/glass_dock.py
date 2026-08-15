"""Frameless glass QDockWidget — edge resize while floating (matches main shell)."""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QDockWidget

from arelis.ui.window_resize import (
    cursor_for_hit,
    enable_win32_resize_frame,
    handle_native_resize,
    hit_test_resize,
    try_system_resize,
)


class GlassDockWidget(QDockWidget):
    """Dock that resizes like the main frameless shell while undocked."""

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.isFloating():
            enable_win32_resize_frame(self)
            self.setMouseTracking(True)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isFloating():
            if not (self.isMaximized() or self.isFullScreen()):
                enable_win32_resize_frame(self)
            # Prefer in-panel FloatingDockTitleBar (not the zero stub titleBarWidget).
            from arelis.ui.chrome import FloatingDockTitleBar

            for bar in self.findChildren(FloatingDockTitleBar):
                bar.sync_window_state(self)
                break

    def nativeEvent(self, eventType, message):
        if self.isFloating():
            handled = handle_native_resize(self, eventType, message)
            if handled is not None:
                return handled
        return super().nativeEvent(eventType, message)

    def mousePressEvent(self, event) -> None:
        if self.isFloating() and event.button() == Qt.MouseButton.LeftButton:
            if try_system_resize(self, event.globalPosition().toPoint()):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.isFloating():
            shape = cursor_for_hit(hit_test_resize(self))
            if shape is not None:
                self.setCursor(shape)
            else:
                self.unsetCursor()
        super().mouseMoveEvent(event)
