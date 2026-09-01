from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QIcon,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QRegion,
)
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QMainWindow,
    QMenu,
    QSystemTrayIcon,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from arelis.core.bus import EventBus, bind_app_bus
from arelis.core.events import Event, EventType
from arelis.desk import DeskStore
from arelis.llm.router import ModelRouter
from arelis.memory import MemoryIndexer, MemoryStore
from arelis.notify import NotificationCenter
from arelis.paths import app_icon_path
from arelis.presence.inbound_runtime import InboundRuntime
from arelis.presence.ipc_client import IpcClient
from arelis.presence.ipc_server import IpcServer
from arelis.presence.pending_confirms import (
    PendingConfirm,
    PendingConfirmStore,
    pending_confirms_path,
)
from arelis.presence.readiness import ChipLevel, probe_readiness
from arelis.sms_auto_reply import SmsAutoReply
from arelis.sms_inbound import (
    InboundSms,
    InboundSmsWatcher,
    floor_is_busy,
)
from arelis.sms_ingest import InboundIngestServer
from arelis.spatial.depth import DepthBank
from arelis.spatial.scene import (
    REACH_DEFAULT,
    WorldScene,
    clamp_reach,
)
from arelis.spatial.verbs import (
    PhysicsAct,
)
from arelis.ui.calendar_window import CalendarWindow
from arelis.ui.chrome import TitleBar
from arelis.ui.confirm_host import emit_restored_confirm
from arelis.ui.contacts_inbox import ContactsInboxWindow
from arelis.ui.dock_surface import apply_dock_chrome, apply_dock_surface
from arelis.ui.event_host import dispatch_event
from arelis.ui.filament_desk import FilamentDesk
from arelis.ui.filament_field import (
    FilamentChatWindow,
    FilamentField,
    FilamentFloatBar,
    clamp_filament_span,
)
from arelis.ui.filament_tile import (
    load_opacities,
    load_tile_origins,
    load_tile_sizes,
)
from arelis.ui.foreground import flash_taskbar, process_owns_foreground
from arelis.ui.glass import GlassFrame, advance_rim_pulse, seal_tool_window
from arelis.ui.glass_dock import GlassDockWidget
from arelis.ui.hands_host import on_hands_chip, park_hands, resume_hands
from arelis.ui.history_host import (
    build_rooms_menu,
    enter_room_from_menu,
    request_session_load,
    show_rooms_menu,
)
from arelis.ui.host_bind import apply_startup_hosts, bind_window_hosts
from arelis.ui.idle_host import (
    note_engagement,
    sync_idle_mode,
    wake_from_away_rest,
)
from arelis.ui.launch import (  # noqa: F401
    _drain_event_loop,
    _raise_running_instance,
    _second_launch,
    force_windows_qt_platform,
    run_ui,
)
from arelis.ui.layout_store import (
    clamp_away_rest_min,
    load_recent_workspace_files,
    load_ui_prefs,
    restore_window_layout,
    save_window_layout,
)
from arelis.ui.notify_host import (
    on_notify_unread,
)
from arelis.ui.notify_inbox import NotificationsInboxWindow
from arelis.ui.panels import (
    CalendarPanel,
    CameraPanel,
    ContactsPanel,
    ConversationStage,
    HistoryPanel,
    InstrumentPanel,
    NotificationsPanel,
    ThinkingPanel,
    WorkspacePanel,
)
from arelis.ui.readiness_strip import ReadinessStrip
from arelis.ui.scale import default_window_size
from arelis.ui.settings_host import (
    apply_always_on_top,
    apply_chat_font_scale,
    nudge_chat_font,
    open_settings,
    toggle_always_on_top,
    toggle_fullscreen,
)
from arelis.ui.shortcuts import ShortcutsSheet
from arelis.ui.sms_chat import SmsChatRegistry
from arelis.ui.sms_host import (
    flush_held_inbound,
    operator_send_sms,
)
from arelis.ui.spatial_hands import SpatialHands
from arelis.ui.stage import StageBackground, paint_atmosphere
from arelis.ui.status_copy import (
    THINKING_STATUS,
    WARMING_STATUS,
)
from arelis.ui.surface_report import log_report
from arelis.ui.theme import (
    GLASS,
    THEME_CHOICES,
    active_theme,
    apply_theme,
    stylesheet,
    theme_from_config,
)
from arelis.ui.voice_host import (
    stop_speech,
    voice_restart_notices,  # noqa: F401 — tests import this from app
    )
from arelis.ui.window_docks import (
    bind_docks,
    on_dock_visibility,
    reveal_dock,
    sanitize_floating_docks,
    stack_left_instruments,
    sync_panel_margins,
    toggle_calendar,
    toggle_camera,
    toggle_contacts,
    toggle_history,
    toggle_notifications,
    toggle_thinking,
    toggle_workspace,
)
from arelis.ui.window_resize import (
    cursor_for_hit,
    enable_win32_resize_frame,
    handle_native_resize,
    hit_test_resize,
    invalidate_window_surface,
    release_native_children,
    try_system_resize,
)
from arelis.ui.workspace_host import (
    refresh_desk,
)
from arelis.ui.world_host import (
    apply_physics_act,
    apply_physics_verb,
    apply_tile,
    attach_world,
    bind_world,
    hide_and_reset_world,
    open_world,
    toggle_world,
    try_physics_verb,
    world_available,
)
from arelis.voice import VoiceService
from arelis.workspace import WorkspaceRoots

log = logging.getLogger(__name__)

_WINDOW_RADIUS = int(GLASS["radius"])

# If a turn somehow ends without a terminal event, re-enable the composer
# rather than leaving the user with a dead window. The orchestrator guarantees
# ASSISTANT_DONE or ERROR, so reaching this is a bug, but a desktop app should
# not need restarting to recover from one.
_BUSY_WATCHDOG_MS = 8000
# One amber hairline on the thinking plate after a click, then rest.
_THINK_PULSE_MS = 600

# One physical Ctrl+M / Ctrl+Shift+M can be delivered twice when the toggle
# reparents the composer mid-press. Longer than that echo, shorter than a
# deliberate second chord.
_VOICE_HOTKEY_ECHO_S = 0.12


def _hide_dock_title(dock: QDockWidget) -> None:
    """Zero-height Qt title always; in-panel chrome lives in InstrumentPanel.

    Docked: InstrumentPanel header is the drag/undock handle. Floating: frameless
    glass window with in-panel min/max/close matching the main Arelis shell.
    """
    dock.setFeatures(
        QDockWidget.DockWidgetFeature.DockWidgetMovable
        | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        | QDockWidget.DockWidgetFeature.DockWidgetClosable
    )
    apply_dock_chrome(dock, dock.isFloating())
    dock.topLevelChanged.connect(
        lambda floating, d=dock: apply_dock_chrome(d, bool(floating))
    )


# Both names predate arelis.ui.dock_surface and are kept for the tray-restore
# verify helper. Surface and chrome live in one module now; see the note there
# on why a floating dock must never be a translucent HWND.
def _glassify_floating_dock(dock: QDockWidget) -> None:
    apply_dock_surface(dock, True)


def _solidify_floating_dock(dock: QDockWidget) -> None:
    apply_dock_surface(dock, True)


def _apply_floating_dock_chrome(dock: QDockWidget, floating: bool) -> None:
    apply_dock_chrome(dock, floating)


# Glass panel spacing: outer window edge and inter-panel gutters stay equal.
# Each neighbor contributes _PANEL_HALF so the visible gap is 2 * HALF = OUTER.
_PANEL_OUTER = 12
_PANEL_HALF = 6
_PANEL_TOP = 12
_PANEL_BOTTOM = 14


def _dock_shell(body: QWidget, margins: tuple[int, int, int, int]) -> QWidget:
    """Inset dock glass to match the central conversation stage.

    Surface attributes are deliberately absent — ``apply_dock_surface`` sets them
    for the whole subtree once ``setWidget`` has attached this shell.
    """
    shell = QWidget()
    layout = QVBoxLayout(shell)
    layout.setContentsMargins(*margins)
    layout.setSpacing(0)
    layout.addWidget(body)
    return shell


def _set_shell_margins(shell: QWidget | None, margins: tuple[int, int, int, int]) -> None:
    if shell is None:
        return
    layout = shell.layout()
    if layout is not None:
        layout.setContentsMargins(*margins)


class BusBridge(QObject):
    """Marshal bus events onto the Qt main thread."""

    event_arrived = Signal(object)

    def feed(self, event: Event) -> None:
        self.event_arrived.emit(event)


