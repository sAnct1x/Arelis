"""Sentinels window, View -> Sentinels. A separate top-level window.

Hosts the bridge's Overseer page in a QWebEngineView, like the Earth globe.
The session token rides in the URL fragment (see sentinel_control.overseer_url)
and is never logged. When the Sentinel child is down the window shows
"Sentinel offline" with a Start button that runs the normal start path.
Window chrome takes its colours from the active Arelis theme tokens.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from arelis import sentinel_control
from arelis.ui.theme_tokens import COLORS

log = logging.getLogger(__name__)

_POLL_MS = 500
_POLL_TRIES = 24


class SentinelWindow(QWidget):
    """Top-level Sentinels window: Overseer page, or the offline card."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(None)
        self._owner = parent
        self.setObjectName("SentinelWindow")
        self.setWindowTitle("Sentinels")
        self.resize(1200, 780)
        self._view = None
        self._loaded_url: str | None = None
        self._tries = 0

        self._stack = QStackedWidget(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._stack)

        self._offline = QWidget(self)
        off = QVBoxLayout(self._offline)
        off.addStretch(1)
        self.offline_label = QLabel("Sentinel offline", self._offline)
        self.offline_label.setObjectName("SentinelOfflineLabel")
        self.start_button = QPushButton("Start", self._offline)
        self.start_button.setObjectName("SentinelStartButton")
        self.start_button.clicked.connect(self.start_sentinel)
        off.addWidget(self.offline_label, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        off.addWidget(self.start_button, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        off.addStretch(1)
        self._stack.addWidget(self._offline)

        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_MS)
        self._poll.timeout.connect(self._poll_tick)
        self.apply_theme()

    def apply_theme(self) -> None:
        bg = COLORS.get("bg0", "#100d0b")
        text = COLORS.get("text", "#f8f1ea")
        accent = COLORS.get("accent", "#ff7a22")
        well = COLORS.get("well", "rgba(74, 60, 50, 255)")
        self.setStyleSheet(
            f"#SentinelWindow, QStackedWidget, QWidget {{ background: {bg}; color: {text}; }}"
            f"#SentinelOfflineLabel {{ font-size: 18px; qproperty-alignment: AlignCenter; }}"
            f"#SentinelStartButton {{ background: {well}; color: {text};"
            f" border: 1px solid {accent}; padding: 6px 18px; }}"
        )

    def is_offline(self) -> bool:
        return self._stack.currentWidget() is self._offline

    def refresh(self) -> None:
        """Show the Overseer if the child is up, else the offline card."""
        url = sentinel_control.overseer_url()
        if not url:
            self._stack.setCurrentWidget(self._offline)
            return
        view = self._ensure_view()
        if view is None:
            self.offline_label.setText("Sentinel is running, but the web view is unavailable")
            self._stack.setCurrentWidget(self._offline)
            return
        if url != self._loaded_url:
            self._loaded_url = url
            view.setUrl(QUrl(url))
        self._stack.setCurrentWidget(view)

    def _ensure_view(self):
        if self._view is not None:
            return self._view
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            log.warning("Sentinels window: QtWebEngine unavailable")
            return None
        self._view = QWebEngineView(self)
        self._stack.addWidget(self._view)
        return self._view

    def start_sentinel(self) -> None:
        """Run the normal start path off the UI thread, then poll for the URL."""
        self.start_button.setEnabled(False)
        self.offline_label.setText("Starting Sentinel")
        threading.Thread(
            target=sentinel_control.start,
            name="arelis-sentinel-start",
            daemon=True,
        ).start()
        self._tries = 0
        self._poll.start()

    def _poll_tick(self) -> None:
        self._tries += 1
        if sentinel_control.overseer_url() or self._tries >= _POLL_TRIES:
            self._poll.stop()
            self.start_button.setEnabled(True)
            self.offline_label.setText("Sentinel offline")
            self.refresh()

    def showEvent(self, event) -> None:
        self.apply_theme()
        self.refresh()
        super().showEvent(event)


def open_sentinel_window(window) -> SentinelWindow:
    """View -> Sentinels. One window per main window; raise it if open."""
    win = getattr(window, "sentinel_window", None)
    if win is None:
        win = SentinelWindow(window)
        window.sentinel_window = win
    win.show()
    win.raise_()
    win.activateWindow()
    return win
