"""Sentinels window: inset frameless host for the bridge Overseer page.

Hosts the bridge's Overseer in a QWebEngineView. The session token rides in
the URL fragment and is never logged. When the Sentinel child is down the
window shows "Sentinel offline" with a Start button. Theme colours follow
the active Arelis theme. Opening fades Arelis and the orbit tree to 20
percent; close, quit, or an error restores them.
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from arelis import sentinel_control
from arelis.ui.sentinel_presence import PresenceController, inset_geometry, mote_pos
from arelis.ui.theme_tokens import COLORS, active_theme

log = logging.getLogger(__name__)

_POLL_MS = 500
_POLL_TRIES = 24


def _reduced_motion() -> bool:
    try:
        from PySide6.QtGui import QGuiApplication

        hints = QGuiApplication.styleHints()
        fn = getattr(hints, "animationsEnabled", None)
        if callable(fn):
            return not bool(fn())
    except Exception:
        # Style hints or the animations query are missing on this Qt build.
        # Treat motion as allowed rather than invent a reduced-motion state.
        return False
    return False


class SentinelMote(QWidget):
    """Idle mote below the orbit. Click opens the Sentinels window."""

    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner)
        self.setObjectName("SentinelMote")
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Sentinels")
        self._owner = owner
        self.show()
        self.raise_()
        self.reposition()

    def reposition(self) -> None:
        if self._owner is None:
            return
        x, y = mote_pos(self._owner.width(), self._owner.height())
        self.move(QPoint(max(0, x - 11), max(0, y - 11)))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            open_sentinel_window(self._owner)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#a78bfa"))
        painter.setOpacity(0.35)
        painter.drawEllipse(1, 1, 20, 20)
        painter.setOpacity(0.8)
        painter.setBrush(QColor("#e2d6ff"))
        painter.drawEllipse(6, 6, 10, 10)


class SentinelWindow(QWidget):
    """Top-level inset Sentinels window: Overseer page, or the offline card."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(None)
        self._owner = parent
        self.presence = PresenceController()
        self.setObjectName("SentinelWindow")
        self.setWindowTitle("Sentinels")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self._view = None
        self._loaded_url: str | None = None
        self._tries = 0
        self._error = ""

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

        self._close_mote = QPushButton("x", self)
        self._close_mote.setObjectName("SentinelCloseMote")
        self._close_mote.setToolTip("Close (Esc)")
        self._close_mote.setFixedSize(28, 28)
        self._close_mote.clicked.connect(self.close)
        self._close_mote.raise_()

        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_MS)
        self._poll.timeout.connect(self._poll_tick)
        QShortcut(QKeySequence("Esc"), self, activated=self.close)
        if parent is not None:
            parent.installEventFilter(self)
        self.apply_theme()
        self._sync_inset()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._owner and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
        ):
            self._sync_inset()
        return super().eventFilter(watched, event)

    def _sync_inset(self) -> None:
        owner = self._owner
        if owner is None:
            self.resize(1200, 780)
            return
        geo = owner.geometry()
        x, y, w, h = inset_geometry(geo.width(), geo.height())
        self.setGeometry(geo.x() + x, geo.y() + y, w, h)
        self._close_mote.move(max(8, w - 46), 48)

    def apply_theme(self) -> None:
        bg = COLORS.get("bg0", "#0b0714")
        text = COLORS.get("text", "#e0d4ff")
        accent = COLORS.get("accent", "#a78bfa")
        well = COLORS.get("well", "rgba(14, 9, 32, 255)")
        theme = active_theme()
        self.setProperty("sentinelTheme", theme)
        self.setStyleSheet(
            f"#SentinelWindow, QStackedWidget, QWidget {{ background: {bg}; color: {text}; }}"
            f"#SentinelOfflineLabel {{ font-size: 18px; qproperty-alignment: AlignCenter; }}"
            f"#SentinelStartButton {{ background: {well}; color: {text};"
            f" border: 1px solid {accent}; padding: 6px 18px; }}"
            f"#SentinelCloseMote {{ background: #d9ccff; color: #1c1430;"
            f" border: 2px solid {accent}; border-radius: 14px; }}"
        )
        self._push_theme_to_page(theme)

    def _push_theme_to_page(self, theme: str) -> None:
        view = self._view
        if view is None:
            return
        page = getattr(view, "page", lambda: None)()
        if page is None or not hasattr(page, "runJavaScript"):
            return
        safe = theme.replace("\\", "").replace('"', "")
        page.runJavaScript(
            f'document.documentElement.setAttribute("data-theme","{safe}");'
            f'window.dispatchEvent(new CustomEvent("arelis-theme",{{detail:"{safe}"}}));'
        )

    def is_offline(self) -> bool:
        return self._stack.currentWidget() is self._offline

    def last_error(self) -> str:
        return self._error

    def refresh(self) -> None:
        """Show the Overseer if the child is up, else the offline card."""
        url = sentinel_control.overseer_url()
        if not url:
            self.offline_label.setText("Sentinel offline")
            self._stack.setCurrentWidget(self._offline)
            return
        view = self._ensure_view()
        if view is None:
            self._error = "Sentinel is running, but this window can't show it right now"
            self.offline_label.setText(self._error)
            self._stack.setCurrentWidget(self._offline)
            self._restore_presence("error")
            return
        self._error = ""
        if url != self._loaded_url:
            self._loaded_url = url
            view.setUrl(QUrl(url))
        self._stack.setCurrentWidget(view)
        self._push_theme_to_page(active_theme())

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

    def _fade_owner(self) -> None:
        owner = self._owner
        if owner is None:
            return
        surface = getattr(owner, "_quick_surface", None)
        self.presence.open_window(reduced=_reduced_motion())
        self.presence.apply_to(surface)
        mote = getattr(owner, "sentinel_mote", None)
        if mote is not None:
            mote.hide()

    def _restore_presence(self, reason: str = "close") -> None:
        owner = self._owner
        surface = getattr(owner, "_quick_surface", None) if owner is not None else None
        self.presence.restore(reason, reduced=_reduced_motion())
        self.presence.apply_to(surface)
        mote = getattr(owner, "sentinel_mote", None) if owner is not None else None
        if mote is not None:
            mote.show()
            mote.reposition()

    def showEvent(self, event) -> None:
        self.apply_theme()
        self._sync_inset()
        self.refresh()
        self._fade_owner()
        super().showEvent(event)

    def closeEvent(self, event) -> None:
        if self.presence.open:
            self._restore_presence("close")
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        self._close_mote.move(max(8, self.width() - 46), 48)
        super().resizeEvent(event)


def teardown_sentinel_window(window) -> None:
    """Quit: restore presence, stop polling, unload the page, then close."""
    win = getattr(window, "sentinel_window", None)
    if win is None:
        return
    window.sentinel_window = None
    win._poll.stop()
    win._restore_presence("quit")
    if win._view is not None:
        win._view.setUrl(QUrl("about:blank"))
    win.close()
    win.deleteLater()


def attach_sentinel_mote(window) -> SentinelMote | None:
    """Filament entry mote below the orbit. Safe to call more than once."""
    existing = getattr(window, "sentinel_mote", None)
    if existing is not None:
        existing.reposition()
        return existing
    mote = SentinelMote(window)
    window.sentinel_mote = mote
    return mote


def open_sentinel_window(window) -> SentinelWindow:
    """View -> Sentinels, or the entry mote. One window per main window."""
    win = getattr(window, "sentinel_window", None)
    if win is None:
        win = SentinelWindow(window)
        window.sentinel_window = win
    win.show()
    win.raise_()
    win.activateWindow()
    return win
