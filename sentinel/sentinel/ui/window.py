"""Native PySide6 Desktop Window hosting the 60 FPS 3D Sentinel Overseer Viewport.

Uses QWebEngineView (matching Arelis's earth_globe architecture) to avoid the
native Qt OpenGL widget AMD driver crash documented in arelis/ui/solar_gl.py,
while also keeping the viewport accessible at http://127.0.0.1:8790/overseer.
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import logging
import math
import socket
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

from sentinel.bridge.protocol import ensure_session_token, overseer_open_url
from sentinel.bridge.server import SentinelBridgeServer
from sentinel.config import resolve_theme
from sentinel.core.hive import SwarmHive
from sentinel.paths import overseer_static_dir

log = logging.getLogger("sentinel.ui")


def _is_port_listening(host: str, port: int) -> bool:
    """Return True if a local Sentinel Bridge is already listening on (host, port)."""
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def ensure_sentinel_ico() -> Path:
    """Generate a high-DPI Matrix Sentinel .ico file if not already present."""
    ico_path = overseer_static_dir() / "sentinel.ico"
    if ico_path.is_file() and ico_path.stat().st_size > 512:
        return ico_path

    try:
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF, QRadialGradient

        size = 256
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(QColor(0, 0, 0, 0))

        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Outer dark obsidian circular badge with sodium/crimson rim
        bg_grad = QRadialGradient(128, 118, 118)
        bg_grad.setColorAt(0.0, QColor(34, 26, 24, 255))
        bg_grad.setColorAt(0.75, QColor(14, 12, 14, 255))
        bg_grad.setColorAt(1.0, QColor(6, 6, 8, 255))
        p.setBrush(bg_grad)
        p.setPen(QPen(QColor(255, 122, 34, 230), 6.0))
        p.drawEllipse(12, 12, 232, 232)

        # 8 Biomechanical tentacles radiating from lower carapace
        for i in range(8):
            frac = (i - 3.5) / 3.5
            x0 = 128 + frac * 42
            y0 = 136 + abs(frac) * 8
            x1 = 128 + frac * 78 + math.sin(i * 1.2) * 10
            y1 = 186
            x2 = 128 + frac * 62
            y2 = 228 - abs(frac) * 14
            p.setPen(QPen(QColor(68, 76, 92, 240), 7.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
            p.setPen(QPen(QColor(255, 122, 34, 215), 4.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Sentinel multi-plate cephalopod head dome
        dome = QPolygonF(
            [
                QPointF(128, 34),
                QPointF(186, 76),
                QPointF(172, 142),
                QPointF(128, 156),
                QPointF(84, 142),
                QPointF(70, 76),
            ]
        )
        p.setBrush(QColor(28, 32, 40, 255))
        p.setPen(QPen(QColor(255, 42, 58, 240), 4.5))
        p.drawPolygon(dome)

        # Glowing 8-eye crimson/amber sensor cluster
        eyes = [
            (128, 86, 11),
            (104, 96, 8),
            (152, 96, 8),
            (114, 118, 7),
            (142, 118, 7),
            (92, 114, 6),
            (164, 114, 6),
            (128, 64, 7),
        ]
        for ex, ey, er in eyes:
            eye_grad = QRadialGradient(ex, ey, er * 1.8)
            eye_grad.setColorAt(0.0, QColor(255, 255, 255, 255))
            eye_grad.setColorAt(0.45, QColor(255, 42, 58, 255))
            eye_grad.setColorAt(1.0, QColor(255, 42, 58, 0))
            p.setBrush(eye_grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(ex, ey), er * 1.6, er * 1.6)

        p.end()
        img.save(str(ico_path), b"ICO")
    except Exception:
        log.debug("Could not generate sentinel.ico via Qt", exc_info=True)

    return ico_path


class _AsyncBridgeRunner:
    """Runs the SwarmHive + SentinelBridgeServer in a dedicated asyncio daemon thread."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.loop = asyncio.new_event_loop()
        self.hive = SwarmHive(config)
        bridge_cfg = config.get("bridge") or {}
        self.server = SentinelBridgeServer(
            self.hive,
            host=str(bridge_cfg.get("host", "127.0.0.1")),
            preferred_port=int(bridge_cfg.get("port", 8790)),
            telemetry_hz=int(bridge_cfg.get("telemetry_hz", 30)),
        )
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="SentinelHiveThread", daemon=True)

    def start(self) -> str:
        self._thread.start()
        self._ready.wait(timeout=10.0)
        return self.server.overseer_url

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.server.start())
        self._ready.set()
        try:
            self.loop.run_forever()
        finally:
            self.loop.run_until_complete(self.server.stop())
            self.loop.close()

    def stop(self) -> None:
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=3.0)


def launch_overseer_window(config: dict[str, Any]) -> int:
    """Start the Hive + Bridge (or attach if already online) and open the native PySide6 Overseer window."""
    bridge_cfg = config.get("bridge") or {}
    host = str(bridge_cfg.get("host", "127.0.0.1"))
    port = int(bridge_cfg.get("port", 8790))

    runner: _AsyncBridgeRunner | None = None
    if _is_port_listening(host, port):
        url = overseer_open_url(host, port, ensure_session_token())
    else:
        runner = _AsyncBridgeRunner(config)
        url = runner.start()

    ui_cfg = config.get("ui") or {}
    width = int(ui_cfg.get("window_width", 1540))
    height = int(ui_cfg.get("window_height", 940))
    theme_dict = resolve_theme(str(ui_cfg.get("theme", "sodium")))
    bg_hex = str(theme_dict.get("bg0", "#100d0b"))

    try:
        if sys.platform == "win32":
            with contextlib.suppress(Exception):
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Arelis.Sentinel.Overseer.1")

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QIcon, QKeySequence, QShortcut
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWidgets import QApplication, QMainWindow

        existing_app = QApplication.instance()
        app: QApplication = existing_app if isinstance(existing_app, QApplication) else QApplication(sys.argv)
        app.setApplicationName("Arelis Sentinel")

        ico_path = ensure_sentinel_ico()
        if ico_path.is_file():
            icon = QIcon(str(ico_path))
            app.setWindowIcon(icon)

        win = QMainWindow()
        win.setWindowTitle("ARELIS SENTINEL — Autonomous Swarm & 3D Overseer")
        if ico_path.is_file():
            win.setWindowIcon(QIcon(str(ico_path)))
        win.resize(width, height)
        win.setStyleSheet(f"QMainWindow {{ background-color: {bg_hex}; }}")

        def _toggle_fullscreen() -> None:
            if win.isFullScreen():
                win.showNormal()
            else:
                win.showFullScreen()

        f11_shortcut = QShortcut(QKeySequence("F11"), win)
        f11_shortcut.activated.connect(_toggle_fullscreen)

        view = QWebEngineView(win)
        view.settings().setAttribute(QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True)

        def _on_fs_req(req: Any) -> None:
            req.accept()
            if req.toggleOn():
                win.showFullScreen()
            else:
                win.showNormal()

        view.page().fullScreenRequested.connect(_on_fs_req)
        view.page().setBackgroundColor(QColor(bg_hex))
        view.setUrl(QUrl(url))
        win.setCentralWidget(view)
        win.show()

        exit_code = app.exec()
        if runner is not None:
            runner.stop()
        return int(exit_code)
    except ImportError:
        log.info(
            "PySide6-WebEngine not installed; opening the Overseer in the browser."
        )
        webbrowser.open(url)
        if runner is not None:
            try:
                while True:
                    threading.Event().wait(3600)
            except KeyboardInterrupt:
                runner.stop()
        return 0