class ArelisWindow(QMainWindow):
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
        # Set before anything can schedule a deferred callback. Every one of them
        # goes through _later, which drops rather than delivers once this is true.
        self._disposed = False
        self.config = config
        self.bridge = bridge
        self.loop = loop
        self.bus = bus
        bind_app_bus(bus)
        self.voice = voice
        self.store = store
        self.indexer = indexer
        self.router = router
        self._restore_session_id = restore_session_id
        self.workspace_roots: WorkspaceRoots = (
            config.get("_workspace") or WorkspaceRoots.from_config(config)
        )
        raw_desk = config.get("_desk")
        self.desk = raw_desk if isinstance(raw_desk, DeskStore) else DeskStore()
        self.config["_desk"] = self.desk
        ui_cfg = config.get("ui", {})
        self._atmosphere_phase = 0.0
        self.setWindowTitle(ui_cfg.get("window_title", "Arelis"))
        icon_path = app_icon_path()
        if icon_path.is_file():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setDockNestingEnabled(True)
        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.AllowNestedDocks
        )
        apply_theme(theme_from_config(config))
        self.setStyleSheet(stylesheet())
        # Native Windows chrome removed — custom glass title bar
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        # Opaque HWND. Translucency here made Windows a layered window; the OS
        # kept the last bitmap across a dock resize, which is the offset orbit
        # after tray-quit + a restored float. Corners are a mask, not alpha.
        seal_tool_window(self)
        self.menuBar().hide()

        self.title_bar = TitleBar()
        self.readiness_strip = ReadinessStrip()
        chrome_stack = QWidget()
        chrome_stack.setObjectName("ChromeStack")
        self._chrome_stack = chrome_stack
        chrome_layout = QVBoxLayout(chrome_stack)
        chrome_layout.setContentsMargins(0, 0, 0, 0)
        chrome_layout.setSpacing(0)
        chrome_layout.addWidget(self.title_bar)
        chrome_layout.addWidget(self.readiness_strip)
        self.chrome_bar = QToolBar()
        self.chrome_bar.setObjectName("ChromeToolBar")
        self.chrome_bar.setMovable(False)
        self.chrome_bar.setFloatable(False)
        self.chrome_bar.setAllowedAreas(Qt.ToolBarArea.TopToolBarArea)
        self.chrome_bar.addWidget(chrome_stack)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.chrome_bar)
        self.title_bar.title_menu_requested.connect(self._show_title_menu)
        self.title_bar.view_menu_requested.connect(self._show_view_menu)
        self.readiness_updated.connect(self.readiness_strip.apply)

        # Central host (transparent — atmosphere painted full-bleed on the window)
        self.stage = StageBackground()
        self.setCentralWidget(self.stage)
        self._stage_layout = QVBoxLayout(self.stage)
        # Margins synced with docks via _sync_panel_margins (even gutters).
        self._stage_layout.setContentsMargins(
            _PANEL_OUTER, _PANEL_TOP, _PANEL_OUTER, _PANEL_BOTTOM
        )
        self._stage_layout.setSpacing(0)

        default_role = config.get("router", {}).get("default_role", "fast")
        self.conversation = ConversationStage(default_role=default_role)
        self.chat = self.conversation.chat
        self.chat.progress_clicked.connect(self._on_thinking_status_clicked)
        self._stage_layout.addWidget(self.conversation, stretch=1)
        self._filament = FilamentField()
        self._filament_parked: dict[str, Any] | None = None
        self._filament_chrome_peek = False
        self._filament_hiding = False
        self._filament_chat_open = False
        self._filament_woken = False
        self._filament_span = clamp_filament_span((config.get("ui") or {}).get("filament_span", 1))
        self._filament_home: QRect | None = None
        self._filament_opacity = load_opacities(config)
        self._filament_tile_sizes = load_tile_sizes(config)
        self._filament_tile_pos = load_tile_origins(config)
        self._filament_dock_areas: dict[str, object] | None = None
        self._filament_floats = FilamentFloatBar(self._filament, self.conversation)
        self._filament_floats.hide()
        self._hands_chip = bool((config.get("ui") or {}).get("hands_chip", False))
        self._filament_chat_tile = FilamentChatWindow(self)
        self._filament_chat_tile.hide()
        self.filament = FilamentDesk(self)
        self.conversation.setMouseTracking(True)

        # Dockable instruments — full glass bodies, no broken native title chrome
        self.thinking = ThinkingPanel()
        self.workspace = WorkspacePanel()
        self.history = HistoryPanel()
        self.contacts = ContactsPanel()
        self.notifications = NotificationsPanel()
        self.notify_center = NotificationCenter(config)
        self.sms_chats = SmsChatRegistry(self)
        self.camera = CameraPanel()
        self.spatial = SpatialHands(self)
        self.spatial.hint.connect(self.camera._set_hint)
        self.spatial.preview_ready.connect(self.camera.set_preview)
        self.calendar = CalendarPanel(memory=self.store)
        self.workspace.set_projects(
            self.workspace_roots.names(),
            self.workspace_roots.active,
            paths={r.name: str(r.path) for r in self.workspace_roots.roots},
        )
        self.workspace.set_recent(load_recent_workspace_files())
        refresh_desk(self)
        self.think_host = InstrumentPanel("thinking", self.thinking)
        self.work_host = InstrumentPanel("workspace", self.workspace)
        self.history_host = InstrumentPanel("history", self.history)
        self.camera_host = InstrumentPanel("camera", self.camera)
        self.sms_watcher: InboundSmsWatcher | None = None
        self.sms_ingest: InboundIngestServer | None = None
        self.sms_auto_reply: SmsAutoReply | None = None
        self.inbound_runtime: InboundRuntime | None = None
        self.ipc_client: IpcClient | None = None
        # Only one of these is ever set: attached to a core we are its client,
        # and running alone we are the server a second launch talks to.
        self.ipc_server: IpcServer | None = None
        presence_cfg = self.config.get("presence") or {}
        self._close_to_tray = bool(presence_cfg.get("close_to_tray", True))
        ui_prefs = load_ui_prefs()
        self._always_on_top = bool(ui_prefs.get("always_on_top", False))
        self._chat_font_scale = float(ui_prefs.get("chat_font_scale", 1.0))
        self._world_reach = clamp_reach(ui_prefs.get("world_reach", REACH_DEFAULT))
        self._away_rest = bool(ui_prefs.get("away_rest", False))
        self._away_rest_min = clamp_away_rest_min(ui_prefs.get("away_rest_min", 45))
        self._away_resting = False
        self._away_hidden: dict[str, bool] = {}
        self._force_quit = False
        # What the window looked like when it went to the tray. showNormal() on
        # the way back would answer "not maximized" regardless, which is both the
        # wrong window and the reason a restore used to flash two of them.
        self._tray_window_state = Qt.WindowState.WindowNoState
        self._tray: QSystemTrayIcon | None = None
        self._pending_store = PendingConfirmStore(pending_confirms_path(self.config))
        self._pending_queue: list[PendingConfirm] = []
        self._restoring_confirm_ids: set[str] = set()
        self._ignore_cancel_echo = False
        # Survives thinking.clear() on session restore so a wiped STATUS line
        # cannot hide "ingest is down / needs token".
        self._inbound_banner: str = ""

        # The four dock object names below are not styling hooks — no QSS rule
        # targets them. QMainWindow.saveState() identifies docks by object name,
        # so they are what layout_store writes into ui_layout.ini and matches on
        # the way back. Drop one and that dock silently stops coming back where
        # it was left, days later, with nothing to connect it to.
        self.think_dock = GlassDockWidget("thinking", self)
        self.think_dock.setObjectName("ThinkingDock")
        self._think_shell = _dock_shell(
            self.think_host,
            (_PANEL_HALF, _PANEL_TOP, _PANEL_OUTER, _PANEL_BOTTOM),
        )
        self.think_dock.setWidget(self._think_shell)
        # After setWidget, so the first surface pass reaches the shell and panel.
        _hide_dock_title(self.think_dock)
        self.think_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.think_dock)

        self.work_dock = GlassDockWidget("workspace", self)
        self.work_dock.setObjectName("WorkspaceDock")
        self._work_shell = _dock_shell(
            self.work_host,
            (_PANEL_OUTER, _PANEL_HALF, _PANEL_OUTER, _PANEL_BOTTOM),
        )
        self.work_dock.setWidget(self._work_shell)
        _hide_dock_title(self.work_dock)
        self.work_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.work_dock)

        self.history_dock = GlassDockWidget("history", self)
        self.history_dock.setObjectName("HistoryDock")
        self._history_shell = _dock_shell(
            self.history_host,
            (_PANEL_OUTER, _PANEL_TOP, _PANEL_HALF, _PANEL_BOTTOM),
        )
        self.history_dock.setWidget(self._history_shell)
        _hide_dock_title(self.history_dock)
        self.history_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.history_dock)

        self.camera_dock = GlassDockWidget("camera", self)
        self.camera_dock.setObjectName("CameraDock")
        self._camera_shell = _dock_shell(
            self.camera_host,
            (_PANEL_OUTER, _PANEL_TOP, _PANEL_HALF, _PANEL_BOTTOM),
        )
        self.camera_dock.setWidget(self._camera_shell)
        _hide_dock_title(self.camera_dock)
        self.camera_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.camera_dock)
        self._stacking_left = False

        # Keep instruments readable while the OS live-resizes the frameless shell.
        # Without mins, QMainWindow will crush side docks to a few pixels.
        self._dock_min_width = 220
        for dock in (
            self.think_dock,
            self.history_dock,
            self.work_dock,
            self.camera_dock,
        ):
            dock.setMinimumWidth(self._dock_min_width)
        self.work_dock.setMinimumHeight(160)
        self.camera_dock.setMinimumHeight(200)
        self.stage.setMinimumWidth(420)
        self.setMinimumSize(960, 560)

        # Rebuild the round window mask only after resize settles — applying it
        # on every resizeEvent flickers badly and can scramble dock geometry.
        self._mask_timer = QTimer(self)
        self._mask_timer.setSingleShot(True)
        self._mask_timer.setInterval(90)
        self._mask_timer.timeout.connect(self._on_resize_settled)

        # Defaults before restore — chat-only until the user or an event opens
        # an instrument. Saved layout still wins after the first run. Size is
        # logical pixels; fit_window_size shrinks 1440×900 onto a 1080p desk
        # and leaves 4K-at-150% alone (that screen is already ~1440 logical).
        opening = default_window_size(self.config)
        self.resize(opening)
        self.think_dock.resize(320, 600)
        self.history_dock.resize(280, 600)
        self._apply_calm_instrument_defaults()

        restored = restore_window_layout(self, opening)
        if not restored:
            self._apply_calm_instrument_defaults()
        # Seal restored floats now, before the first show. Do not redock them
        # after paint — that shrink used to leave a second orbit on the right.
        self._sanitize_floating_docks()
        self._stack_left_instruments()
        self._later(0, self._clamp_dock_widths)
        self._later(0, self._sync_panel_margins)
        self._later(0, self._stack_left_instruments)
        self._later(250, self._stack_left_instruments)

        self.notify_inbox = NotificationsInboxWindow(self.notifications, self)
        self.notify_inbox.hide()
        self.contacts_inbox = ContactsInboxWindow(self.contacts, self)
        self.contacts_inbox.hide()
        self.calendar_window = CalendarWindow(self.calendar, self)
        self.calendar_window.hide()
        self._calendar_placed = False
        self.world_scene = WorldScene()
        self.world_depth = DepthBank()
        self.spatial.scene_log = self.world_scene.to_log
        self._closed_off: dict[str, tuple[float, float]] = {}
        self.world_window = attach_world(self.world_scene, self)
        self._world_placed = False
        self.camera.set_reach(self._world_reach)

        self._build_view_actions()
        self._voice_hotkey_at = 0.0
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        apply_always_on_top(self, self._always_on_top, persist=False)
        apply_chat_font_scale(self, self._chat_font_scale, persist=False)
        self.conversation.submitted.connect(self._on_submit)
        self.chat.again_requested.connect(self._on_again)
        self.conversation.attach_errors.connect(self._on_attach_errors)
        self.conversation.stop_requested.connect(self._on_stop)
        self.conversation.stop_declined.connect(self._on_stop_declined)
        self.conversation.pause_requested.connect(self._on_drive_pause)
        self.conversation.resume_requested.connect(self._on_drive_resume)
        self.conversation.confirm_decided.connect(self._on_confirm_decided)
        # Armed paths for the two press-again gates that guard unsaved work in
        # the editor: discarding it by opening over it, and overwriting a file
        # that changed on disk while it sat open.
        self._workspace_discard_armed = ""
        self._workspace_overwrite_armed = ""
        self._workspace_tool_args: dict[str, Any] = {}
        self.workspace.project_changed.connect(self._on_project_changed)
        self.chat.desk_requested.connect(self._keep_file_on_desk)
        self.contacts_inbox.closed.connect(self._on_contacts_inbox_closed)
        self._ui_call.connect(self._run_ui_call)

        self._assistant_streaming = False
        self._turn_busy = False
        self._mobile_foreign = False
        self._drive_session = False
        self._readiness_snap = None
        self._idle_ghosts: list[tuple[str, str]] = []
        self._away_timer = QTimer(self)
        self._away_timer.setSingleShot(True)
        self._held_inbound: list[InboundSms] = []
        self._job_t0: float | None = None
        self._job_name = ""
        self._mail_poll_inflight = False
        self._mail_poll_at = 0.0
        # Last spoken state per background poller, plus fail/ok streaks so a
        # one-shot DNS/timeout blip does not print stopped/working/stopped.
        self._poll_state: dict[str, str] = {}
        self._poll_fail_streak: dict[str, int] = {}
        self._poll_ok_streak: dict[str, int] = {}
        self._poll_spoken: dict[str, str] = {}
        self._current_role = default_role
        self._current_model = config.get("models", {}).get(default_role, "")
        self._busy_watchdog = QTimer(self)
        self._busy_watchdog.setSingleShot(True)
        self._busy_watchdog.timeout.connect(self._on_busy_watchdog)
        self._think_pulse_timer = QTimer(self)
        self._think_pulse_timer.setSingleShot(True)
        self._think_pulse_timer.setInterval(_THINK_PULSE_MS)
        self._think_pulse_timer.timeout.connect(self._on_think_pulse_done)

        # Embed archived messages between turns only. Mid-turn would load nomic
        # and risk evicting the chat model on a 12GB card.
        self._index_timer = QTimer(self)
        self._index_timer.setInterval(30_000)
        self._index_timer.timeout.connect(self._on_index_tick)
        if self.indexer is not None:
            self._index_timer.start()

        # Soft readiness refresh — Ollama + local integrations under the title bar.
        self._readiness_timer = QTimer(self)
        self._readiness_timer.setInterval(30_000)
        self._readiness_timer.timeout.connect(self._schedule_readiness_probe)
        self._readiness_timer.start()

        notify_cfg = (config.get("ui") or {}).get("notifications") or {}
        self._notify_timer = QTimer(self)
        self._notify_timer.setInterval(
            max(15_000, int(float(notify_cfg.get("poll_s") or 30) * 1000))
        )
        self._notify_timer.start()
        self._calendar_sync_inflight = False
        self._calendar_sync_timeout_ms = 20_000
        self._calendar_sync_timer = QTimer(self)
        self._calendar_sync_timer.setInterval(300_000)
        self._calendar_sync_watchdog = QTimer(self)
        self._calendar_sync_watchdog.setSingleShot(True)
        self._job_tick = QTimer(self)
        self._job_tick.setInterval(1000)
        bind_window_hosts(self)
        bind_docks(self)
        bind_world(self)
        self.filament.bind()
        apply_startup_hosts(self)

        # Slow grain drift — paused while minimized.
        self._atmosphere_timer = QTimer(self)
        self._atmosphere_timer.setInterval(100)
        self._atmosphere_timer.timeout.connect(self._tick_atmosphere)
        self._atmosphere_timer.start()
        self._sync_filament_face()

        self._later(0, self._schedule_readiness_probe)
        self._later(80, self.conversation.focus_input)
        # The duplicate-paint bug is on screen from the first frame, so a dump
        # once the window has settled catches it. See surface_report for why
        # these three lists are the ones worth printing.
        self._later(4000, lambda: log_report(self, tag="settled"))
        if self._restore_session_id:
            # Bus is already running on the background thread by the time the
            # window is shown; a zero-delay shot waits one event-loop pass so
            # the bridge is connected before SESSION_LOADED comes back.
            self._later(
                0, lambda: request_session_load(self, self._restore_session_id or "")
            )

    def _schedule_readiness_probe(self) -> None:
        """Refresh the readiness strip without blocking the UI thread."""
        if not self.loop.is_running():
            return

        async def _run() -> None:
            try:
                snap = await probe_readiness(self.config, router=self.router)
            except Exception as exc:
                log.info("Readiness probe failed: %s", exc)
                from arelis.presence.readiness import ReadinessChip, ReadinessSnapshot

                snap = ReadinessSnapshot(
                    chips=tuple(
                        ReadinessChip(
                            key=key,
                            label=label,
                            status=ChipLevel.OFF,
                            detail=f"Probe error: {exc}",
                        )
                        for key, label in (
                            ("ollama", "Ollama"),
                            ("models", "Models"),
                            ("role", "Model"),
                            ("confirm", "Allow gates"),
                            ("calendar", "Calendar"),
                            ("sms", "SMS"),
                            ("mail", "Mail"),
                            ("embed", "Embed"),
                        )
                    )
                )
            self.readiness_updated.emit(snap)

        asyncio.run_coroutine_threadsafe(_run(), self.loop)

    def _apply_calm_instrument_defaults(self) -> None:
        """Hide instruments for a conversation-first composition."""
        ui_cfg = self.config.get("ui", {})
        if not ui_cfg.get("thinking_open", False):
            self.think_dock.hide()
        if not ui_cfg.get("workspace_open", False):
            self.work_dock.hide()
        if not ui_cfg.get("camera_open", False):
            self.camera_dock.hide()
        self.history_dock.hide()
        cal = getattr(self, "calendar_window", None)
        if cal is not None:
            cal.hide()

    def _reveal_dock(
        self,
        dock: QDockWidget,
        action: QAction | None = None,
        *,
        asked: bool = False,
    ) -> None:
        return reveal_dock(self, dock, action, asked=asked)

    def _on_thinking_status_clicked(self) -> None:
        """The status line is a control: open Thinking, or pulse that plate."""
        # isVisible() is false whenever the parent window is hidden (tests, tray),
        # so the open/closed latch is isHidden() — same as the rest of the UI.
        if not self.think_dock.isHidden():
            self._pulse_thinking_instrument()
            return
        self._reveal_dock(self.think_dock, self.act_thinking, asked=True)

    def _pulse_thinking_instrument(self) -> None:
        """One short amber hairline on the thinking plate, then rest."""
        self.think_host.set_attention(True, ember=True)
        self._think_pulse_timer.start()

    def _on_think_pulse_done(self) -> None:
        self.think_host.set_attention(False)

    def _atmosphere_glass_frames(self) -> list[GlassFrame]:
        """Plates the 10 Hz tick may invalidate.

        Conversation is type in the void. A 10 Hz repaint on that
        translucent surface — or on RoomStrip / DriveStrip sitting on it —
        is the duplicate-orbit / ghost-tick path. Companion HWNDs
        (world, calendar) have their own timers.
        """
        conversation = self.conversation
        frames = []
        for frame in self.findChildren(GlassFrame):
            if frame is conversation or conversation.isAncestorOf(frame):
                continue
            if frame.window() is not self:
                continue
            if frame.isHidden():
                continue
            if frame.has_attention or getattr(frame, "_pulse_rim", False):
                frames.append(frame)
            elif getattr(frame, "_fill_alpha", 0) > 4:
                frames.append(frame)
        return frames

    def _tick_atmosphere(self) -> None:
        if self.isMinimized():
            return
        self._atmosphere_phase = (self._atmosphere_phase + 0.012) % 6.283185307179586
        # Slow grain drift. Rim on plates is a static hairline, not a pulse circus.
        advance_rim_pulse(0.1)
        if active_theme() == "filament":
            camera = getattr(self, "camera_dock", None)
            live = camera is not None and camera.isVisible()
            self._filament.set_load("camera" if live else "")
            ms = self._filament.atmosphere_ms()
            self._atmosphere_timer.setInterval(ms)
            self._filament.set_state(self._filament_weather())
            self._filament.tick(ms / 1000.0)
            self._place_filament_floats(reshape=False)
            self.update(self._filament.dirty_rect(self.rect()))
            return
        self._atmosphere_timer.setInterval(100)
        self.update()
        for frame in self._atmosphere_glass_frames():
            frame.update()


    def _build_view_actions(self) -> None:
        self.act_thinking = QAction("thinking", self)
        self.act_thinking.setCheckable(True)
        self.act_thinking.setChecked(self.think_dock.isVisible())
        self.act_thinking.setShortcut(QKeySequence("Ctrl+1"))
        self.act_thinking.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_thinking.triggered.connect(self._toggle_thinking)
        self.addAction(self.act_thinking)

        self.act_workspace = QAction("workspace", self)
        self.act_workspace.setCheckable(True)
        self.act_workspace.setChecked(self.work_dock.isVisible())
        self.act_workspace.setShortcut(QKeySequence("Ctrl+2"))
        self.act_workspace.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_workspace.triggered.connect(self._toggle_workspace)
        self.addAction(self.act_workspace)

        self.act_history = QAction("history", self)
        self.act_history.setCheckable(True)
        self.act_history.setChecked(self.history_dock.isVisible())
        self.act_history.setShortcut(QKeySequence("Ctrl+3"))
        self.act_history.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_history.triggered.connect(self._toggle_history)
        self.addAction(self.act_history)

        self.act_notifications = QAction("notifications", self)
        self.act_notifications.setCheckable(True)
        self.act_notifications.setChecked(self.notify_inbox.isVisible())
        self.act_notifications.setShortcut(QKeySequence("Ctrl+4"))
        self.act_notifications.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_notifications.triggered.connect(self._toggle_notifications)
        self.addAction(self.act_notifications)
        on_notify_unread(self, self.notify_center.unread_count())

        self.act_camera = QAction("camera", self)
        self.act_camera.setCheckable(True)
        self.act_camera.setChecked(self.camera_dock.isVisible())
        self.act_camera.setShortcut(QKeySequence("Ctrl+5"))
        self.act_camera.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_camera.triggered.connect(self._toggle_camera)
        self.addAction(self.act_camera)

        self.act_contacts = QAction("contacts", self)
        self.act_contacts.setCheckable(True)
        self.act_contacts.setChecked(self.contacts_inbox.isVisible())
        self.act_contacts.setShortcut(QKeySequence("Ctrl+6"))
        self.act_contacts.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_contacts.triggered.connect(self._toggle_contacts)
        self.addAction(self.act_contacts)

        self.act_calendar = QAction("calendar", self)
        self.act_calendar.setCheckable(True)
        self.act_calendar.setChecked(not self.calendar_window.isHidden())
        self.act_calendar.setShortcut(QKeySequence("Ctrl+7"))
        self.act_calendar.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_calendar.triggered.connect(self._toggle_calendar)
        self.addAction(self.act_calendar)

        self.act_world = QAction("Reality", self)
        self.act_world.setCheckable(True)
        self.act_world.setChecked(False)
        self.act_world.setShortcut(QKeySequence("Ctrl+8"))
        self.act_world.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_world.triggered.connect(self._toggle_world)
        self.addAction(self.act_world)

        self.act_reset = QAction("reset layout", self)
        self.act_reset.triggered.connect(self._reset_layout)
        self.addAction(self.act_reset)

        self.act_settings = QAction("settings…", self)
        self.act_settings.setShortcut(QKeySequence("Ctrl+,"))
        self.act_settings.triggered.connect(lambda: open_settings(self))
        self.addAction(self.act_settings)

        self.act_always_on_top = QAction("always on top", self)
        self.act_always_on_top.setCheckable(True)
        self.act_always_on_top.setChecked(self._always_on_top)
        self.act_always_on_top.triggered.connect(
            lambda checked: toggle_always_on_top(self, checked)
        )
        self.addAction(self.act_always_on_top)

        self.act_fullscreen = QAction("fullscreen", self)
        self.act_fullscreen.setShortcut(QKeySequence(Qt.Key.Key_F11))
        self.act_fullscreen.triggered.connect(self._toggle_fullscreen)
        self.addAction(self.act_fullscreen)

        self.act_font_larger = QAction("larger text", self)
        self.act_font_larger.setShortcuts(
            [QKeySequence("Ctrl+="), QKeySequence("Ctrl++")]
        )
        self.act_font_larger.triggered.connect(lambda: nudge_chat_font(self, 0.1))
        self.addAction(self.act_font_larger)

        self.act_font_smaller = QAction("smaller text", self)
        self.act_font_smaller.setShortcut(QKeySequence("Ctrl+-"))
        self.act_font_smaller.triggered.connect(lambda: nudge_chat_font(self, -0.1))
        self.addAction(self.act_font_smaller)

        self.act_font_reset = QAction("reset text size", self)
        self.act_font_reset.setShortcut(QKeySequence("Ctrl+0"))
        self.act_font_reset.triggered.connect(
            lambda: apply_chat_font_scale(self, 1.0)
        )
        self.addAction(self.act_font_reset)

        self.act_notify_url = QAction("notify url…", self)
        self.act_notify_url.setToolTip("Show and copy the phone companion URL")
        self.act_notify_url.triggered.connect(lambda: open_settings(self, "Notify"))
        self.addAction(self.act_notify_url)

        self.act_shortcuts = QAction("shortcuts", self)
        self.act_shortcuts.setShortcut(QKeySequence(Qt.Key.Key_F1))
        self.act_shortcuts.triggered.connect(self._open_shortcuts)
        self.addAction(self.act_shortcuts)

        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        current = theme_from_config(self.config)
        for theme_id, label in THEME_CHOICES:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(theme_id == current)
            act.triggered.connect(
                lambda checked=False, tid=theme_id: self._choose_theme(tid, checked)
            )
            self._theme_group.addAction(act)
            self.addAction(act)
            self._theme_actions[theme_id] = act

        self.act_dictate = QAction("dictate", self)
        self.act_dictate.triggered.connect(self.conversation.toggle_dictate)
        self.addAction(self.act_dictate)

        self.act_conversation = QAction("conversation", self)
        self.act_conversation.triggered.connect(self.conversation.toggle_conversation)
        self.addAction(self.act_conversation)

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        """Ctrl+M / Ctrl+Shift+M must win over the idle composer and docks.

        Two event types carry one physical press. ShortcutOverride arrives
        first and is only claimed here, so no QAction and no focused editor
        gets the chord; KeyPress is the single place the mode is toggled.
        Toggling on both counted one press twice, and Windows repeats a held
        chord every few tens of milliseconds once the repeat delay expires, so
        the mode turned on and straight back off and the orbit looked dead.
        """
        et = event.type()
        if et == QEvent.Type.MouseButtonPress:
            note_engagement(self)
            return super().eventFilter(obj, event)
        if et == QEvent.Type.MouseMove:
            self._filament_on_mouse_move(event)
            return super().eventFilter(obj, event)
        if et not in {QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress}:
            return super().eventFilter(obj, event)
        if not isinstance(event, QKeyEvent) or not self._voice_hotkeys_allowed():
            return super().eventFilter(obj, event)
        if not self._is_voice_hotkey(event):
            return super().eventFilter(obj, event)
        event.accept()
        if et == QEvent.Type.KeyPress and not event.isAutoRepeat():
            self._fire_voice_hotkey(event)
        return True

    def _fire_voice_hotkey(self, event: QKeyEvent) -> None:
        # Reparenting the composer between the orbit and the workbench happens
        # inside the toggle and can re-deliver the same press. Anything this
        # close together is that echo, not a second deliberate chord, and the
        # window is short enough that a real double-tap still lands.
        now = time.monotonic()
        if now - self._voice_hotkey_at < _VOICE_HOTKEY_ECHO_S:
            return
        self._voice_hotkey_at = now
        note_engagement(self)
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.conversation.toggle_conversation()
        else:
            self.conversation.toggle_dictate()

    def _voice_hotkeys_allowed(self) -> bool:
        from arelis.ui.settings_dialog import SettingsDialog

        aw = QApplication.activeWindow()
        if aw is None:
            return False
        if isinstance(aw, SettingsDialog):
            return False
        if aw is self or self.isAncestorOf(aw):
            return True
        # World / calendar / inboxes are native windows. isAncestorOf is false
        # across windows even when we own them — conversation still lives here.
        parent = aw.parent() if aw is not None else None
        return parent is self

    def _is_voice_hotkey(self, event: QKeyEvent) -> bool:
        if event.key() != Qt.Key.Key_M:
            return False
        mods = event.modifiers()
        if not (mods & Qt.KeyboardModifier.ControlModifier):
            return False
        if mods & Qt.KeyboardModifier.AltModifier:
            return False
        return True

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if active_theme() == "filament":
            painter.setClipRegion(event.region())
            self._filament.paint(painter, self.rect())
            return
        path = QPainterPath()
        path.addRoundedRect(
            self.rect().adjusted(0, 0, -1, -1), _WINDOW_RADIUS, _WINDOW_RADIUS
        )
        painter.setClipPath(path)
        paint_atmosphere(painter, self.rect(), drift=self._atmosphere_phase)
        # Corner ticks live on ConversationStage so they don't cut the title bar.

    def event(self, event) -> bool:
        # Nothing between this window and the text paints a background: the
        # stage, the dock shells, the instrument plates at fill 0 and the panel
        # bodies are all transparent, and this paintEvent is the only thing that
        # lays down pixels. Qt repaints the smallest region it thinks changed,
        # so a widget that moves gets its new position painted while its old
        # position keeps the previous frame — a second history header 40px up, a
        # second orbit one dock-column to the right.
        #
        # A whole-window repaint on layout change is the answer rather than a
        # _flush_glass_surface call at each of the dozen places that can move a
        # widget, because the next one added would not know it had to call it.
        # update() coalesces into a single paint per frame.
        # Filament titles are child buttons — Qt already dirties their move
        # rects. Flushing 7680×1466 on every place() undoes the band update.
        if event.type() == QEvent.Type.LayoutRequest:
            if active_theme() == "filament":
                self.update(self._filament.dirty_rect(self.rect()))
            else:
                self.update()
        return super().event(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # Drop the mask while the user is dragging an edge — setMask every
        # pixel is expensive and was leaving docks stuck at crushed widths.
        if not self.isMaximized() and not self.isFullScreen():
            self.clearMask()
        self._mask_timer.start()
        self._sync_browser_anchor()
        # Floats follow the coil. Remask waits for _on_resize_settled —
        # reshape here put setMask back on every drag pixel.
        self._place_filament_floats(reshape=False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Frameless alone drops OS resize; re-add thick frame after the HWND exists.
        if not (self.isMaximized() or self.isFullScreen()):
            enable_win32_resize_frame(self)
        # QMainWindow will have promoted docks/toolbars to child HWNDs by now.
        # Those are the second paint of each panel, offset by the child's origin.
        release_native_children(self)
        self._apply_round_mask()
        self._clamp_dock_widths()
        self._sync_panel_margins()
        self._sync_chrome_state()
        self.setMouseTracking(True)
        self._sync_browser_anchor()
        sync_idle_mode(self)
        if active_theme() == "filament" and self._filament_parked is not None:
            self._later(0, self._filament_place_entity)

    def _sync_browser_anchor(self) -> None:
        """Park her Chrome on one desk. Never pass the 1/2/3 span as its size."""
        from arelis.browser.launch import set_arelis_anchor
        from arelis.ui.scale import available_work_area

        geo = self.geometry()
        home = getattr(self, "_filament_home", None)
        if (
            active_theme() == "filament"
            and home is not None
            and home.isValid()
            and home.width() > 80
        ):
            avail = home
        else:
            screen = self.screen()
            avail = screen.availableGeometry() if screen is not None else available_work_area(self)
        set_arelis_anchor(
            geo.x(),
            geo.y(),
            geo.width(),
            geo.height(),
            screen=(avail.x(), avail.y(), avail.width(), avail.height()),
        )

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            # Minimizing is the other way to take the glass off screen, and a
            # floating instrument is a top-level window that does not go down
            # with it. Left alone, the panel sits on the desktop with nothing
            # behind it — same orphan as close-to-tray, reached from the title bar.
            was_minimized = bool(
                event.oldState() & Qt.WindowState.WindowMinimized
            )
            if self.isMinimized():
                self._park_floating_docks()
                park_hands(self)
            elif was_minimized:
                self._unpark_floating_docks()
                resume_hands(self)
            self._sync_chrome_state()
            self._apply_round_mask()
            self._clamp_dock_widths()
            if not (self.isMaximized() or self.isFullScreen()):
                enable_win32_resize_frame(self)
            self._sync_notify_surface()

    def nativeEvent(self, eventType, message):
        passed = self._filament_native_hit(eventType, message)
        if passed is not None:
            return passed
        handled = handle_native_resize(self, eventType, message)
        if handled is not None:
            return handled
        return super().nativeEvent(eventType, message)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            if try_system_resize(self, event.globalPosition().toPoint()):
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        # Hover cursor when the pointer is over the window chrome edges.
        # (OS also sets cursors once WM_NCHITTEST returns HT* codes.)
        shape = cursor_for_hit(hit_test_resize(self))
        if shape is not None:
            self.setCursor(shape)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def _sync_chrome_state(self) -> None:
        self.title_bar.sync_window_state(self)

    def _on_resize_settled(self) -> None:
        self._apply_round_mask()
        self._clamp_dock_widths()
        self._flush_glass_surface()

    def _clamp_dock_widths(self) -> None:
        """Repair docks crushed by a bad saved layout or a mid-resize layout pass."""
        min_w = int(getattr(self, "_dock_min_width", 220))
        docks: list[QDockWidget] = []
        widths: list[int] = []
        for dock in (
            self.history_dock,
            self.think_dock,
            self.work_dock,
            self.camera_dock,
        ):
            if not dock.isVisible() or dock.isFloating():
                continue
            area = self.dockWidgetArea(dock)
            if area not in {
                Qt.DockWidgetArea.LeftDockWidgetArea,
                Qt.DockWidgetArea.RightDockWidgetArea,
            }:
                continue
            if dock.width() < min_w:
                docks.append(dock)
                widths.append(min_w)
        if docks:
            self.resizeDocks(docks, widths, Qt.Orientation.Horizontal)

    def _apply_round_mask(self) -> None:
        if active_theme() == "filament":
            self._filament_apply_shape()
            return
        if self.isMaximized() or self.isFullScreen():
            self.clearMask()
            return
        bounds = QRect(0, 0, self.width(), self.height()).adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(bounds, _WINDOW_RADIUS, _WINDOW_RADIUS)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _open_shortcuts(self) -> None:
        """Show the chord sheet, reusing the one window rather than stacking."""
        sheet = getattr(self, "_shortcuts_sheet", None)
        if sheet is None:
            sheet = ShortcutsSheet(self)
            self._shortcuts_sheet = sheet
        sheet.show()
        sheet.raise_()
        sheet.activateWindow()

    def _show_title_menu(self, anchor) -> None:
        if active_theme() == "filament":
            self._popup_filament_menu(anchor.mapToGlobal(QPoint(0, anchor.height())))
            return
        self._show_view_menu(anchor)

    def _show_view_menu(self, anchor) -> None:
        self._sync_view_checks()
        menu = QMenu(self)
        menu.addAction(self.act_thinking)
        menu.addAction(self.act_workspace)
        menu.addAction(self.act_history)
        menu.addAction(self.act_notifications)
        menu.addAction(self.act_camera)
        menu.addAction(self.act_contacts)
        menu.addAction(self.act_calendar)
        if world_available():
            menu.addAction(self.act_world)
        menu.addSeparator()
        menu.addAction(self.act_always_on_top)
        menu.addAction(self.act_fullscreen)
        themes = menu.addMenu("themes")
        for act in self._theme_actions.values():
            themes.addAction(act)
        menu.addSeparator()
        menu.addAction(self.act_shortcuts)
        menu.addAction(self.act_notify_url)
        menu.addAction(self.act_reset)
        # Settings lives on the title-bar button (and Ctrl+,), not in View.
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def contextMenuEvent(self, event) -> None:  # type: ignore[override]
        if active_theme() == "filament":
            self._popup_filament_menu(event.globalPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def _build_filament_menu(self):
        from arelis.ui.filament_desk import build_filament_menu
        return build_filament_menu(self)

    def _popup_filament_menu(self, global_pos) -> None:
        from arelis.ui.filament_desk import popup_filament_menu
        return popup_filament_menu(self, global_pos)

    def _show_rooms_menu(self, anchor) -> None:
        return show_rooms_menu(self, anchor)

    def _build_rooms_menu(self):
        return build_rooms_menu(self)

    def _enter_room_from_menu(self, room_id: str) -> None:
        return enter_room_from_menu(self, room_id)

    def _hang_up_conversation(self) -> None:
        """Leave hands-free talk. Wake stays on. The room does not change."""
        btn = self.conversation.conversation_btn
        if btn.isChecked():
            btn.setChecked(False)
        if self.voice_controller is not None:
            self.voice_controller.set_conversation(False)
        self.thinking.append("Listening for Hey Arelis.", kind="status")

    def _toggle_fullscreen(self) -> None:
        if active_theme() == "filament":
            if self.isFullScreen() or self.isMaximized():
                self.showNormal()
            self._filament_place_entity()
            return
        return toggle_fullscreen(self)

    def _toggle_thinking(self, checked: bool) -> None:
        return toggle_thinking(self, checked)

    def _toggle_workspace(self, checked: bool) -> None:
        return toggle_workspace(self, checked)

    def _toggle_history(self, checked: bool) -> None:
        return toggle_history(self, checked)

    def _toggle_notifications(self, checked: bool) -> None:
        return toggle_notifications(self, checked)

    def _toggle_camera(self, checked: bool) -> None:
        return toggle_camera(self, checked)

    def _toggle_contacts(self, checked: bool) -> None:
        return toggle_contacts(self, checked)

    def _toggle_calendar(self, checked: bool) -> None:
        return toggle_calendar(self, checked)

    def _open_world(self) -> None:
        return open_world(self)

    def _toggle_world(self, checked: bool, page: str = '', *, force: bool = False) -> None:
        return toggle_world(self, checked, page=page, force=force)

    def _hide_world(self) -> None:
        return hide_and_reset_world(self)

    def _try_physics_verb(self, text: str) -> bool:
        return try_physics_verb(self, text)

    def _apply_physics_verb(
        self,
        verb: str,
        *,
        name: str = '',
        flag: str = '',
        on: bool | None = None,
        page: str = '',
    ) -> None:
        return apply_physics_verb(self, verb, name=name, flag=flag, on=on, page=page)

    def _apply_physics_act(self, act: PhysicsAct) -> None:
        return apply_physics_act(self, act)

    def _touch_solar(self) -> None:
        from arelis.ui.world_host import touch_solar
        return touch_solar(self)

    def _apply_tile(self, name: str, *, show: bool, page: str = '') -> None:
        return apply_tile(self, name, show=show, page=page)

    def _run_ui_call(self, fn) -> None:
        if getattr(self, "_disposed", False) or getattr(self, "_force_quit", False):
            return
        if callable(fn):
            fn()

    def _on_contacts_inbox_closed(self) -> None:
        self.act_contacts.setChecked(False)
        sync_idle_mode(self)

    def _on_world_window_closed(self) -> None:
        from arelis.ui.world_host import on_world_window_closed
        return on_world_window_closed(self)

    def _on_hands_chip(self, on: bool) -> None:
        return on_hands_chip(self, on)

    def _sync_view_checks(self) -> None:
        """Keep View-menu checkmarks aligned with the docks that are actually up."""
        if not hasattr(self, "act_thinking"):
            return
        self.act_thinking.setChecked(self.think_dock.isVisible())
        self.act_workspace.setChecked(self.work_dock.isVisible())
        self.act_history.setChecked(self.history_dock.isVisible())
        self.act_notifications.setChecked(self.notify_inbox.isVisible())
        self.act_camera.setChecked(self.camera_dock.isVisible())
        if hasattr(self, "act_contacts"):
            self.act_contacts.setChecked(self.contacts_inbox.isVisible())
        if hasattr(self, "act_calendar"):
            self.act_calendar.setChecked(not self.calendar_window.isHidden())
        if hasattr(self, "act_world"):
            self.act_world.setChecked(not self.world_window.isHidden())
        self._sync_theme_checks()

    def _sync_theme_checks(self) -> None:
        from arelis.ui.theme import active_theme

        current = active_theme()
        for theme_id, act in getattr(self, "_theme_actions", {}).items():
            act.blockSignals(True)
            act.setChecked(theme_id == current)
            act.blockSignals(False)

    def _choose_theme(self, theme_id: str, checked: bool) -> None:
        if not checked:
            return
        from arelis.config import merge_local_config
        from arelis.ui.dialog import confirm
        from arelis.ui.settings_host import apply_window_theme

        if theme_id == "filament" and not (self.config.get("ui") or {}).get(
            "filament_ack"
        ):
            ok = confirm(
                self,
                "filament (testing)",
                "a test face. it wants a row of desks — three is the intended layout.",
                detail=(
                    "sodium is the app. filament is a checkout experiment for a "
                    "three-monitor desk; 1 and 2 still work. talk does not need a "
                    "chat tile. plates float — drag them. right-click for themes. "
                    "sodium is one click."
                ),
                confirm_text="enter filament",
                cancel_text="stay in sodium",
            )
            if not ok:
                self._sync_theme_checks()
                return
            self.config.setdefault("ui", {})["filament_ack"] = True
            merge_local_config({"ui": {"filament_ack": True}})
        apply_window_theme(self, theme_id, persist=True)
        self._sync_filament_face()
        self._sync_theme_checks()

    def _filament_weather(self) -> str:
        from arelis.ui.filament_desk import filament_weather
        return filament_weather(self)

    def _filament_can_claim_desk(self) -> bool:
        from arelis.ui.filament_desk import filament_can_claim_desk
        return filament_can_claim_desk(self)

    def _filament_apply_glass(self, on: bool) -> None:
        from arelis.ui.filament_desk import filament_apply_glass
        return filament_apply_glass(self, on)

    def _filament_pin_home(self):
        from arelis.ui.filament_desk import filament_pin_home
        return filament_pin_home(self)

    def _filament_set_span(self, n: int) -> None:
        from arelis.ui.filament_desk import filament_set_span
        return filament_set_span(self, n)

    def _filament_place_entity(self) -> None:
        from arelis.ui.filament_desk import filament_place_entity
        return filament_place_entity(self)

    def _filament_fill_home_desk(self, pinned) -> None:
        from arelis.ui.filament_desk import filament_fill_home_desk
        return filament_fill_home_desk(self, pinned)

    def _filament_is_spanned(self) -> bool:
        from arelis.ui.filament_desk import filament_is_spanned
        return filament_is_spanned(self)

    def _filament_toggle_span(self) -> None:
        from arelis.ui.filament_desk import filament_toggle_span
        return filament_toggle_span(self)

    def _filament_apply_shape(self) -> None:
        from arelis.ui.filament_desk import filament_apply_shape
        return filament_apply_shape(self)

    def _filament_place_chrome(self) -> None:
        from arelis.ui.filament_desk import filament_place_chrome
        return filament_place_chrome(self)

    def _filament_dock_chrome(self) -> None:
        from arelis.ui.filament_desk import filament_dock_chrome
        return filament_dock_chrome(self)

    def _filament_lock_tiles(self, on: bool) -> None:
        from arelis.ui.filament_desk import filament_lock_tiles
        return filament_lock_tiles(self, on)

    def _filament_extra_tiles(self):
        from arelis.ui.filament_desk import filament_extra_tiles
        return filament_extra_tiles(self)

    @staticmethod
    def _filament_plate_open(widget) -> bool:
        from arelis.ui.filament_desk import filament_plate_open
        return filament_plate_open(widget)

    def _filament_native_hit(self, event_type, message):
        from arelis.ui.filament_desk import filament_native_hit
        return filament_native_hit(self, event_type, message)

    def _filament_wants_click(self, global_pos) -> bool:
        from arelis.ui.filament_desk import filament_wants_click
        return filament_wants_click(self, global_pos)

    def _filament_on_mouse_move(self, event) -> None:
        from arelis.ui.filament_desk import filament_on_mouse_move
        return filament_on_mouse_move(self, event)

    def _filament_set_chrome_peek(self, on: bool) -> None:
        from arelis.ui.filament_desk import filament_set_chrome_peek
        return filament_set_chrome_peek(self, on)

    def _filament_enter_presence(self) -> None:
        from arelis.ui.filament_desk import filament_enter_presence
        return filament_enter_presence(self)

    def _filament_leave_presence(self) -> None:
        from arelis.ui.filament_desk import filament_leave_presence
        return filament_leave_presence(self)

    def _sync_filament_face(self) -> None:
        from arelis.ui.filament_desk import sync_filament_face
        return sync_filament_face(self)

    def _place_filament_floats(self, *, reshape: bool = True) -> None:
        from arelis.ui.filament_desk import place_filament_floats
        return place_filament_floats(self, reshape=reshape)

    def _filament_sync_tethers(self) -> None:
        from arelis.ui.filament_desk import filament_sync_tethers
        return filament_sync_tethers(self)

    def _on_filament_float(self, name: str) -> None:
        from arelis.ui.filament_desk import on_filament_float
        return on_filament_float(self, name)

    def _filament_open_reality(self) -> None:
        from arelis.ui.filament_desk import filament_open_reality
        return filament_open_reality(self)

    def _filament_refuse_dock(self, dock, name: str, floating: bool) -> None:
        from arelis.ui.filament_desk import filament_refuse_dock
        return filament_refuse_dock(self, dock, name, floating)

    def _filament_dress_tile(self, widget, name: str) -> None:
        from arelis.ui.filament_desk import filament_dress_tile
        return filament_dress_tile(self, widget, name)

    def _filament_present_tile(self, dock, name: str) -> None:
        from arelis.ui.filament_desk import filament_present_tile
        return filament_present_tile(self, dock, name)

    def _filament_place_near_title(self, widget, name: str) -> None:
        from arelis.ui.filament_desk import filament_place_near_title
        return filament_place_near_title(self, widget, name)

    def _filament_set_chat_open(self, on: bool) -> None:
        from arelis.ui.filament_desk import filament_set_chat_open
        return filament_set_chat_open(self, on)

    def _on_filament_chat_closed(self) -> None:
        from arelis.ui.filament_desk import on_filament_chat_closed
        return on_filament_chat_closed(self)

    def _filament_mount_chat(self) -> None:
        from arelis.ui.filament_desk import filament_mount_chat
        return filament_mount_chat(self)

    def _filament_unmount_chat(self) -> None:
        from arelis.ui.filament_desk import filament_unmount_chat
        return filament_unmount_chat(self)

    def _on_dock_visibility(self, visible: bool) -> None:
        return on_dock_visibility(self, visible)

    def _docked_in(self, dock, area):
        from arelis.ui.window_docks import docked_in
        return docked_in(self, dock, area)

    def _left_column_member(self, dock) -> bool:
        from arelis.ui.window_docks import left_column_member
        return left_column_member(self, dock)

    def _history_camera_tabbed(self) -> bool:
        from arelis.ui.window_docks import history_camera_tabbed
        return history_camera_tabbed(self)

    def _stack_left_instruments(self) -> None:
        return stack_left_instruments(self)

    def _sync_panel_margins(self) -> None:
        return sync_panel_margins(self)

    def _sanitize_floating_docks(self) -> None:
        return sanitize_floating_docks(self)

    def _flush_glass_surface(self) -> None:
        """Drop leftover opacity pixmaps and ask for a full repaint."""
        if self.conversation.graphicsEffect() is not None:
            self.conversation.setGraphicsEffect(None)
        empty = getattr(self.chat, "empty", None)
        if empty is not None and empty.graphicsEffect() is not None:
            empty.setGraphicsEffect(None)
        self.update()
        invalidate_window_surface(self)

    def _animate_dock(self, dock: QDockWidget) -> None:
        # Docked instruments are type in the void (fill 0). An opacity fade
        # on that glass caches a pixmap and ghosts ticks/strips across the
        # resize that opening a dock just caused. Floating plates are already
        # opaque — fading them punches a hole through to chat.
        if dock.graphicsEffect() is not None:
            dock.setGraphicsEffect(None)
        target = dock.widget()
        if target is not None and target.graphicsEffect() is not None:
            target.setGraphicsEffect(None)

    def _reset_layout(self) -> None:
        self.camera.stop()
        self.think_dock.setFloating(False)
        self.work_dock.setFloating(False)
        self.history_dock.setFloating(False)
        self.camera_dock.setFloating(False)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.think_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.work_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.history_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.camera_dock)
        self._stack_left_instruments()
        self.notify_inbox.hide()
        self.contacts_inbox.hide()
        self.calendar_window.hide()
        self._hide_world()
        self._calendar_sync_timer.stop()
        self._calendar_sync_watchdog.stop()
        self.sms_chats.hide_all()
        self._apply_calm_instrument_defaults()
        self.act_thinking.setChecked(self.think_dock.isVisible())
        self.act_workspace.setChecked(self.work_dock.isVisible())
        self.act_history.setChecked(False)
        self.act_notifications.setChecked(False)
        self.act_camera.setChecked(False)
        self.act_contacts.setChecked(False)
        self.act_calendar.setChecked(False)
        self._calendar_placed = False
        self.resize(default_window_size(self.config))
        self._sync_panel_margins()
        if self.conversation.graphicsEffect() is not None:
            self.conversation.setGraphicsEffect(None)
        sync_idle_mode(self)

    def _persist_window_layout(self) -> None:
        """Write geometry. Rest must not persist a collapsed window."""
        if self._away_resting:
            wake_from_away_rest(self)
        if getattr(self, "_filament_parked", None) is not None and active_theme() == "filament":
            return
        save_window_layout(self)

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

    def queue_pending_confirms(self, items: list[PendingConfirm]) -> None:
        """Show stored send confirms (e.g. from `arelis --core` drafts)."""
        self._pending_queue = list(items)
        for item in items:
            self._restoring_confirm_ids.add(item.id)
        self._show_next_pending_confirm()

    def _show_next_pending_confirm(self) -> None:
        if self._force_quit or self._disposed:
            return
        if not self._pending_queue:
            return
        if str(self.conversation.confirm._confirm_id or ""):
            return
        item = self._pending_queue[0]
        self.conversation.ask_confirm(
            item.id,
            item.tool,
            item.summary,
            detail=item.detail,
            note=item.note
            or "Restored pending send — nothing was sent while you were away.",
            batch_ok=item.batch_ok,
        )
        self._set_confirm_pending(True)
        self.thinking.append(f"confirm  {item.summary}", kind="tool")
        if self.isHidden():
            self.show_from_tray()

    def _on_index_tick(self) -> None:
        if self._force_quit or self._disposed:
            return
        if self.indexer is None or self._turn_busy:
            return
        if getattr(self.router, "reserve_vram_for_heavy", False):
            return
        loop = self.loop
        if loop is None or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self.indexer.run_batch(), loop)

    def _on_attach_errors(self, errors: list) -> None:
        for msg in errors or []:
            text = str(msg).strip()
            if text:
                self.chat.add_system(text)

    def _on_again(self) -> None:
        """Re-submit the last user turn. Same role; composer stays empty."""
        if self._turn_busy:
            self._toast_finish_or_stop(
                "Finish or stop the current turn before asking again."
            )
            return
        text = self.chat._last_user_text
        attachments = list(self.chat._last_user_attachments or [])
        if not text and not attachments:
            return
        role = self._current_role or self.conversation.role.currentText()
        self._on_submit(text, role, attachments)

    def _on_submit(self, text: str, role: str, attachments: list | None = None) -> None:
        note_engagement(self)
        if not attachments and self._try_physics_verb(text):
            return
        attachments = list(attachments or [])
        self._current_role = role
        # Grant session read on each original absolute path (attach = consent).
        for item in attachments:
            source = str(item.get("source_path") or "").strip()
            if source:
                try:
                    self.workspace_roots.grant_external_read(source)
                except Exception:
                    pass
        self._set_busy(True)
        self.chat.add_user(text, attachments=attachments)
        sync_idle_mode(self)
        if not (text or "").lstrip().startswith("/"):
            self._show_model_loading(role)
        payload: dict = {"text": text, "role": role}
        if attachments:
            payload["attachments"] = attachments
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.USER_MESSAGE, payload)),
            self.loop,
        )

    def _show_model_loading(self, role: str) -> None:
        """Composer hint while waiting for first token (L1 cold TTFT)."""
        pending = getattr(self.router, "warmup_pending", None)
        if callable(pending) and pending():
            tip = "loading the model — first reply after that is quick"
        else:
            model = str(
                (self.config.get("models") or {}).get(role) or self._current_model or ""
            )
            tip = f"thinking… ({role}" + (f":{model}" if model else "") + ")"
        self.thinking.append(tip, kind="status")
        if self.conversation.confirm_open():
            return
        if self.conversation.input.text().strip():
            return
        self.conversation.input.setPlaceholderText(tip)

    def _clear_model_loading(self) -> None:
        self.conversation._sync_composer_buttons()

    def _publish_bus(self, event: Event) -> None:
        """Best-effort bus publish. Tray Quit must not die if the loop is down."""
        loop = self.loop
        if loop is None or not loop.is_running():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.bus.publish(event), loop)
        except Exception:
            log.debug("bus publish skipped", exc_info=True)

    def _on_stop(self) -> None:
        self._cancel_turn(schedule_next=True)

    def _cancel_turn(self, *, schedule_next: bool) -> None:
        self._apply_stop_ui(publish_confirm_skip=True)
        self._ignore_cancel_echo = True
        self._publish_bus(Event(EventType.TURN_CANCEL, {}))
        if schedule_next and not self._force_quit and not self._disposed:
            self._later(0, self._show_next_pending_confirm)

    def _apply_stop_ui(self, *, publish_confirm_skip: bool) -> None:
        """Cut speech and hide the card. The bus cancel is published separately."""
        open_id = str(self.conversation.confirm._confirm_id or "")
        self.conversation.dismiss_confirm()
        self._set_confirm_pending(False)
        if open_id:
            self._pending_queue = [x for x in self._pending_queue if x.id != open_id]
            self._restoring_confirm_ids.discard(open_id)
            if publish_confirm_skip:
                self._publish_bus(
                    Event(
                        EventType.TOOL_CONFIRM_REPLY,
                        {"id": open_id, "decision": "skip", "allow_turn": False},
                    )
                )
        # Stop means stop. Speech outlives the turn that produced it, so
        # cancelling the turn without cutting playback leaves her talking about
        # something the user has already abandoned.
        stop_speech(self)
        self.thinking.append("stop requested", kind="status")
        self._drive_session = False
        self.conversation.set_drive(False)
        if not self._force_quit and not self._disposed:
            self._busy_watchdog.start(_BUSY_WATCHDOG_MS)

    def _on_stop_declined(self) -> None:
        """Esc on a turn that has painted nothing. Explain instead of cancelling.

        Three spoken SMS turns died here: the answer is held back until the
        tools have run, so the thread was blank, Esc read as "clear this", and
        the send was cancelled before its Allow card existed.
        """
        message = (
            "Still working — the answer is held back until the tools finish. "
            "Press stop to cancel it."
        )
        self.thinking.append(message, kind="status")
        # With the thinking dock closed that line lands somewhere nobody is
        # looking, and pressing Esc into total silence is what made the app feel
        # hung in the first place.
        if not self.think_dock.isVisible():
            self.chat.add_system(message)

    def _on_drive_pause(self) -> None:
        self.thinking.append("drive paused", kind="status")
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.TURN_PAUSE, {})),
            self.loop,
        )

    def _on_drive_resume(self) -> None:
        self.thinking.append("drive resumed", kind="status")
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.TURN_RESUME, {})),
            self.loop,
        )

    def _on_busy_watchdog(self) -> None:
        if self._force_quit or self._disposed:
            return
        if self._turn_busy:
            self._assistant_streaming = False
            self._set_busy(False)
            self.chat.add_system("Turn ended without a reply. Input re-enabled.")

    def _on_confirm_decided(self, confirm_id: str, decision: str, allow_turn: bool) -> None:
        note_engagement(self)
        # Clear the voice hold before the reply hits the bus so conversation
        # mode is not stuck deaf for an extra event-loop hop after Allow/Skip.
        self._set_confirm_pending(False)
        restoring = confirm_id in self._restoring_confirm_ids
        stored = self._pending_store.get(confirm_id)
        self._pending_queue = [x for x in self._pending_queue if x.id != confirm_id]
        self._restoring_confirm_ids.discard(confirm_id)
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(
                Event(
                    EventType.TOOL_CONFIRM_REPLY,
                    {"id": confirm_id, "decision": decision, "allow_turn": allow_turn},
                )
            ),
            self.loop,
        )
        # When attached to a detached core, also notify its bus (no silent send —
        # this only carries the human decision).
        if self.ipc_client is not None:
            asyncio.run_coroutine_threadsafe(
                self.ipc_client.send_confirm_reply(confirm_id, decision),
                self.loop,
            )
        # Restored / core-parked cards have no live waiter — Allow must send here.
        if restoring and decision in {"allow", "allow_turn"} and stored is not None:
            asyncio.run_coroutine_threadsafe(
                self._execute_restored_confirm(stored),
                self.loop,
            )
        elif restoring and decision not in {"allow", "allow_turn"}:
            self.thinking.append("pending send skipped", kind="status")
        self._later(0, self._show_next_pending_confirm)

    async def _execute_restored_confirm(self, item: PendingConfirm) -> None:
        await emit_restored_confirm(self.bus, item, self.config)

    def _set_confirm_pending(self, pending: bool) -> None:
        self._confirm_waiting = bool(pending)
        self.readiness_strip.set_confirm_waiting(pending)
        if self.voice_controller is not None:
            self.voice_controller.notify_confirm_pending(pending)
        if not pending:
            flush_held_inbound(self)
        if active_theme() == "filament":
            self._place_filament_floats(reshape=False)

    def _busy_status_line(self) -> str:
        """Shimmer copy for an in-flight turn with no named tool yet."""
        pending = getattr(self.router, "warmup_pending", None)
        if callable(pending) and pending():
            return WARMING_STATUS
        return THINKING_STATUS

    def _set_busy(self, busy: bool) -> None:
        self._turn_busy = busy
        self.conversation.set_busy(busy)
        self.history.set_switch_enabled(not busy)
        # Every turn status hangs off this one flag, so no shimmer can outlive the
        # turn that started it — including the turns that end at the watchdog
        # rather than at an answer.
        if busy:
            self.chat.show_progress(self._busy_status_line())
        else:
            self.chat.clear_progress()
        if not busy:
            self._busy_watchdog.stop()
            self._clear_model_loading()
            if self._drive_session:
                if not self.conversation.drive.is_paused():
                    self.conversation.set_drive_status("page stays")
            else:
                self.conversation.set_drive(False)
        if self.voice_controller is not None:
            if busy:
                self.voice_controller.notify_turn_started()
            else:
                self.voice_controller.notify_turn_finished()
        if not busy:
            flush_held_inbound(self)
        sync_idle_mode(self)

    def _on_project_changed(self, name: str) -> None:
        """Update the shared active project from the dock switcher (Qt thread)."""
        try:
            self.workspace_roots.set_active(name)
        except ValueError as exc:
            self.chat.add_system(str(exc))
            self.workspace.set_active_project(self.workspace_roots.active)
            return
        self.thinking.append(f"project  active → {name}", kind="status")
        refresh_desk(self)

    def _keep_file_on_desk(self, path: str) -> None:
        from arelis.ui.workspace_host import record_artifact

        record_artifact(self, path, source="open", pin=True)
        self.workspace.show_desk()
        self._reveal_dock(self.work_dock, self.act_workspace)
        self.chat.add_system(f"On the desk: {Path(path).name}")

    def _on_event(self, event: Event) -> None:
        dispatch_event(self, event)


    def _alert_if_background(self) -> None:
        """Flash the Arelis taskbar button when another app is in front."""
        if self._force_quit or self._disposed:
            return
        if process_owns_foreground():
            return
        flash_taskbar(self)

    def _floor_busy(self) -> bool:
        speaking = self._speech_expected or self._speech_playing or (
            self.speech_player is not None and self.speech_player.has_work()
        )
        return floor_is_busy(
            turn_busy=self._turn_busy,
            confirm_open=self.conversation.confirm_open(),
            speaking=speaking,
        )







    async def _operator_send_sms(self, alias: str, phone: str, body: str) -> None:
        return await operator_send_sms(self, alias, phone, body)







