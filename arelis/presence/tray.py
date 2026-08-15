"""Minimal core-owned system tray (Open UI / Quit) — Qt, no glass window."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)


class CoreTray:
    """Runs a QSystemTrayIcon on a dedicated thread with its own QApplication."""

    def __init__(
        self,
        *,
        on_open_ui: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        self._on_open_ui = on_open_ui
        self._on_quit = on_quit
        self._thread: threading.Thread | None = None
        self._app: Any = None
        self._tray: Any = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run, name="arelis-core-tray", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        app = self._app
        if app is not None:
            try:
                app.quit()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)
        self._thread = None
        self._app = None
        self._tray = None

    def _run(self) -> None:
        try:
            from PySide6.QtGui import QAction, QIcon
            from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
        except Exception as exc:
            log.warning("Core tray unavailable (Qt): %s", exc)
            return

        import os

        from arelis.config import PROJECT_ROOT

        # Avoid fighting a glass UI's QApplication on the main thread — we are
        # already on a dedicated thread with our own instance.
        os.environ.setdefault("QT_QPA_PLATFORM", "windows")
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        app.setApplicationName("Arelis Core")
        app.setQuitOnLastWindowClosed(False)
        self._app = app

        if sys_platform_is_windows():
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
                    "Arelis.Core"
                )
            except Exception:
                pass

        icon_path = PROJECT_ROOT / "assets" / "arelis.ico"
        icon = QIcon(str(icon_path)) if icon_path.is_file() else QIcon()
        tray = QSystemTrayIcon(icon)
        menu = QMenu()
        act_open = QAction("Open Arelis", menu)
        act_quit = QAction("Quit Arelis", menu)
        act_open.triggered.connect(self._handle_open)
        act_quit.triggered.connect(self._handle_quit)
        menu.addAction(act_open)
        menu.addSeparator()
        menu.addAction(act_quit)
        tray.setContextMenu(menu)
        tray.setToolTip("Arelis core")
        tray.activated.connect(self._on_activated)
        tray.show()
        self._tray = tray
        log.info("Core tray started")
        app.exec()
        log.info("Core tray stopped")

    def _handle_open(self) -> None:
        if self._on_open_ui is not None:
            try:
                self._on_open_ui()
            except Exception:
                log.exception("Core tray Open UI failed")

    def _handle_quit(self) -> None:
        if self._on_quit is not None:
            try:
                self._on_quit()
            except Exception:
                log.exception("Core tray Quit failed")
        if self._app is not None:
            self._app.quit()

    def _on_activated(self, reason: Any) -> None:
        try:
            from PySide6.QtWidgets import QSystemTrayIcon
        except Exception:
            return
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self._handle_open()


def sys_platform_is_windows() -> bool:
    import sys

    return sys.platform == "win32"
