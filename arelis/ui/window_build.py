"""Construct the sodium shell on an existing ArelisWindow.

Mixin on ArelisWindow. Same HWND. Not a second QMainWindow.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import (
    QIcon,
)
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QMainWindow,
    QSystemTrayIcon,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from arelis.core.bus import bind_app_bus
from arelis.desk import DeskStore
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
from arelis.sms_auto_reply import SmsAutoReply
from arelis.sms_inbound import InboundSms, InboundSmsWatcher
from arelis.sms_ingest import InboundIngestServer
from arelis.spatial.depth import DepthBank
from arelis.spatial.scene import REACH_DEFAULT, WorldScene, clamp_reach
from arelis.ui.calendar_window import CalendarWindow
from arelis.ui.chrome import TitleBar
from arelis.ui.contacts_inbox import ContactsInboxWindow
from arelis.ui.dock_surface import apply_dock_chrome
from arelis.ui.filament_desk import FilamentDesk
from arelis.ui.filament_field import (
    FilamentChatWindow,
    FilamentField,
    FilamentFloatBar,
    clamp_filament_span,
)
from arelis.ui.filament_tile import load_opacities, load_tile_origins, load_tile_sizes
from arelis.ui.glass import seal_tool_window
from arelis.ui.glass_dock import GlassDockWidget
from arelis.ui.history_host import request_session_load
from arelis.ui.host_bind import apply_startup_hosts, bind_window_hosts
from arelis.ui.layout_store import (
    clamp_away_rest_min,
    load_recent_workspace_files,
    load_ui_prefs,
    restore_window_layout,
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
)
from arelis.ui.sms_chat import SmsChatRegistry
from arelis.ui.spatial_hands import SpatialHands
from arelis.ui.stage import StageBackground
from arelis.ui.surface_report import log_report
from arelis.ui.theme import (
    GLASS,
    apply_theme,
    stylesheet,
    theme_from_config,
)
from arelis.ui.window_docks import bind_docks
from arelis.ui.workspace_host import refresh_desk
from arelis.ui.world_host import attach_world, bind_world
from arelis.workspace import WorkspaceRoots

log = logging.getLogger(__name__)

_WINDOW_RADIUS = int(GLASS["radius"])
_BUSY_WATCHDOG_MS = 8000
_THINK_PULSE_MS = 600
_VOICE_HOTKEY_ECHO_S = 0.12

_PANEL_OUTER = 12
_PANEL_HALF = 6
_PANEL_TOP = 12
_PANEL_BOTTOM = 14


def _hide_dock_title(dock: QDockWidget) -> None:
    dock.setFeatures(
        QDockWidget.DockWidgetFeature.DockWidgetMovable
        | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        | QDockWidget.DockWidgetFeature.DockWidgetClosable
    )
    apply_dock_chrome(dock, dock.isFloating())
    dock.topLevelChanged.connect(
        lambda floating, d=dock: apply_dock_chrome(d, bool(floating))
    )


def _dock_shell(body: QWidget, margins: tuple[int, int, int, int]) -> QWidget:
    shell = QWidget()
    layout = QVBoxLayout(shell)
    layout.setContentsMargins(*margins)
    layout.setSpacing(0)
    layout.addWidget(body)
    return shell

class WindowBuild:
    def _construct_shell(
        self,
        config: dict[str, Any],
        bridge,
        loop,
        bus,
        voice=None,
        *,
        store=None,
        restore_session_id: str | None = None,
        indexer=None,
        router=None,
    ) -> None:
        """Build chrome, docks, timers, and hosts on this HWND."""
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
