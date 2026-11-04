"""Quit during her first load: dispose took the window's filter off the app but not off
app_filters' list, so her scene build's quiet() put the closed window's filter back."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QWidget


def test_a_disposed_windows_filter_is_not_reinstalled_by_quiet(qt_app) -> None:
    from arelis.ui import app_filters
    from arelis.ui.window_lifetime import WindowLifetime

    class Win(WindowLifetime, QWidget):
        def __init__(self) -> None:
            QWidget.__init__(self)
            self._disposed = False
            self.seen = 0
            stub = SimpleNamespace(stop_track=lambda: None, stop=lambda: None)
            self.spatial = self.camera = self._filament_render = stub
            self.voice_controller = None

        def eventFilter(self, obj, ev) -> bool:
            self.seen += 1
            return False

    app = QApplication.instance()
    win = Win()
    app_filters.install(app, win)
    win.dispose()
    with app_filters.quiet():
        pass
    win.seen = 0
    QApplication.sendEvent(QWidget(), QEvent(QEvent.Type.User))
    assert win.seen == 0
