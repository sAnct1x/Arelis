"""A Quick host dropped mid-load (theme switch) clears the window's loading veil."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget

from arelis.ui.persona_face.quick_surface import QuickSurfaceAvatar


class _Surface:
    def __init__(self) -> None:
        self.loading = True

    def set_loading(self, on: bool) -> None:
        self.loading = on


def test_drop_before_ready_clears_loading_and_stops_timers() -> None:
    _app = QApplication.instance() or QApplication([])
    host = QWidget()
    av = QuickSurfaceAvatar(host)
    av.surface = _Surface()
    av._poll, av._deadline = QTimer(av), QTimer(av)
    av._poll.start(250)
    av._deadline.start(10000)
    av._drop()
    assert av.surface.loading is False
    assert not av._poll.isActive() and not av._deadline.isActive()
    host.deleteLater()
