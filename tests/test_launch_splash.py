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
