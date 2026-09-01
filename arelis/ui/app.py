"""Sodium window. Mixins own construct, chrome, lifetime, and turns.

Filament is a second GUI on this same HWND — ``filament (testing)``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDockWidget, QMainWindow

from arelis.core.bus import EventBus
from arelis.core.events import Event
from arelis.llm.router import ModelRouter
from arelis.memory import MemoryIndexer, MemoryStore
from arelis.ui.dock_surface import apply_dock_chrome, apply_dock_surface
from arelis.ui.launch import (  # noqa: F401
    _drain_event_loop,
    _raise_running_instance,
    _second_launch,
    force_windows_qt_platform,
    run_ui,
)
from arelis.ui.voice_host import (
    voice_restart_notices,  # noqa: F401 — tests import this from app
)
from arelis.ui.window_aliases import WindowAliases
from arelis.ui.window_build import WindowBuild
from arelis.ui.window_chrome import WindowChrome
from arelis.ui.window_lifetime import WindowLifetime
from arelis.ui.window_turn import WindowTurn
from arelis.voice import VoiceService


class BusBridge(QObject):
    """Marshal bus events onto the Qt main thread."""

    event_arrived = Signal(object)

    def feed(self, event: Event) -> None:
        self.event_arrived.emit(event)


# Both names predate arelis.ui.dock_surface and are kept for the tray-restore
# verify helper. Surface and chrome live in one module now; see the note there
# on why a floating dock must never be a translucent HWND.
def _glassify_floating_dock(dock: QDockWidget) -> None:
    apply_dock_surface(dock, True)


def _solidify_floating_dock(dock: QDockWidget) -> None:
    apply_dock_surface(dock, True)


def _apply_floating_dock_chrome(dock: QDockWidget, floating: bool) -> None:
    apply_dock_chrome(dock, floating)


class ArelisWindow(
    WindowBuild,
    WindowChrome,
    WindowLifetime,
    WindowTurn,
    WindowAliases,
    QMainWindow,
):
    # Emitted from the asyncio thread when a handed-off recording has been
    # resolved, carrying whether it actually became a turn. Qt makes the
    # delivery queued because the receiver lives on the main thread, which is
    # what keeps this off the widgets from a foreign thread.
    utterance_settled = Signal(bool)
    # Wake-listen result: None = ignore, "" = wake only, otherwise the remainder
    # to send as the first conversation turn.
    wake_detected = Signal(object)
    # Readiness probe finished on the asyncio thread; payload is ReadinessSnapshot.
    readiness_updated = Signal(object)
    mail_headers_ready = Signal(object)
    sms_send_finished = Signal(str, bool, str)
    # Closures posted from the asyncio thread. Queued onto the Qt thread the
    # same way utterance_settled is — QTimer.singleShot from that thread is
    # not, which left the calendar tile on syncing… / sync failed after Google
    # had already returned 200.
    _ui_call = Signal(object)

    def __init__(
        self,
        config: dict[str, Any],
        bridge: BusBridge,
        loop: asyncio.AbstractEventLoop,
        bus: EventBus,
        voice: VoiceService | None = None,
        *,
        store: MemoryStore | None = None,
        restore_session_id: str | None = None,
        indexer: MemoryIndexer | None = None,
        router: ModelRouter | None = None,
    ) -> None:
        super().__init__()
        self._construct_shell(
            config,
            bridge,
            loop,
            bus,
            voice,
            store=store,
            restore_session_id=restore_session_id,
            indexer=indexer,
            router=router,
        )
