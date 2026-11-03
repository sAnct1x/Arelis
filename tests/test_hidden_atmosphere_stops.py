"""In the tray the atmosphere timer stops instead of waking the GUI thread to skip (v11c)."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QTimer

from arelis.ui import window_chrome


def test_hidden_window_stops_the_atmosphere_timer(qt_app) -> None:
    timer = QTimer()
    timer.start(33)
    host = SimpleNamespace(
        isVisible=lambda: False, isMinimized=lambda: False, _atmosphere_timer=timer
    )
    window_chrome.WindowChrome._tick_atmosphere(host)
    assert not timer.isActive()
