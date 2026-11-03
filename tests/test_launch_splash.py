"""Launch: the heavy load runs off the UI thread while her splash keeps breathing."""

import threading
import time

from PySide6.QtWidgets import QApplication

from arelis.ui.splash import LaunchSplash, run_off_ui


def test_load_runs_off_ui_while_splash_animates() -> None:
    QApplication.instance() or QApplication([])
    splash = LaunchSplash()
    splash.start()
    seen = splash.frames

    def work():
        time.sleep(0.4)
        return threading.current_thread()

    try:
        ran_on = run_off_ui(splash, "Loading model", work)
        assert ran_on is not threading.main_thread()
        assert splash.status() == "Loading model"
        assert splash.frames - seen >= 3  # it kept painting during the load
    finally:
        splash.finish()


def test_no_window_is_up_before_first_run_setup(monkeypatch, tmp_path) -> None:
    """The installer probe's first titled window must be the welcome dialog, not her splash."""
    QApplication.instance() or QApplication([])
    from arelis.ui import launch as launch_mod

    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(launch_mod, "_second_launch", lambda *_a, **_k: 0)
    from PySide6.QtCore import QEvent, QObject

    class _Shows(QObject):
        def __init__(self) -> None:
            super().__init__()
            self.shown: list[str] = []
            self.open = True

        def eventFilter(self, obj, event) -> bool:
            if self.open and event.type() == QEvent.Type.Show and obj.isWidgetType():
                if obj.isWindow():
                    self.shown.append(obj.windowTitle() or obj.objectName())
            return False

    shows = _Shows()
    QApplication.instance().installEventFilter(shows)

    def _setup(*_a, **_k):
        shows.open = False  # only what came up before setup counts
        return None  # unfinished setup: run_ui stops here

    monkeypatch.setattr(launch_mod, "apply_first_run_glass", _setup)
    monkeypatch.setattr("arelis.ui.dialog.notice", lambda *_a, **_k: None)
    try:
        assert launch_mod.run_ui({}) == 1
    finally:
        QApplication.instance().removeEventFilter(shows)
    assert shows.shown == []
