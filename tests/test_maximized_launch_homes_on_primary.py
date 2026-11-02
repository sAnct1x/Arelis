from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget

from arelis.ui import launch


def test_a_maximized_launch_saved_on_another_monitor_is_created_on_the_primary(qt_app, monkeypatch):
    monkeypatch.setattr(launch, "quiet_launch", lambda _w: False)
    monkeypatch.setattr(launch, "show_without_activating", lambda _w: None)
    w = QWidget()
    avail = QApplication.primaryScreen().availableGeometry()
    w.setGeometry(avail.right() + 900, avail.top() + 450, 640, 480)
    w.setWindowState(Qt.WindowState.WindowMaximized)
    launch._present_at_startup(w)
    assert avail.contains(w.geometry().center())
