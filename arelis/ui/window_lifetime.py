"""Dispose, close-to-tray, park, and Quit.

Mixin on ArelisWindow. Same HWND. Not a second QMainWindow.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QSystemTrayIcon,
    QWidget,
)

from arelis.core.bus import bind_app_bus
from arelis.paths import app_icon_path
from arelis.ui.idle_host import wake_from_away_rest
from arelis.ui.layout_store import (
    save_window_layout,
)
from arelis.ui.theme import (
    GLASS,
    active_theme,
)
from arelis.ui.voice_host import stop_speech
from arelis.ui.window_resize import (
    invalidate_window_surface,
)

log = logging.getLogger(__name__)

_WINDOW_RADIUS = int(GLASS["radius"])
_BUSY_WATCHDOG_MS = 8000
_THINK_PULSE_MS = 600
_VOICE_HOTKEY_ECHO_S = 0.12

_PANEL_OUTER = 12
_PANEL_HALF = 6
_PANEL_TOP = 12
_PANEL_BOTTOM = 14



class WindowLifetime:
    def _later(self, ms: int, fn: Callable[[], Any]) -> None:
        """A single-shot this window will drop if it is gone by the time it fires.

        Building the window schedules seven of these, at 0, 40, 80 and 250ms, to
        settle layout and focus after the first event-loop pass. That is fine in
        the app, where the window outlives them by hours. It is not fine anywhere
        the window is short-lived: the callback arrives later, touches widgets
        whose C++ halves have since been deleted, and takes the process with it.

        ``QTimer.singleShot`` cannot be cancelled, so the shot still fires — it
        just finds a disposed window and returns. That is the whole mechanism.
        """
        QTimer.singleShot(
            ms,
            lambda: None
            if self._disposed or getattr(self, "_force_quit", False)
            else fn(),
        )

    def dispose(self) -> None:
        """Release everything that outlives a hidden window. Idempotent.

        ``closeEvent`` is the app's teardown and does much more than this — layout
        save, asyncio shutdown, tray, model unload — but it stops only four of the
        nine timers and never removes the application-wide event filter, because
        the process was about to end anyway.

        A test process is not about to end. It builds sixteen of these windows and
        only hides them, so the filters stack up, the atmosphere timers keep
        repainting, and pending single-shots land on widgets a later drain has
        already deleted. That is the access violation that moved around the suite
        depending on file order: not a flake, an accumulation.
        """
        if self._disposed:
            return
        self._disposed = True
        bind_app_bus(None)

        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)

        for timer in self.findChildren(QTimer):
            try:
                timer.stop()
            except RuntimeError:
                # Already deleted by Qt. Nothing left to stop.
                pass

        # Devices Qt will not release on its own, and Windows keeps claimed.
        for release in (
            lambda: self.spatial.stop_track(),
            lambda: self.camera.stop(),
            lambda: (
                self.voice_controller.stop_all()
                if self.voice_controller is not None
                else None
            ),
            lambda: stop_speech(self),
        ):
            try:
                release()
            except Exception:
                log.debug("dispose: release step failed", exc_info=True)

        # Top-level children are not reparented by hiding the window, so they
        # would survive it and keep their own timers and filters.
        for child in list(self.findChildren(QWidget)):
            try:
                if child.isWindow() and child is not self:
                    child.hide()
                    child.deleteLater()
            except RuntimeError:
                pass

        try:
            self.hide()
        except RuntimeError:
            pass
        self.deleteLater()

    def closeEvent(self, event) -> None:
        # Close-to-tray: keep ingest / bus alive; Quit from the tray fully exits.
        if (
            self._close_to_tray
            and not self._force_quit
            and self._tray is not None
            and self._tray.isVisible()
        ):
            self._persist_window_layout()
            if self.voice_controller is not None:
                self.voice_controller.stop_all()
            stop_speech(self)
            try:
                self.camera.stop()
            except Exception:
                pass
            self._remember_window_state()
            self._park_floating_docks()
            self.hide()
            self._tray.showMessage(
                "Arelis",
                "Still running in the tray — inbound texts keep working. "
                "Quit from the tray menu to stop fully.",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
            event.ignore()
            return

        quit_t0 = time.monotonic()
        log.info("quit_begin force=%s", self._force_quit)
        bind_app_bus(None)
        self._persist_window_layout()
        # Tray Quit must drop the glass immediately. Inbound stop can take a
        # couple of seconds; leaving the window up for that is what made Quit
        # feel like a hang, and a second shortcut click then stacked another.
        if self._force_quit:
            self._park_floating_docks()
            if self._tray is not None:
                try:
                    self._tray.hide()
                except RuntimeError:
                    pass
            try:
                self.hide()
            except RuntimeError:
                pass
        # Release the microphone and the audio device before the window goes.
        # Qt will not do it for us and Windows keeps both claimed.
        if self.voice_controller is not None:
            self.voice_controller.stop_all()
        stop_speech(self)
        try:
            self.camera.stop()
        except Exception:
            log.debug("camera stop on quit failed", exc_info=True)
        self._index_timer.stop()
        self._atmosphere_timer.stop()
        self._notify_timer.stop()
        self._calendar_sync_timer.stop()
        self._calendar_sync_watchdog.stop()
        self._job_tick.stop()
        # Tray Quit must feel instant. Stop notify first (phone listener), then
        # best-effort flush — never wait on model unload / long indexer work.
        inbound_timeout = 2.0 if self._force_quit else 5.0
        loop = self.loop
        loop_up = loop is not None and loop.is_running()
        if (
            self.inbound_runtime is not None
            and self.inbound_runtime.owned
            and loop_up
        ):
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self.inbound_runtime.stop(), loop
                )
                fut.result(timeout=inbound_timeout)
            except Exception:
                log.warning("inbound stop timed out or failed during quit", exc_info=True)
            self.sms_ingest = None
            self.sms_watcher = None
            self.sms_auto_reply = None
        elif self.inbound_runtime is not None and self.inbound_runtime.owned:
            self.sms_ingest = None
            self.sms_watcher = None
            self.sms_auto_reply = None
        # Never block tray Quit on indexer flush.
        if (
            self.indexer is not None
            and not self._turn_busy
            and not self._force_quit
            and loop_up
        ):
            try:
                fut = asyncio.run_coroutine_threadsafe(self.indexer.flush(), loop)
                fut.result(timeout=1.5)
            except TimeoutError:
                log.info("indexer flush skipped on quit (timeout)")
            except Exception:
                log.warning("indexer flush failed during quit", exc_info=True)
        try:
            from arelis.tools.comfy_lifecycle import cancel_comfy_idle, park_comfy

            cancel_comfy_idle()
            park_comfy()
        except Exception:
            log.debug("Comfy park on quit failed", exc_info=True)
        if self._tray is not None:
            self._tray.hide()
        try:
            self.workspace_roots.clear_external_reads()
        except Exception:
            pass
        log.info("quit_end_ms=%.0f", (time.monotonic() - quit_t0) * 1000)
        super().closeEvent(event)

    def setup_tray(self, app: QApplication) -> None:
        """OS tray icon: Show window / Quit Arelis."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self._close_to_tray = False
            return
        icon_path = app_icon_path()
        icon = QIcon(str(icon_path)) if icon_path.is_file() else self.windowIcon()
        tray = QSystemTrayIcon(icon, app)
        menu = QMenu()
        act_show = QAction("Open Arelis", menu)
        act_quit = QAction("Quit Arelis", menu)
        act_show.triggered.connect(self._on_activation_request)
        act_quit.triggered.connect(self.quit_from_tray)
        menu.addAction(act_show)
        menu.addSeparator()
        menu.addAction(act_quit)
        tray.setContextMenu(menu)
        tray.setToolTip("Arelis")
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray

    def _park_floating_docks(self) -> None:
        """Take floating instruments with the glass when it leaves the screen.

        A docked instrument is a child widget and disappears with its parent. A
        floating one is a top-level window of its own — ``apply_dock_chrome``
        gives it ``Qt.Window``, where every other companion surface here is a
        ``Qt.Tool`` and so is hidden by Qt along with its parent. The panel
        therefore stayed on screen with the glass in the tray, and the next launch
        painted a whole new Arelis underneath an orphan still sitting on top:
        two of them, stacked, which is what the ghosting reports were.

        Parked rather than closed, because coming back to a different set of
        instruments than you left would be its own small betrayal.
        """
        for dock in (
            self.think_dock,
            self.work_dock,
            self.history_dock,
            self.camera_dock,
        ):
            if dock.isFloating() and dock.isVisible():
                dock._arelis_parked = True
                dock.hide()
        cal = getattr(self, "calendar_window", None)
        if cal is not None and not cal.isHidden():
            cal._arelis_parked = True
            cal.hide()
        world = getattr(self, "world_window", None)
        if world is not None and not world.isHidden():
            world._arelis_parked = True
            world.hide()

    def _unpark_floating_docks(self) -> None:
        """Bring parked floating instruments back with the glass."""
        for dock in (
            self.think_dock,
            self.work_dock,
            self.history_dock,
            self.camera_dock,
        ):
            if not getattr(dock, "_arelis_parked", False):
                continue
            dock._arelis_parked = False
            dock.show()
            dock.raise_()
            invalidate_window_surface(dock)
        cal = getattr(self, "calendar_window", None)
        if cal is not None and getattr(cal, "_arelis_parked", False):
            cal._arelis_parked = False
            cal.show()
            cal.raise_()
        world = getattr(self, "world_window", None)
        if world is not None and getattr(world, "_arelis_parked", False):
            world._arelis_parked = False
            world.show()
            world.raise_()

    def _remember_window_state(self) -> None:
        """Record maximized/full-screen before hiding, ignoring Minimized.

        Minimized is never worth coming back to — somebody asking for the window
        wants to see it — and it is also what the OS leaves set if the glass was
        minimized on its way to the tray.
        """
        state = self.windowState()
        state &= ~Qt.WindowState.WindowMinimized
        self._tray_window_state = state

    def _on_activation_request(self) -> None:
        """Second-launch IPC / tray Open. No-op once Quit has started."""
        if self._force_quit or self._disposed:
            return
        self.show_from_tray()

    def show_from_tray(self) -> None:
        if self._force_quit or self._disposed:
            return
        if self.isVisible():
            # Asking for a window that is already up means "bring it to me", not
            # "resize it". Take what it is now as the state to come back to —
            # which also un-minimizes it, since Minimized is stripped there.
            self._remember_window_state()
        # setWindowState before show, so the window is only ever mapped once and
        # at its final size. Showing first and correcting afterwards is what put
        # a full-screen frame on screen underneath a restored-size one.
        self.setWindowState(self._tray_window_state)
        self.show()
        self.raise_()
        self.activateWindow()
        # Inbound texts and readiness keep moving while the glass is hidden.
        # Repaint this window and every float — each is its own HWND.
        invalidate_window_surface(self)
        self._unpark_floating_docks()
        self._show_next_pending_confirm()

    def quit_from_tray(self) -> None:
        """Full exit. Force-quit first so nothing can raise the glass again."""
        if self._disposed:
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return
        if self._force_quit:
            # A second click must not close() again while the first teardown
            # is still in inbound-stop. Just ask the loop to leave.
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return
        self._force_quit = True
        # When attached to --core, ask core to stop too (full Quit Arelis).
        if self.ipc_client is not None:
            try:
                self._publish_bus_coro(
                    self.ipc_client.send_shutdown(reason="ui_tray_quit")
                )
            except Exception:
                pass
        # Cancel an in-flight turn so Quit is not blocked on model/tools.
        # Do not schedule the next Allow card — that used to show the window.
        try:
            self._cancel_turn(schedule_next=False)
        except Exception:
            log.exception("quit cancel failed")
        try:
            self.close()
        except Exception:
            log.exception("quit close failed")
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _publish_bus_coro(self, coro: object) -> None:
        loop = self.loop
        if loop is None or not loop.is_running():
            return
        try:
            asyncio.run_coroutine_threadsafe(coro, loop)  # type: ignore[arg-type]
        except Exception:
            log.debug("async quit step skipped", exc_info=True)

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self._on_activation_request()

    def _persist_window_layout(self) -> None:
        """Write geometry. Rest must not persist a collapsed window."""
        if self._away_resting:
            wake_from_away_rest(self)
        if getattr(self, "_filament_parked", None) is not None and active_theme() == "filament":
            return
        save_window_layout(self)
