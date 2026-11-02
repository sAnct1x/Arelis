import time

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QWidget

from arelis.ui import launch


class _Sizes(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.widths: list[int] = []

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.widths.append(event.size().width())
        return False


def test_a_maximized_launch_is_resized_once_exposed_so_its_surface_presents(qt_app, monkeypatch):
    monkeypatch.setattr(launch, "quiet_launch", lambda _w: False)
    w = QWidget()
    w.setWindowState(Qt.WindowState.WindowMaximized)
    sizes = _Sizes()
    w.installEventFilter(sizes)
    launch._present_at_startup(w)
    end = time.monotonic() + 2.0
    while time.monotonic() < end:
        qt_app.processEvents()
    full = w.width()
    w.close()
    assert full - 1 in sizes.widths and sizes.widths[-1] == full
