from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
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
    QTabBar,
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
from arelis.spatial import PHYSICS_ROOM_ID
from arelis.spatial.depth import DepthBank
from arelis.spatial.scene import (
    REACH_DEFAULT,
    WorldScene,
    clamp_reach,
)
from arelis.spatial.verbs import (
    PhysicsAct,
    classify_physics_act,
    is_time_verb,
    is_toy_verb,
    speech_body_names,
)
from arelis.ui.calendar_host import (
    calendar_service,
    kick_calendar_sync,
    on_calendar_create,
    on_calendar_delete,
    on_calendar_job_delete,
    on_calendar_job_run,
    on_calendar_job_save,
    on_calendar_sync_watchdog,
    on_calendar_task_add,
    on_calendar_task_remove,
    on_calendar_task_status,
    on_calendar_update,
    on_calendar_window_closed,
    reveal_calendar_jobs,
    run_calendar,
)
from arelis.ui.calendar_window import CalendarWindow
from arelis.ui.camera_host import (
    hand_depth,
    on_camera_ask,
    on_camera_dock_visibility,
    on_camera_pose,
    on_camera_pose_video,
    on_camera_record,
    on_camera_running_changed,
    on_camera_track,
    on_spatial_hands,
    on_spatial_recording,
    refresh_camera_capture_hook,
)
from arelis.ui.chrome import TitleBar
from arelis.ui.confirm_host import emit_restored_confirm
from arelis.ui.contacts_inbox import ContactsInboxWindow
from arelis.ui.dock_surface import apply_dock_chrome, apply_dock_surface, chrome_applying
from arelis.ui.event_host import dispatch_event
from arelis.ui.filament_field import (
    FilamentChatWindow,
    FilamentField,
    FilamentFloatBar,
    attach_on_rect,
    chrome_band_on_glass,
    clamp_filament_span,
    filament_chosen_desks,
    filament_row_desks,
    filament_span_geometry,
    filament_work_region,
    home_band_from_union,
    home_band_in_window,
)
from arelis.ui.filament_tile import (
    DEFAULT_OPACITY,
    DEFAULT_SIZES,
    apply_tile_opacity,
    apply_tile_size,
    bind_tile_opacity,
    bind_tile_size,
    flush_tile_geom,
    load_opacities,
    load_tile_origins,
    load_tile_sizes,
    origin_on_a_desk,
    play_tile_grow,
)
from arelis.ui.foreground import flash_taskbar, process_owns_foreground
from arelis.ui.glass import GlassFrame, advance_rim_pulse, seal_tool_window
from arelis.ui.glass_dock import GlassDockWidget
from arelis.ui.hands_host import apply_hands_face, on_hands_chip, park_hands, resume_hands
from arelis.ui.history_host import (
    build_rooms_menu,
    enter_room_from_menu,
    leave_room,
    on_fact_decided,
    on_history_delete,
    on_history_new,
    on_history_selected,
    refresh_history,
    request_session_load,
    show_rooms_menu,
    toast_finish_or_stop,
)
from arelis.ui.idle_host import (
    arm_away_rest_timer,
    away_rest_blocked,
    enter_away_rest,
    idle_eligible,
    note_engagement,
    on_idle_readiness,
    refresh_idle_face,
    return_to_idle,
    sync_idle_mode,
    sync_idle_voice_mode,
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
from arelis.ui.mobile_host import bind_mobile_hub
from arelis.ui.notify_host import (
    begin_job,
    finish_job,
    kick_mail_poll,
    on_inbox_opened,
    on_job_tick,
    on_mail_headers,
    on_notice_activated,
    on_notice_dismiss,
    on_notice_open,
    on_notice_snooze,
    on_notify_chip_clicked,
    on_notify_inbox_closed,
    on_notify_mark_all_read,
    on_notify_pill_clicked,
    on_notify_poll,
    on_notify_unread,
    report_poll_state,
    sync_notify_surface,
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
from arelis.ui.settings_host import (
    apply_always_on_top,
    apply_chat_font_scale,
    apply_settings,
    apply_world_reach,
    nudge_chat_font,
    on_reach_changed,
    open_settings,
    settings_test_mic,
    settings_test_speak,
    toggle_always_on_top,
    toggle_fullscreen,
)
from arelis.ui.shortcuts import ShortcutsSheet
from arelis.ui.sms_chat import SmsChatRegistry
from arelis.ui.sms_host import (
    flush_held_inbound,
    maybe_voice_sms,
    on_notice_reply,
    on_sms_received,
    on_sms_send_finished,
    on_sms_tile_send,
    on_sms_tile_shown,
    open_sms_chat,
    operator_send_sms,
    push_mobile_notice,
    sms_send_resolved,
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
    arm_speech,
    build_voice,
    invalidate_provisional,
    invalidate_wake,
    on_barge_in,
    on_capture_failed,
    on_live_pcm,
    on_live_started,
    on_playback,
    on_playback_failed,
    on_provisional_pcm,
    on_speech_synthesized,
    on_speech_watchdog,
    on_utterance,
    on_utterance_settled,
    on_voice_mode,
    on_voice_status,
    on_wake_detected,
    preload_voice,
    provisional_resolved,
    stop_speech,
    trace_voice,
    update_speaking,
    utterance_resolved,
    voice_restart_notices,  # noqa: F401 — tests import this from app
    wake_resolved,
)
from arelis.ui.window_resize import (
    cursor_for_hit,
    enable_win32_resize_frame,
    handle_native_resize,
    hit_test_resize,
    invalidate_window_surface,
    place_frameless_rect,
    release_native_children,
    try_system_resize,
)
from arelis.ui.workspace_host import (
    add_workspace_folder_dialog,
    apply_workspace_roots,
    disk_moved_under_editor,
    drop_desk_item,
    keep_note_dialog,
    new_workspace_folder_dialog,
    open_desk_item,
    open_file,
    open_outside,
    pin_desk_item,
    refresh_desk,
    register_workspace_folder,
    remove_active_workspace_root,
    reveal_desk_item,
    save_file,
    unique_root_name,
    workspace_root_dicts,
)
from arelis.ui.world_host import (
    attach_world,
    hide_world,
    should_offer_world,
    show_world,
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
        self.title_bar.view_menu_requested.connect(self._show_view_menu)
        self.title_bar.rooms_menu_requested.connect(self._show_rooms_menu)
        self.title_bar.settings_requested.connect(self._open_settings)
        self.title_bar.span_requested.connect(self._filament_set_span)
        self.readiness_strip.settings_requested.connect(self._open_settings)
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
        self._filament_floats.opened.connect(self._on_filament_float)
        self._filament_floats.hands_toggled.connect(self._on_hands_chip)
        self._filament_floats.hide()
        self._hands_chip = bool((config.get("ui") or {}).get("hands_chip", False))
        self._filament_chat_tile = FilamentChatWindow(self)
        self._filament_chat_tile.closed.connect(self._on_filament_chat_closed)
        self._filament_chat_tile.hide()
        self.conversation.setMouseTracking(True)

        # Dockable instruments — full glass bodies, no broken native title chrome
        self.thinking = ThinkingPanel()
        self.workspace = WorkspacePanel()
        self.history = HistoryPanel()
        self.contacts = ContactsPanel()
        self.notifications = NotificationsPanel()
        self.notify_center = NotificationCenter(config)
        self.sms_chats = SmsChatRegistry(self)
        self.sms_chats.set_send_handler(self._on_sms_tile_send)
        self.sms_chats.set_shown_handler(self._on_sms_tile_shown)
        self.camera = CameraPanel()
        self.spatial = SpatialHands(self)
        self.spatial.hint.connect(self.camera._set_hint)
        self.spatial.frame_ready.connect(self._on_spatial_hands)
        self.spatial.preview_ready.connect(self.camera.set_preview)
        self.spatial.recording_changed.connect(self._on_spatial_recording)
        self.camera.track_toggled.connect(self._on_camera_track)
        self.camera.record_toggled.connect(self._on_camera_record)
        self.camera.pose_frame.connect(self._on_camera_pose)
        self.camera.pose_video.connect(self._on_camera_pose_video)
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
        # an instrument. Saved layout still wins after the first run.
        self.resize(
            int(ui_cfg.get("default_width", 1440)),
            int(ui_cfg.get("default_height", 900)),
        )
        self.think_dock.resize(320, 600)
        self.history_dock.resize(280, 600)
        self._apply_calm_instrument_defaults()

        restored = restore_window_layout(
            self,
            QSize(int(ui_cfg.get("default_width", 1440)), int(ui_cfg.get("default_height", 900))),
        )
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
        self.camera.reach_changed.connect(self._on_reach_changed)

        self._build_view_actions()
        self._voice_hotkey_at = 0.0
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._apply_always_on_top(self._always_on_top, persist=False)
        self._apply_chat_font_scale(self._chat_font_scale, persist=False)
        self.conversation.submitted.connect(self._on_submit)
        self.chat.again_requested.connect(self._on_again)
        # QPlainTextEdit.textChanged has no arg; a `_t` lambda TypeError'd every keystroke.
        self.conversation.input.textChanged.connect(self._note_engagement)
        self.conversation.attach_errors.connect(self._on_attach_errors)
        self.conversation.stop_requested.connect(self._on_stop)
        self.conversation.stop_declined.connect(self._on_stop_declined)
        self.conversation.pause_requested.connect(self._on_drive_pause)
        self.conversation.resume_requested.connect(self._on_drive_resume)
        self.conversation.confirm_decided.connect(self._on_confirm_decided)
        self.conversation.leave_room_requested.connect(self._leave_room)
        self.conversation.world_requested.connect(self._open_world)
        # Armed paths for the two press-again gates that guard unsaved work in
        # the editor: discarding it by opening over it, and overwriting a file
        # that changed on disk while it sat open.
        self._workspace_discard_armed = ""
        self._workspace_overwrite_armed = ""
        self._workspace_tool_args: dict[str, Any] = {}
        self.workspace.open_requested.connect(self._open_file)
        self.workspace.save_requested.connect(self._save_file)
        self.workspace.project_changed.connect(self._on_project_changed)
        self.workspace.add_root_requested.connect(self._add_workspace_folder_dialog)
        self.workspace.new_root_requested.connect(self._new_workspace_folder_dialog)
        self.workspace.remove_root_requested.connect(self._remove_active_workspace_root)
        self.workspace.keep_requested.connect(self._keep_note_dialog)
        self.workspace.pin_requested.connect(self._pin_desk_item)
        self.workspace.drop_requested.connect(self._drop_desk_item)
        self.workspace.desk_open_requested.connect(self._open_desk_item)
        self.workspace.reveal_requested.connect(self._reveal_desk_item)
        self.workspace.outside_requested.connect(self._open_outside)
        self.chat.desk_requested.connect(self._keep_file_on_desk)
        self.history.session_selected.connect(self._on_history_selected)
        self.history.session_delete_requested.connect(self._on_history_delete)
        self.history.new_requested.connect(self._on_history_new)
        self.conversation.new_requested.connect(self._on_history_new)
        self.history.fact_decided.connect(self._on_fact_decided)
        self.notifications.unread_changed.connect(self._on_notify_unread)
        self.bridge.event_arrived.connect(self._on_event)
        self.think_dock.visibilityChanged.connect(self._on_dock_visibility)
        self.work_dock.visibilityChanged.connect(self._on_dock_visibility)
        self.history_dock.visibilityChanged.connect(self._on_dock_visibility)
        self.camera_dock.visibilityChanged.connect(self._on_dock_visibility)
        self.camera_dock.visibilityChanged.connect(self._on_camera_dock_visibility)
        self.camera.ask_arelis.connect(self._on_camera_ask)
        self.camera.running_changed.connect(self._on_camera_running_changed)
        for dock in (
            self.think_dock,
            self.work_dock,
            self.history_dock,
            self.camera_dock,
        ):
            dock.dockLocationChanged.connect(lambda _area: self._sync_panel_margins())
            dock.topLevelChanged.connect(lambda _floating: self._sync_panel_margins())
            dock.topLevelChanged.connect(lambda _floating: self._flush_glass_surface())
        self.history_dock.topLevelChanged.connect(lambda _f: self._stack_left_instruments())
        self.camera_dock.topLevelChanged.connect(lambda _f: self._stack_left_instruments())
        self.history_dock.dockLocationChanged.connect(lambda _a: self._stack_left_instruments())
        self.camera_dock.dockLocationChanged.connect(lambda _a: self._stack_left_instruments())

        self.notify_inbox.closed.connect(self._on_notify_inbox_closed)
        self.contacts_inbox.closed.connect(self._on_contacts_inbox_closed)
        self.calendar_window.closed.connect(self._on_calendar_window_closed)
        self.world_window.closed.connect(self._on_world_window_closed)
        overlay = self.conversation.notify_overlay
        overlay.dismiss_requested.connect(self._on_notice_dismiss)
        overlay.snooze_requested.connect(self._on_notice_snooze)
        overlay.reply_requested.connect(self._on_notice_reply)
        overlay.open_requested.connect(self._on_notice_open)
        overlay.pill_clicked.connect(self._on_notify_pill_clicked)
        overlay.collapsed.connect(self._sync_idle_mode)
        self.conversation.idle_conditions_changed.connect(self._sync_idle_mode)
        self.conversation.session_clicked.connect(self._on_history_selected)
        self.readiness_updated.connect(self._on_idle_readiness)
        self.readiness_strip.notify_chip.clicked.connect(self._on_notify_chip_clicked)
        self.mail_headers_ready.connect(self._on_mail_headers)
        self.notifications.opened.connect(self._on_inbox_opened)
        self.notifications.notice_activated.connect(self._on_notice_activated)
        self.notifications.chat_requested.connect(self._open_sms_chat)
        self.notifications.mark_read_btn.clicked.connect(self._on_notify_mark_all_read)
        self.sms_send_finished.connect(self._on_sms_send_finished)
        self._ui_call.connect(self._run_ui_call)

        self._assistant_streaming = False
        self._turn_busy = False
        self._mobile_foreign = False
        self._drive_session = False
        self._readiness_snap = None
        self._idle_ghosts: list[tuple[str, str]] = []
        self._away_timer = QTimer(self)
        self._away_timer.setSingleShot(True)
        self._away_timer.timeout.connect(self._enter_away_rest)
        self._arm_away_rest_timer()
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

        self._build_voice()
        if self.voice_controller is not None:
            self.voice_controller.listening_changed.connect(
                lambda _on: self._refresh_idle_face()
            )
        self._refresh_history()
        self._sync_idle_mode()

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
        self._notify_timer.timeout.connect(self._on_notify_poll)
        self._notify_timer.start()
        self._calendar_sync_inflight = False
        self._calendar_sync_timeout_ms = 20_000
        self._calendar_sync_timer = QTimer(self)
        self._calendar_sync_timer.setInterval(300_000)
        self._calendar_sync_timer.timeout.connect(self._kick_calendar_sync)
        self._calendar_sync_watchdog = QTimer(self)
        self._calendar_sync_watchdog.setSingleShot(True)
        self._calendar_sync_watchdog.timeout.connect(self._on_calendar_sync_watchdog)
        self.calendar.create_requested.connect(self._on_calendar_create)
        self.calendar.update_requested.connect(self._on_calendar_update)
        self.calendar.delete_requested.connect(self._on_calendar_delete)
        self.calendar.sync_requested.connect(self._kick_calendar_sync)
        self.calendar.task_add_requested.connect(self._on_calendar_task_add)
        self.calendar.task_status_requested.connect(self._on_calendar_task_status)
        self.calendar.task_remove_requested.connect(self._on_calendar_task_remove)
        self.calendar.job_save_requested.connect(self._on_calendar_job_save)
        self.calendar.job_delete_requested.connect(self._on_calendar_job_delete)
        self.calendar.job_run_requested.connect(self._on_calendar_job_run)
        self._job_tick = QTimer(self)
        self._job_tick.setInterval(1000)
        self._job_tick.timeout.connect(self._on_job_tick)

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
                0, lambda: self._request_session_load(self._restore_session_id or "")
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
        """Show an instrument once, with the same fade used by the View menu.

        Filament plates open from the bead, not from a turn. Auto-show is
        sodium stacked glass. asked=True is View / click. Thinking still
        breathes on the current.
        """
        if active_theme() == "filament" and not asked:
            return
        if getattr(self, "_away_resting", False):
            return
        if dock.isVisible():
            return
        dock.show()
        if action is not None:
            action.setChecked(True)
        self._animate_dock(dock)
        if active_theme() == "filament":
            names = {
                self.think_dock: "thinking",
                self.work_dock: "files",
                self.history_dock: "history",
                self.camera_dock: "camera",
            }
            self._filament_present_tile(dock, names.get(dock, "files"))

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

    def _build_voice(self) -> None:
        return build_voice(self)

    def _on_provisional_pcm(self, pcm: bytes, rate: int, channels: int) -> None:
        return on_provisional_pcm(self, pcm, rate, channels)

    def _provisional_resolved(self, future, generation: int) -> None:
        return provisional_resolved(self, future, generation)

    def _on_utterance(self, pcm: bytes, rate: int, channels: int, deliver: str) -> None:
        return on_utterance(self, pcm, rate, channels, deliver)

    def _on_live_started(self) -> None:
        return on_live_started(self)

    def _on_live_pcm(self, pcm: bytes, rate: int, channels: int) -> None:
        return on_live_pcm(self, pcm, rate, channels)

    def _invalidate_wake(self) -> None:
        return invalidate_wake(self)

    def _invalidate_provisional(self) -> None:
        return invalidate_provisional(self)

    def _wake_resolved(self, future, generation: int) -> None:
        return wake_resolved(self, future, generation)

    def _on_wake_detected(self, remainder: object) -> None:
        return on_wake_detected(self, remainder)

    def _utterance_resolved(self, future) -> None:
        return utterance_resolved(self, future)

    def _on_utterance_settled(self, became_turn: bool) -> None:
        return on_utterance_settled(self, became_turn)

    def _preload_voice(self) -> None:
        return preload_voice(self)

    def _on_voice_mode(self, mode: str) -> None:
        return on_voice_mode(self, mode)

    def _on_voice_status(self, message: str) -> None:
        return on_voice_status(self, message)

    def _on_capture_failed(self, message: str) -> None:
        return on_capture_failed(self, message)

    def _on_playback_failed(self, message: str) -> None:
        return on_playback_failed(self, message)

    def _on_barge_in(self) -> None:
        return on_barge_in(self)

    def _arm_speech(self) -> None:
        return arm_speech(self)

    def _on_speech_synthesized(self, clips: int) -> None:
        return on_speech_synthesized(self, clips)

    def _on_playback(self, playing: bool) -> None:
        return on_playback(self, playing)

    def _update_speaking(self) -> None:
        return update_speaking(self)

    def _on_speech_watchdog(self) -> None:
        return on_speech_watchdog(self)

    def _stop_speech(self) -> None:
        return stop_speech(self)

    def _trace_voice(self, event: str, **fields: Any) -> None:
        return trace_voice(self, event, **fields)


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
        self._on_notify_unread(self.notify_center.unread_count())

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
        self.act_settings.triggered.connect(lambda: self._open_settings())
        self.addAction(self.act_settings)

        self.act_always_on_top = QAction("always on top", self)
        self.act_always_on_top.setCheckable(True)
        self.act_always_on_top.setChecked(self._always_on_top)
        self.act_always_on_top.triggered.connect(self._toggle_always_on_top)
        self.addAction(self.act_always_on_top)

        self.act_fullscreen = QAction("fullscreen", self)
        self.act_fullscreen.setShortcut(QKeySequence(Qt.Key.Key_F11))
        self.act_fullscreen.triggered.connect(self._toggle_fullscreen)
        self.addAction(self.act_fullscreen)

        self.act_font_larger = QAction("larger text", self)
        self.act_font_larger.setShortcuts(
            [QKeySequence("Ctrl+="), QKeySequence("Ctrl++")]
        )
        self.act_font_larger.triggered.connect(lambda: self._nudge_chat_font(0.1))
        self.addAction(self.act_font_larger)

        self.act_font_smaller = QAction("smaller text", self)
        self.act_font_smaller.setShortcut(QKeySequence("Ctrl+-"))
        self.act_font_smaller.triggered.connect(lambda: self._nudge_chat_font(-0.1))
        self.addAction(self.act_font_smaller)

        self.act_font_reset = QAction("reset text size", self)
        self.act_font_reset.setShortcut(QKeySequence("Ctrl+0"))
        self.act_font_reset.triggered.connect(
            lambda: self._apply_chat_font_scale(1.0)
        )
        self.addAction(self.act_font_reset)

        self.act_notify_url = QAction("notify url…", self)
        self.act_notify_url.setToolTip("Show and copy the phone companion URL")
        self.act_notify_url.triggered.connect(lambda: self._open_settings("Notify"))
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
            self._note_engagement()
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
        self._note_engagement()
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
        self._sync_idle_mode()
        if active_theme() == "filament" and self._filament_parked is not None:
            self._later(0, self._filament_place_entity)

    def _sync_browser_anchor(self) -> None:
        """Her Chrome matches this window's size and sits beside chat."""
        from arelis.browser.launch import set_arelis_anchor

        geo = self.geometry()
        screen = self.screen()
        avail = screen.availableGeometry() if screen is not None else None
        set_arelis_anchor(
            geo.x(),
            geo.y(),
            geo.width(),
            geo.height(),
            screen=(
                (avail.x(), avail.y(), avail.width(), avail.height())
                if avail is not None
                else None
            ),
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

    def _build_filament_menu(self) -> QMenu:
        """Leave hatch when chrome is gone. Themes first so sodium is one click."""
        self._sync_view_checks()
        menu = QMenu(self)
        menu.setObjectName("FilamentMenu")
        themes = menu.addMenu("themes")
        for act in self._theme_actions.values():
            themes.addAction(act)
        menu.addSeparator()
        settings = menu.addAction("settings")
        settings.triggered.connect(lambda: self._open_settings())
        chat = menu.addAction("chat")
        chat.setCheckable(True)
        chat.setChecked(bool(self._filament_chat_open))
        chat.triggered.connect(lambda c=False: self._filament_set_chat_open(bool(c)))
        desks = menu.addMenu("desks")
        have = len(filament_row_desks(self, self._filament_home)[0])
        for n, label in ((1, "1 monitor"), (2, "2 monitors"), (3, "3 monitors")):
            act = desks.addAction(label)
            act.setCheckable(True)
            act.setChecked(self._filament_span == n)
            act.setEnabled(n <= max(1, have))
            act.triggered.connect(lambda _c=False, k=n: self._filament_set_span(k))
        rooms = self._build_rooms_menu()
        rooms.setTitle("rooms")
        menu.addMenu(rooms)
        menu.addSeparator()
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
        menu.addAction(self.act_shortcuts)
        return menu

    def _popup_filament_menu(self, global_pos) -> None:
        self._build_filament_menu().exec(global_pos)

    def _show_rooms_menu(self, anchor) -> None:
        return show_rooms_menu(self, anchor)

    def _build_rooms_menu(self) -> QMenu:
        return build_rooms_menu(self)

    def _hang_up_conversation(self) -> None:
        """Leave hands-free talk. Wake stays on. The room does not change."""
        btn = self.conversation.conversation_btn
        if btn.isChecked():
            btn.setChecked(False)
        if self.voice_controller is not None:
            self.voice_controller.set_conversation(False)
        self.thinking.append("Listening for Hey Arelis.", kind="status")

    def _enter_room_from_menu(self, room_id: str) -> None:
        return enter_room_from_menu(self, room_id)

    def _toggle_fullscreen(self) -> None:
        if active_theme() == "filament":
            if self.isFullScreen() or self.isMaximized():
                self.showNormal()
            self._filament_place_entity()
            return
        return toggle_fullscreen(self)

    def _toggle_always_on_top(self, checked: bool) -> None:
        return toggle_always_on_top(self, checked)

    def _apply_always_on_top(self, on: bool, *, persist: bool = True) -> None:
        return apply_always_on_top(self, on, persist=persist)

    def _nudge_chat_font(self, delta: float) -> None:
        return nudge_chat_font(self, delta)

    def _apply_chat_font_scale(self, scale: float, *, persist: bool = True) -> None:
        return apply_chat_font_scale(self, scale, persist=persist)

    def _on_reach_changed(self, reach: float) -> None:
        return on_reach_changed(self, reach)

    def _apply_world_reach(self, reach: float, *, persist: bool = True) -> None:
        return apply_world_reach(self, reach, persist=persist)

    def _open_settings(self, tab: str='') -> None:
        return open_settings(self, tab)

    def _settings_test_mic(self) -> str:
        return settings_test_mic(self)

    def _settings_test_speak(self) -> None:
        return settings_test_speak(self)

    def _apply_settings(self, values: dict[str, Any]) -> None:
        return apply_settings(self, values)

    def _apply_workspace_roots(
        self,
        roots: list[dict[str, object]],
        *,
        preferred_active: str | None = None,
    ) -> None:
        return apply_workspace_roots(self, roots, preferred_active=preferred_active)

    def _workspace_root_dicts(self) -> list[dict[str, object]]:
        return workspace_root_dicts(self)

    @staticmethod
    def _unique_root_name(base: str, taken: set[str]) -> str:
        return unique_root_name(base, taken)

    def _register_workspace_folder(self, path: Path, *, make_active: bool=True) -> None:
        return register_workspace_folder(self, path, make_active=make_active)

    def _add_workspace_folder_dialog(self) -> None:
        return add_workspace_folder_dialog(self)

    def _new_workspace_folder_dialog(self) -> None:
        return new_workspace_folder_dialog(self)

    def _remove_active_workspace_root(self) -> None:
        return remove_active_workspace_root(self)

    def _toggle_thinking(self, checked: bool) -> None:
        self._note_engagement()
        self.think_dock.setVisible(checked)
        if checked:
            self._animate_dock(self.think_dock)
            self._filament_present_tile(self.think_dock, "thinking")

    def _toggle_workspace(self, checked: bool) -> None:
        self._note_engagement()
        self.work_dock.setVisible(checked)
        if checked:
            self._animate_dock(self.work_dock)
            self._filament_present_tile(self.work_dock, "files")

    def _toggle_history(self, checked: bool) -> None:
        self._note_engagement()
        self.history_dock.setVisible(checked)
        if checked:
            self._refresh_history()
            self._animate_dock(self.history_dock)
            self._filament_present_tile(self.history_dock, "history")
        self._stack_left_instruments()

    def _toggle_notifications(self, checked: bool) -> None:
        self._note_engagement()
        if checked:
            self._on_notify_poll()
            self.notify_inbox.show()
            self.notify_inbox.raise_()
            self.notifications.opened.emit()
            if active_theme() == "filament":
                self._filament_dress_tile(self.notify_inbox, "notify")
                self._filament_place_near_title(self.notify_inbox, "notify")
        else:
            if active_theme() == "filament":
                flush_tile_geom(self.notify_inbox)
            self.notify_inbox.hide()

        self._sync_notify_surface()
        self._sync_idle_mode()

    def _toggle_camera(self, checked: bool) -> None:
        self._note_engagement()
        self.camera_dock.setVisible(checked)
        if checked:
            self.camera.start()
            self._animate_dock(self.camera_dock)
            self._filament_present_tile(self.camera_dock, "camera")
        else:
            self.camera.stop()
        self._stack_left_instruments()

    def _toggle_contacts(self, checked: bool) -> None:
        self._note_engagement()
        if checked:
            self.contacts.show_list()
            self.contacts_inbox.show()
            self.contacts_inbox.raise_()
            if active_theme() == "filament":
                self._filament_dress_tile(self.contacts_inbox, "contacts")
                self._filament_place_near_title(self.contacts_inbox, "contacts")
        else:
            if active_theme() == "filament":
                flush_tile_geom(self.contacts_inbox)
            self.contacts_inbox.hide()
        self._sync_idle_mode()

    def _toggle_calendar(self, checked: bool) -> None:
        self._note_engagement()
        if checked:
            if not getattr(self, "_calendar_placed", False):
                geo = self.frameGeometry()
                self.calendar_window.move(geo.x() + 40, geo.y() + 40)
                self._calendar_placed = True
            self.calendar_window.show()
            self.calendar_window.raise_()
            self.calendar.reload()
            self._kick_calendar_sync()
            self._calendar_sync_timer.start()
            if active_theme() == "filament":
                self._filament_dress_tile(self.calendar_window, "days")
                self._filament_place_near_title(self.calendar_window, "days")
        else:
            if active_theme() == "filament":
                flush_tile_geom(self.calendar_window)
            self.calendar_window.hide()
            self._calendar_sync_timer.stop()
            self._calendar_sync_watchdog.stop()
        self._sync_idle_mode()

    def _open_world(self) -> None:
        self.act_world.setChecked(True)
        self._toggle_world(True)

    def _toggle_world(self, checked: bool, page: str = "", *, force: bool = False) -> None:
        self._note_engagement()
        if not world_available():
            self.act_world.setChecked(False)
            if checked:
                self.thinking.append(
                    "Reality's plate is a source-checkout stage — not in the installer.",
                    kind="status",
                )
            return
        if checked:
            if not force and not should_offer_world(self.conversation.room.room_id):
                self.act_world.setChecked(False)
                self.thinking.append(
                    "Reality is that room. Say let's work on Reality first.",
                    kind="status",
                )
                return
            self._world_placed = show_world(
                self.world_window,
                self.frameGeometry(),
                page=page,
                placed=getattr(self, "_world_placed", False),
            )
            if active_theme() == "filament":
                self._filament_dress_tile(self.world_window, "reality")
                self._filament_place_near_title(self.world_window, "reality")
        else:
            if active_theme() == "filament":
                flush_tile_geom(self.world_window)
            hide_world(self.world_window)
        self._sync_idle_mode()

    def _hide_world(self) -> None:
        self.world_scene.reset()
        if hasattr(self, "world_depth"):
            self.world_depth.reset()
        hide_world(getattr(self, "world_window", None))
        window = getattr(self, "world_window", None)
        if window is not None:
            window.panel.refresh()
        if hasattr(self, "act_world"):
            self.act_world.setChecked(False)

    def _try_physics_verb(self, text: str) -> bool:
        """Closed lexicon in this room. True when it must not start a turn."""
        act = classify_physics_act(text, names=speech_body_names())
        if not act:
            return False
        in_reality = self.conversation.room.room_id == PHYSICS_ROOM_ID
        if not in_reality and act.verb != "goto_earth":
            return False
        self._apply_physics_act(act)
        return True

    def _apply_physics_verb(
        self,
        verb: str,
        *,
        name: str = "",
        flag: str = "",
        on: bool | None = None,
        page: str = "",
    ) -> None:
        self._apply_physics_act(
            PhysicsAct(verb=verb, name=name, flag=flag, on=on, page=page)
        )

    def _apply_physics_act(self, act: PhysicsAct) -> None:
        from arelis.physics.runtime import get_system

        verb = act.verb
        if verb == "lab":
            self._apply_tile("world", show=bool(act.on), page=act.page)
            return
        if verb == "overlay":
            self._apply_tile("world", show=True, page="solar")
            system = get_system()
            if system is None:
                self.thinking.append("No solar system loaded", kind="status")
                return
            val = system.apply_overlay(act.flag, on=act.on)
            if val is None:
                self.thinking.append(f"unknown overlay {act.flag}", kind="status")
                return
            self.thinking.append(f"{act.flag}={val}", kind="status")
            self._touch_solar()
            return
        if verb == "travel":
            self._apply_tile("world", show=True, page="solar")
            system = get_system()
            if system is None:
                self.thinking.append("No solar system loaded", kind="status")
                return
            name = (act.name or "").strip()
            if not name:
                name = ""
                if hasattr(self, "world_window"):
                    name = str(self.world_window.solar._inspect or "")
                if not name:
                    name = str(system.lock or "")
            if not name:
                self.thinking.append(
                    "Name a body, or inspect one first.", kind="status"
                )
                return
            if system.nbody.find(name) is None:
                self.thinking.append(f"No body named {name!r}", kind="status")
                return
            system.lock = name
            system.pending_inspect = name
            system.pending_travel = name
            self.thinking.append(f"flying to {name}", kind="status")
            self._touch_solar()
            return
        if verb == "inspect_body":
            self._apply_tile("world", show=True, page="solar")
            system = get_system()
            if system is None:
                self.thinking.append("No solar system loaded", kind="status")
                return
            name = (act.name or "").strip()
            if not name or system.nbody.find(name) is None:
                self.thinking.append(f"No body named {name!r}", kind="status")
                return
            system.lock = name
            system.pending_inspect = name
            self.thinking.append(f"inspecting {name}", kind="status")
            self._touch_solar()
            return
        if verb == "reset_view":
            self._apply_tile("world", show=True, page="solar")
            system = get_system()
            if system is None:
                self.thinking.append("No solar system loaded", kind="status")
                return
            system.pending_reset = True
            self.thinking.append("reset view", kind="status")
            self._touch_solar()
            return
        if verb == "enter_earth":
            self._apply_tile("world", show=True, page="solar")
            from arelis.earth.runtime import require_earth

            note = require_earth().enter()
            system = get_system()
            if system is not None and system.nbody.find("Earth") is not None:
                system.lock = "Earth"
                system.pending_inspect = "Earth"
                system.pending_travel = "Earth"
            self.thinking.append(note, kind="status")
            self._touch_solar()
            return
        if verb == "leave_earth":
            from arelis.earth.dump import dump_state
            from arelis.earth.runtime import get_earth

            zone = get_earth()
            if zone is None or not zone.active:
                self.thinking.append("already solar", kind="status")
                return
            try:
                dump_state(zone, trigger="leave")
            except OSError:
                pass
            self.thinking.append(zone.leave(), kind="status")
            self._touch_solar()
            return
        if verb == "goto_earth":
            from arelis.earth.gazetteer import resolve_place
            from arelis.earth.runtime import require_earth

            query = (act.name or "").strip()
            zone = require_earth()
            hit = resolve_place(query, zone)
            if hit is None:
                if query.casefold() in {"home", "here"}:
                    self.thinking.append(
                        "Set a home city in your profile first.", kind="status"
                    )
                    return
                self.thinking.append(
                    f"I don't know a place named {query!r}.", kind="status"
                )
                return
            if not world_available():
                self.thinking.append(
                    "Reality's plate is a source-checkout stage — not in the installer.",
                    kind="status",
                )
                return
            self._toggle_world(True, page="solar", force=True)
            if not zone.active:
                zone.enter()
            zone.request_goto(hit)
            system = get_system()
            on_earth = False
            if hasattr(self, "world_window"):
                on_earth = getattr(self.world_window.solar, "_earth_cam", None) is not None
            if system is not None and system.nbody.find("Earth") is not None:
                system.lock = "Earth"
                system.pending_inspect = "Earth"
                if not on_earth:
                    system.pending_travel = "Earth"
            self.thinking.append(f"flying to {hit.name}", kind="status")
            self._touch_solar()
            return
        if verb == "ride_iss":
            self._apply_tile("world", show=True, page="solar")
            from arelis.earth.runtime import require_earth

            zone = require_earth()
            if not zone.active:
                zone.enter()
            hit = zone.ride("norad:25544")
            system = get_system()
            if system is not None:
                system.lock = "Earth"
                system.pending_inspect = "Earth"
                system.pending_travel = "Earth"
            self.thinking.append(
                f"riding {hit.label}" if hit else "ISS not in the store",
                kind="status",
            )
            self._touch_solar()
            return
        if is_time_verb(verb):
            system = get_system()
            if system is None:
                self.thinking.append("No solar system loaded", kind="status")
                return
            if verb == "pause":
                system.paused = True
            elif verb == "resume":
                system.paused = False
            elif verb == "step":
                system.step_once()
            elif verb == "faster":
                system.set_rate(min(1.0e7, system.rate * 10.0))
            elif verb == "slower":
                system.set_rate(system.rate / 10.0)
            elif verb == "realtime":
                system.go_realtime()
            elif verb == "hour":
                system.set_rate(3_600.0)
            elif verb == "day":
                system.set_rate(86_400.0)
            elif verb == "year":
                system.set_rate(365.25 * 86_400.0)
            elif verb == "fly":
                system.enter_inspect()
            elif verb == "inspect":
                system.enter_inspect()
            self.thinking.append(
                f"{verb}  rate={system.rate:g}  t={system.t:.3e}s",
                kind="status",
            )
            self._touch_solar()
            return
        system = get_system()
        if system is not None and is_toy_verb(verb):
            if verb == "freeze":
                system.paused = True
                self.thinking.append("pause  (freeze is the sandbox word)", kind="status")
                return
            if verb == "unfreeze":
                system.paused = False
                self.thinking.append("resume  (unfreeze is the sandbox word)", kind="status")
                return
            self.thinking.append(
                "No discs in Reality. Spawn a particle, belt tracer, or L4 from "
                "the ⋯ menu. WASD flies the inspect camera. heavier/lighter would "
                "change a mass — that is solar impulse/add_planet with Allow.",
                kind="status",
            )
            return
        result = self.world_scene.apply_verb(verb)
        if hasattr(self, "world_window"):
            self.world_window.panel.refresh()
        if result:
            mass = result.get("mass")
            frozen = result.get("frozen")
            bits = [str(result.get("verb") or verb)]
            if isinstance(mass, (int, float)):
                bits.append(f"{mass:.2f}×")
            if frozen:
                bits.append("frozen")
            self.thinking.append(" ".join(bits), kind="status")
        else:
            self.thinking.append("Nothing is held", kind="status")

    def _touch_solar(self) -> None:
        if hasattr(self, "world_window") and self.world_window.solar_active():
            self.world_window.solar.update()

    def _apply_tile(self, name: str, *, show: bool, page: str = "") -> None:
        """Show or hide a View-menu tile from the tile tool."""
        key = (name or "").strip().lower()
        mapping = {
            "thinking": (self.act_thinking, self._toggle_thinking),
            "workspace": (self.act_workspace, self._toggle_workspace),
            "history": (self.act_history, self._toggle_history),
            "notifications": (self.act_notifications, self._toggle_notifications),
            "camera": (self.act_camera, self._toggle_camera),
            "contacts": (self.act_contacts, self._toggle_contacts),
            "calendar": (self.act_calendar, self._toggle_calendar),
            "world": (self.act_world, self._toggle_world),
        }
        pair = mapping.get(key)
        if pair is None:
            return
        action, toggle = pair
        action.setChecked(show)
        if key == "world":
            self._toggle_world(show, page=page)
            return
        toggle(show)

    def _run_ui_call(self, fn) -> None:
        if getattr(self, "_disposed", False) or getattr(self, "_force_quit", False):
            return
        if callable(fn):
            fn()

    def _calendar_service(self):
        return calendar_service(self)

    def _run_calendar(self, coro, *, ok_status: str = "google · just now") -> None:
        return run_calendar(self, coro, ok_status=ok_status)

    def _kick_calendar_sync(self) -> None:
        return kick_calendar_sync(self)

    def _on_calendar_sync_watchdog(self) -> None:
        return on_calendar_sync_watchdog(self)

    def _on_calendar_create(self, payload: dict[str, Any]) -> None:
        return on_calendar_create(self, payload)

    def _on_calendar_update(self, payload: dict[str, Any]) -> None:
        return on_calendar_update(self, payload)

    def _on_calendar_delete(self, event_id: str) -> None:
        return on_calendar_delete(self, event_id)

    def _on_calendar_task_add(self, title: str, due: str) -> None:
        return on_calendar_task_add(self, title, due)

    def _on_calendar_task_status(self, task_id: int, status: str) -> None:
        return on_calendar_task_status(self, task_id, status)

    def _on_calendar_task_remove(self, task_id: int) -> None:
        return on_calendar_task_remove(self, task_id)

    def _reveal_calendar_jobs(self) -> None:
        return reveal_calendar_jobs(self)

    def _on_calendar_job_save(self, payload: dict[str, Any]) -> None:
        return on_calendar_job_save(self, payload)

    def _on_calendar_job_delete(self, job_id: str) -> None:
        return on_calendar_job_delete(self, job_id)

    def _on_calendar_job_run(self, job_id: str) -> None:
        return on_calendar_job_run(self, job_id)

    def _on_contacts_inbox_closed(self) -> None:
        self.act_contacts.setChecked(False)
        self._sync_idle_mode()

    def _on_calendar_window_closed(self) -> None:
        return on_calendar_window_closed(self)

    def _on_world_window_closed(self) -> None:
        self.act_world.setChecked(False)
        self._calendar_sync_timer.stop()
        self._calendar_sync_watchdog.stop()
        self._sync_idle_mode()

    def _on_notify_unread(self, count: int) -> None:
        return on_notify_unread(self, count)

    def _on_notify_inbox_closed(self) -> None:
        return on_notify_inbox_closed(self)

    def _on_inbox_opened(self) -> None:
        return on_inbox_opened(self)

    def _on_notify_mark_all_read(self) -> None:
        return on_notify_mark_all_read(self)

    def _on_notice_activated(self, notice_id: str) -> None:
        return on_notice_activated(self, notice_id)

    def _on_camera_dock_visibility(self, visible: bool) -> None:
        return on_camera_dock_visibility(self, visible)

    def _on_camera_running_changed(self, _running: bool) -> None:
        return on_camera_running_changed(self, _running)

    def _on_camera_track(self, on: bool) -> None:
        return on_camera_track(self, on)

    def _on_hands_chip(self, on: bool) -> None:
        return on_hands_chip(self, on)

    def _on_camera_record(self, on: bool) -> None:
        return on_camera_record(self, on)

    def _on_camera_pose(self, payload: object) -> None:
        return on_camera_pose(self, payload)

    def _on_camera_pose_video(self, frame: object, t_capture: float) -> None:
        return on_camera_pose_video(self, frame, t_capture)

    def _on_spatial_recording(self, on: bool) -> None:
        return on_spatial_recording(self, on)

    def _hand_depth(self, who: str, hand: object, stamp: float, frame: object) -> float | None:
        return hand_depth(self, who, hand, stamp, frame)

    def _on_spatial_hands(self, frame: object) -> None:
        return on_spatial_hands(self, frame)

    def _refresh_camera_capture_hook(self) -> None:
        return refresh_camera_capture_hook(self)

    def _on_camera_ask(self, path: str) -> None:
        return on_camera_ask(self, path)

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
                "this replaces the app face. it may take the desk you give it.",
                detail=(
                    "the current sits on the desk. talk does not need a chat tile. "
                    "history, thinking, chat, days, files open as their own plates "
                    "— drag them anywhere. right-click for themes. sodium is one click."
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
        conv = getattr(self, "conversation", None)
        if conv is None:
            return "idle"
        if getattr(conv, "_speaking", False):
            self._filament_woken = True
            return "speak"
        if getattr(conv, "_busy", False) or getattr(self, "_turn_busy", False):
            self._filament_woken = True
            return "think"
        if conv.conversation_btn.isChecked() or conv.mic_btn.isChecked():
            self._filament_woken = True
            return "listen"
        if getattr(self, "_away_resting", False):
            self._filament_woken = False
            return "idle"
        if not getattr(self, "_filament_woken", False):
            return "idle"
        return "awake"

    def _filament_can_claim_desk(self) -> bool:
        app = QApplication.instance()
        if app is None:
            return False
        return str(app.platformName()) != "offscreen"

    def _filament_apply_glass(self, _on: bool) -> None:
        """Enter and leave both seal. The desk HWND is never layered.

        WA_TranslucentBackground stacked every glyph (a second history
        header, a second orbit). Opacity lives on the floating plates.
        """
        seal_tool_window(self)

    def _filament_pin_home(self) -> QRect | None:
        """Always the OS primary desk. Never the screen the HWND drifted onto."""
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            screen = self.screen()
        if screen is None:
            return QRect(self._filament_home) if self._filament_home is not None else None
        self._filament_home = QRect(screen.availableGeometry())
        return QRect(self._filament_home)

    def _filament_set_span(self, n: int) -> None:
        want = clamp_filament_span(n)
        self._filament_span = want
        self.title_bar.set_span_choice(want)
        self.config.setdefault("ui", {})["filament_span"] = want
        from arelis.config import merge_local_config

        merge_local_config({"ui": {"filament_span": want}})
        if active_theme() == "filament":
            self._filament_place_entity()

    def _filament_place_entity(self) -> None:
        """Grow or shrink to the chosen 1 / 2 / 3 desks."""
        if not self._filament_can_claim_desk():
            self.title_bar.set_span_choice(self._filament_span)
            return
        home = self._filament_pin_home()
        union, pinned, count = filament_span_geometry(self, self._filament_span, home)
        have = len(filament_row_desks(self, pinned)[0])
        self.title_bar.set_span_choice(self._filament_span)
        self.title_bar.set_span_available(have)
        if pinned is None:
            return
        # Place during __init__ used to take the app down. The HWND is real
        # after show; showEvent already re-places.
        if not self.isVisible() or self.windowHandle() is None:
            self._filament_apply_shape()
            return
        if count <= 1:
            self._filament_fill_home_desk(pinned)
        else:
            placed = place_frameless_rect(self, union)
            if not home_band_in_window(self, pinned).isValid():
                placed = place_frameless_rect(self, union) or placed
            # HWND on the union with a stale Qt cache still counts. Snapping
            # home here is how a working 3-span got thrown away.
            if not placed and not home_band_in_window(self, pinned).isValid():
                self._filament_fill_home_desk(pinned)
        self._filament_apply_shape()
        empty = getattr(getattr(self, "chat", None), "empty", None)
        layout_idle = getattr(empty, "_layout_idle", None)
        if callable(layout_idle):
            layout_idle()
        self.title_bar.sync_window_state(self)
        # dirty_rect is the old band. New desk glass has to void-fill once.
        self.update()

    def _filament_fill_home_desk(self, pinned: QRect) -> None:
        """Sit on the primary work area. showMaximized follows the HWND to the wrong desk."""
        if pinned is None or not pinned.isValid():
            return
        place_frameless_rect(self, pinned)

    def _filament_is_spanned(self) -> bool:
        if self._filament_span >= 2:
            home = self._filament_pin_home()
            if home is None:
                return True
            return self.width() >= int(home.width() * 1.2)
        home = self._filament_pin_home()
        if home is None:
            return bool(self.isMaximized() or self.isFullScreen())
        geo = self.geometry()
        return (
            abs(geo.x() - home.x()) <= 16
            and abs(geo.width() - home.width()) <= 24
            and abs(geo.height() - home.height()) <= 24
        )

    def _filament_toggle_span(self) -> None:
        """Maximize snaps back to the chosen 1 / 2 / 3. It does not cycle
        desks and it does not fullscreen — F11 follows the HWND left."""
        if self.isFullScreen() or self.isMaximized():
            self.showNormal()
        self._filament_place_entity()

    def _filament_apply_shape(self) -> None:
        self.clearMask()
        if not self._filament_can_claim_desk():
            self._filament.set_span(self._filament_span)
            self._filament_place_chrome()
            return
        home = self._filament_pin_home()
        union, pinned, desks = filament_chosen_desks(self, self._filament_span, home)
        count = len(desks)
        work = filament_work_region(union, desks)
        if not work.isEmpty() and count >= 2:
            self.setMask(work)
        band = home_band_from_union(union, pinned)
        if not band.isValid() or band.width() < 280:
            band = home_band_in_window(self, pinned)
        win_w = max(1, int(self.width()))
        if band.isValid() and band.width() >= 280:
            desk_left = int(band.x())
            desk_w = int(band.width())
        else:
            desk_left = 0
            desk_w = win_w
        self._filament.set_span(
            max(1, count),
            desk_left=float(desk_left),
            desk_width=float(desk_w),
        )
        self._filament_place_chrome()

    def _filament_place_chrome(self) -> None:
        """Slim 1/2/3 bar sits on the primary overlap, above the field."""
        bar = self.title_bar
        bar.set_slim(True)
        home = self._filament_pin_home()
        union, pinned, _count = filament_span_geometry(self, self._filament_span, home)
        glass = QRect(0, 0, max(1, int(self.width())), max(32, int(self.height())))
        band = chrome_band_on_glass(union, pinned, glass)
        if bar.parent() is not self:
            bar.setParent(self)
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.set_home_band(0, 0, 0)
        bar.setGeometry(band)
        bar.show()
        bar.raise_()
        self.chrome_bar.hide()
        self.readiness_strip.hide()

    def _filament_dock_chrome(self) -> None:
        bar = self.title_bar
        stack = getattr(self, "_chrome_stack", None)
        bar.set_home_band(0, 0, 0)
        if stack is not None and bar.parent() is not stack:
            lay = stack.layout()
            if lay is not None:
                lay.insertWidget(0, bar)
        bar.set_slim(False)
        self.chrome_bar.show()

    def _filament_lock_tiles(self, on: bool) -> None:
        docks = {
            "thinking": self.think_dock,
            "files": self.work_dock,
            "history": self.history_dock,
            "camera": self.camera_dock,
        }
        sides = (
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        if on:
            if self._filament_dock_areas is None:
                self._filament_dock_areas = {
                    name: dock.allowedAreas() for name, dock in docks.items()
                }
            for name, dock in docks.items():
                dock.setAllowedAreas(Qt.DockWidgetArea.NoDockWidgetArea)
                bind_tile_opacity(dock, name, self._filament_opacity)
                bind_tile_size(
                    dock, name, self._filament_tile_sizes, self._filament_tile_pos
                )
                if not getattr(dock, "_filament_afloat_bound", False):
                    dock._filament_afloat_bound = True
                    dock.topLevelChanged.connect(
                        lambda floating, d=dock, n=name: self._filament_refuse_dock(
                            d, n, floating
                        )
                    )
            for widget, name in self._filament_extra_tiles():
                bind_tile_opacity(widget, name, self._filament_opacity)
                bind_tile_size(
                    widget, name, self._filament_tile_sizes, self._filament_tile_pos
                )
        else:
            parked = self._filament_dock_areas or {}
            self._filament_dock_areas = None
            for name, dock in docks.items():
                dock.setAllowedAreas(parked.get(name, sides))
                apply_tile_opacity(dock, 1.0)
            for widget, _name in self._filament_extra_tiles():
                apply_tile_opacity(widget, 1.0)
            self.calendar_window.setMinimumSize(720, 520)

    def _filament_extra_tiles(self) -> list[tuple[object, str]]:
        extras: list[tuple[object, str]] = [
            (self._filament_chat_tile, "chat"),
            (self.calendar_window, "days"),
            (self.notify_inbox, "notify"),
            (self.contacts_inbox, "contacts"),
        ]
        world = getattr(self, "world_window", None)
        if world is not None:
            extras.append((world, "reality"))
        return extras

    @staticmethod
    def _filament_plate_open(widget) -> bool:
        return widget is not None and not widget.isHidden()

    def _filament_native_hit(self, event_type, message):
        """No HTTRANSPARENT. The desk is an opaque HWND; click-through
        ate the title bar and left holes in the field."""
        return None

    def _filament_wants_click(self, global_pos) -> bool:
        local = self.mapFromGlobal(global_pos)
        bar = getattr(self, "chrome_bar", None)
        if (
            self._filament_chrome_peek
            and bar is not None
            and bar.isVisible()
            and bar.geometry().contains(local)
        ):
            return True
        if self._filament.hit_band(self.rect()).contains(local):
            return True
        if self._filament.prompt_rect(self.rect()).contains(local):
            return True
        floats = getattr(self, "_filament_floats", None)
        if floats is not None:
            hits = list(floats.chips().values())
            hits.extend(getattr(floats, "_beads", {}).values())
            for btn in hits:
                if not btn.isVisible():
                    continue
                top = QRect(btn.mapTo(self, QPoint(0, 0)), btn.size())
                if top.contains(local):
                    return True
        return False

    def _filament_on_mouse_move(self, event) -> None:
        """Sodium used to peek chrome on hover. Filament keeps the slim bar."""
        return

    def _filament_set_chrome_peek(self, on: bool) -> None:
        if active_theme() != "filament":
            return
        self._filament_chrome_peek = bool(on)
        bar = getattr(self, "chrome_bar", None)
        if bar is None:
            return
        bar.setVisible(on)
        if on:
            bar.raise_()

    def _filament_enter_presence(self) -> None:
        if self._filament_parked is not None:
            return
        self.act_fullscreen.setEnabled(False)
        # Capture before showNormal. After it, both flags are false and
        # leave would restore a normal window the user never asked for.
        was_full = self.isFullScreen()
        was_max = self.isMaximized()
        parked_geo = QByteArray(self.saveGeometry())
        if was_full or was_max:
            self.showNormal()
        self._filament_woken = False
        self._filament_home = None
        self._filament_pin_home()
        self.title_bar.set_span_choice(self._filament_span)
        world = getattr(self, "world_window", None)
        self._filament_parked = {
            "geometry": parked_geo,
            "maximized": was_max,
            "fullscreen": was_full,
            "docks": {
                "think": not self.think_dock.isHidden(),
                "work": not self.work_dock.isHidden(),
                "history": not self.history_dock.isHidden(),
                "camera": not self.camera_dock.isHidden(),
                "notify": not self.notify_inbox.isHidden(),
                "contacts": not self.contacts_inbox.isHidden(),
                "calendar": not self.calendar_window.isHidden(),
                "world": world is not None and not world.isHidden(),
            },
        }
        self._filament_hiding = True
        try:
            self.title_bar.set_slim(True)
            self.readiness_strip.hide()
            self.think_dock.hide()
            self.work_dock.hide()
            self.history_dock.hide()
            self.camera_dock.hide()
            self.notify_inbox.hide()
            self.contacts_inbox.hide()
            self.calendar_window.hide()
            if world is not None:
                world.hide()
        finally:
            self._filament_hiding = False
        self._filament_apply_glass(True)
        self._filament_lock_tiles(True)
        self._filament_place_entity()
        apply = getattr(self.conversation, "apply_filament_desk", None)
        if callable(apply):
            apply(True, chat_open=False)
        self._sync_panel_margins()
        self._sync_view_checks()
        self._sync_idle_mode()
        self._place_filament_floats()
        self._filament_apply_shape()
        self._flush_glass_surface()
        self.update()

    def _filament_leave_presence(self) -> None:
        self.act_fullscreen.setEnabled(True)
        parked = self._filament_parked
        self._filament_parked = None
        self._filament_home = None
        self._filament_chrome_peek = False
        self._filament_set_chat_open(False)
        self._filament_lock_tiles(False)
        self._filament_apply_glass(False)
        self.clearMask()
        self._filament_dock_chrome()
        self.readiness_strip.show()
        apply = getattr(self.conversation, "apply_filament_desk", None)
        if callable(apply):
            apply(False)
        if parked is None:
            self._sync_panel_margins()
            self._sync_idle_mode()
            return
        docks = parked.get("docks") or {}
        self._filament_hiding = True
        try:
            self.think_dock.setVisible(bool(docks.get("think")))
            self.work_dock.setVisible(bool(docks.get("work")))
            self.history_dock.setVisible(bool(docks.get("history")))
            self.camera_dock.setVisible(bool(docks.get("camera")))
            if docks.get("notify"):
                self.notify_inbox.show()
            else:
                self.notify_inbox.hide()
            if docks.get("contacts"):
                self.contacts_inbox.show()
            else:
                self.contacts_inbox.hide()
            if docks.get("calendar"):
                self.calendar_window.show()
            else:
                self.calendar_window.hide()
            world = getattr(self, "world_window", None)
            if world is not None:
                if docks.get("world"):
                    world.show()
                else:
                    world.hide()
        finally:
            self._filament_hiding = False
        if self._filament_can_claim_desk():
            geo = parked.get("geometry")
            if parked.get("fullscreen"):
                self.showFullScreen()
            elif parked.get("maximized"):
                self.showMaximized()
            else:
                self.showNormal()
                if geo:
                    self.restoreGeometry(geo)
        self._sync_panel_margins()
        self._sync_view_checks()
        self._sync_idle_mode()
        self._apply_round_mask()
        self.update()

    def _sync_filament_face(self) -> None:
        on = active_theme() == "filament"
        floats = getattr(self, "_filament_floats", None)
        if floats is None:
            return
        if on:
            self._filament_enter_presence()
            floats.setVisible(True)
            self._place_filament_floats()
            apply_hands_face(self)
        else:
            floats.setVisible(False)
            self._filament_leave_presence()
            apply_hands_face(self)
        empty = getattr(getattr(self, "chat", None), "empty", None)
        if empty is not None and hasattr(empty, "apply_theme_face"):
            empty.apply_theme_face()

    def _place_filament_floats(self, *, reshape: bool = True) -> None:
        floats = getattr(self, "_filament_floats", None)
        if floats is None or active_theme() != "filament":
            return
        history = getattr(self, "history_dock", None)
        think = getattr(self, "think_dock", None)
        work = getattr(self, "work_dock", None)
        cal = getattr(self, "calendar_window", None)
        camera = getattr(self, "camera_dock", None)
        notify = getattr(self, "notify_inbox", None)
        contacts = getattr(self, "contacts_inbox", None)
        world = getattr(self, "world_window", None)
        floats.skip("reality", not world_available())
        hidden = set()
        if not world_available():
            hidden.add("reality")
        self._filament.set_hidden_faces(hidden)
        floats.set_open("history", self._filament_plate_open(history))
        floats.set_open("thinking", self._filament_plate_open(think))
        floats.set_open("files", self._filament_plate_open(work))
        floats.set_open("days", self._filament_plate_open(cal))
        floats.set_open("camera", self._filament_plate_open(camera))
        floats.set_open("notify", self._filament_plate_open(notify))
        floats.set_open("contacts", self._filament_plate_open(contacts))
        floats.set_open("reality", self._filament_plate_open(world))
        floats.set_open("chat", bool(self._filament_chat_open))
        live: set[str] = set()
        if self._filament_weather() == "think" or getattr(
            self, "_confirm_waiting", False
        ):
            live.add("thinking")
        unread = 0
        center = getattr(self, "notify_center", None)
        if center is not None:
            unread = int(center.unread_count())
        if unread > 0 and not self._filament_plate_open(notify):
            live.add("notify")
        self._filament.set_live_faces(live)
        self._filament.set_load("camera" if self._filament_plate_open(camera) else "")
        floats.place(self.rect())
        self._filament_sync_tethers()
        if reshape:
            self._filament_apply_shape()

    def _filament_sync_tethers(self) -> None:
        tiles = {
            "history": getattr(self, "history_dock", None),
            "thinking": getattr(self, "think_dock", None),
            "files": getattr(self, "work_dock", None),
            "days": getattr(self, "calendar_window", None),
            "camera": getattr(self, "camera_dock", None),
            "notify": getattr(self, "notify_inbox", None),
            "contacts": getattr(self, "contacts_inbox", None),
            "reality": getattr(self, "world_window", None),
            "chat": getattr(self, "_filament_chat_tile", None),
        }
        open_faces = {name for name, w in tiles.items() if w is not None and not w.isHidden()}
        self._filament.set_open_faces(open_faces)
        for name, widget in tiles.items():
            if widget is None or widget.isHidden():
                self._filament.bind_tether(name, None)
                continue
            geo = widget.frameGeometry()
            local = QRect(self.mapFromGlobal(geo.topLeft()), geo.size())
            anchor = self._filament.anchor_point(name, self.rect())
            self._filament.bind_tether(name, attach_on_rect(local, anchor))

    def _on_filament_float(self, name: str) -> None:
        if name == "chat":
            self._filament_set_chat_open(not self._filament_chat_open)
            return
        if name == "rooms":
            chips = self._filament_floats.chips()
            self._show_rooms_menu(chips.get("rooms") or self)
            return
        if name == "history":
            self.act_history.trigger()
        elif name == "thinking":
            self.act_thinking.trigger()
        elif name == "files":
            self.act_workspace.trigger()
        elif name == "days":
            self.act_calendar.trigger()
        elif name == "camera":
            self.act_camera.trigger()
        elif name == "notify":
            self.act_notifications.trigger()
        elif name == "contacts":
            self.act_contacts.trigger()
        elif name == "reality":
            self._filament_open_reality()

    def _filament_open_reality(self) -> None:
        """The particle is the door. Orbit still cannot open the plate."""
        if not world_available():
            self._toggle_world(True)
            return
        if self._filament_plate_open(getattr(self, "world_window", None)):
            self._toggle_world(False)
            return
        room_id = str(getattr(self.conversation.room, "room_id", "") or "")
        if room_id != PHYSICS_ROOM_ID:
            self._enter_room_from_menu(PHYSICS_ROOM_ID)
        self._toggle_world(True, force=True)

    def _filament_refuse_dock(self, dock: QDockWidget, name: str, floating: bool) -> None:
        if active_theme() != "filament" or floating or dock.isHidden():
            return
        dock.setAllowedAreas(Qt.DockWidgetArea.NoDockWidgetArea)
        dock.setFloating(True)
        apply_dock_chrome(dock, True)

    def _filament_dress_tile(self, widget, name: str) -> None:
        self._filament_woken = True
        widget.setMinimumSize(240, 180)
        apply_tile_opacity(widget, self._filament_opacity.get(name, DEFAULT_OPACITY))
        bind_tile_opacity(widget, name, self._filament_opacity)
        apply_tile_size(widget, name, self._filament_tile_sizes)
        bind_tile_size(widget, name, self._filament_tile_sizes, self._filament_tile_pos)

    def _filament_present_tile(self, dock: QDockWidget, name: str) -> None:
        if active_theme() != "filament" or dock.isHidden():
            return
        dock.setAllowedAreas(Qt.DockWidgetArea.NoDockWidgetArea)
        dock.setFloating(True)
        apply_dock_chrome(dock, True)
        self._filament_dress_tile(dock, name)
        self._filament_place_near_title(dock, name)

    def _filament_place_near_title(self, widget, name: str) -> None:
        p = self._filament.title_point(name, self.rect())
        origin = self.mapToGlobal(QPoint(int(p.x()) + 12, int(p.y()) + 24))
        size = self._filament_tile_sizes.get(name) or DEFAULT_SIZES.get(name, (320, 280))
        parked = self._filament_tile_pos.get(name)
        if (
            active_theme() == "filament"
            and parked is not None
            and origin_on_a_desk(parked[0], parked[1], size[0], size[1])
        ):
            dest = QRect(int(parked[0]), int(parked[1]), int(size[0]), int(size[1]))
            start = self._filament.bead_point(name, self.rect())
            local = QRect(self.mapFromGlobal(dest.topLeft()), dest.size())
            self._filament.bind_tether(name, attach_on_rect(local, start))
            widget.setMinimumSize(240, 180)
            apply_tile_opacity(
                widget, self._filament_opacity.get(name, DEFAULT_OPACITY)
            )
            widget.setGeometry(dest)
            widget.show()
            widget.raise_()
            self._place_filament_floats()
            return
        if active_theme() == "filament":
            dest = QRect(self.mapFromGlobal(origin), QSize(int(size[0]), int(size[1])))
            start = self._filament.bead_point(name, self.rect())
            self._filament.bind_tether(name, attach_on_rect(dest, start))
            play_tile_grow(
                widget,
                origin,
                size,
                opacity=self._filament_opacity.get(name, DEFAULT_OPACITY),
            )
            self._place_filament_floats()
            return
        widget.move(origin)
        widget.show()
        widget.raise_()

    def _filament_set_chat_open(self, on: bool) -> None:
        want = bool(on)
        if want == self._filament_chat_open and (
            want is False or self.conversation.chat.parent() is self._filament_chat_tile.body
        ):
            if want:
                self._filament_chat_tile.show()
                self._filament_chat_tile.raise_()
            self._place_filament_floats()
            return
        if want:
            self._filament_mount_chat()
            self._filament_chat_open = True
            self._filament_dress_tile(self._filament_chat_tile, "chat")
            self._filament_place_near_title(self._filament_chat_tile, "chat")
        else:
            if active_theme() == "filament":
                flush_tile_geom(self._filament_chat_tile)
            self._filament_unmount_chat()
            self._filament_chat_open = False
            self._filament_chat_tile.hide()
        apply = getattr(self.conversation, "apply_filament_desk", None)
        if callable(apply) and active_theme() == "filament":
            apply(True, chat_open=want)
        self._place_filament_floats()

    def _on_filament_chat_closed(self) -> None:
        if self._filament_chat_open:
            self._filament_set_chat_open(False)

    def _filament_mount_chat(self) -> None:
        conv = self.conversation
        tile = self._filament_chat_tile
        if conv.chat.parent() is tile.body:
            return
        lay = conv.layout()
        if lay is not None:
            lay.removeWidget(conv.chat)
            lay.removeWidget(conv._composer)
        tile.body_layout.addWidget(conv.chat, stretch=1)
        tile.body_layout.addWidget(conv._composer)
        conv.chat.setMinimumWidth(0)
        conv._composer.setMinimumWidth(0)
        conv.chat.show()
        empty = getattr(conv.chat, "empty", None)
        if empty is not None:
            empty.hide()
        if conv.chat.has_messages:
            conv.chat.view.show()
        else:
            conv.chat.view.hide()
        conv._place_composer(False)
        conv._composer.show()
        apply_tile_size(tile, "chat", self._filament_tile_sizes)

    def _filament_unmount_chat(self) -> None:
        conv = self.conversation
        tile = self._filament_chat_tile
        if conv.chat.parent() is not tile.body:
            return
        tile.body_layout.removeWidget(conv.chat)
        tile.body_layout.removeWidget(conv._composer)
        lay = conv.layout()
        if lay is not None:
            lay.insertWidget(1, conv.chat, stretch=1)
            lay.addWidget(conv._composer)
        conv.chat.hide()
        conv._composer.hide()

    def _on_dock_visibility(self, visible: bool) -> None:
        # Ignore the transient hide that setWindowFlags causes while swapping
        # floating chrome — otherwise View checks flip off and the panel vanishes.
        # _arelis_parked is the same kind of bookkeeping: the glass went to the
        # tray or the taskbar and took its floating panels with it, which is not
        # the user turning an instrument off.
        sender = self.sender()
        if getattr(self, "_filament_hiding", False):
            return
        if isinstance(sender, QDockWidget) and (
            chrome_applying(sender) or getattr(sender, "_arelis_parked", False)
        ):
            return
        if (
            not visible
            and active_theme() == "filament"
            and isinstance(sender, QDockWidget)
        ):
            flush_tile_geom(sender)
        self._sync_view_checks()
        self._place_filament_floats()
        self._sync_panel_margins()
        self._flush_glass_surface()
        if visible:
            dock = sender
            if isinstance(dock, QDockWidget) and dock.isFloating():
                self._animate_dock(dock)
        if sender in (self.history_dock, self.camera_dock):
            self._stack_left_instruments()
        self._sync_idle_mode()

    def _docked_in(self, dock: QDockWidget, area: Qt.DockWidgetArea) -> bool:
        return (
            dock.isVisible()
            and not dock.isFloating()
            and self.dockWidgetArea(dock) == area
        )

    def _left_column_member(self, dock: QDockWidget) -> bool:
        """Same as docked-on-the-left, but isHidden() so tests and tray agree."""
        return (
            not dock.isHidden()
            and not dock.isFloating()
            and self.dockWidgetArea(dock) == Qt.DockWidgetArea.LeftDockWidgetArea
        )

    def _history_camera_tabbed(self) -> bool:
        for bar in self.findChildren(QTabBar):
            labels = {bar.tabText(i).strip().lower() for i in range(bar.count())}
            if "history" in labels and "camera" in labels:
                return True
        return False

    def _stack_left_instruments(self) -> None:
        """History above camera on the left. No tabs. Float restores history."""
        if active_theme() == "filament":
            return
        if getattr(self, "_disposed", False) or getattr(self, "_stacking_left", False):
            return
        if chrome_applying(self.history_dock) or chrome_applying(self.camera_dock):
            return
        self._stacking_left = True
        try:
            hist = self.history_dock
            cam = self.camera_dock
            if self._history_camera_tabbed():
                if not hist.isFloating():
                    self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, hist)
                if not cam.isFloating():
                    self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, cam)
            hist_left = self._left_column_member(hist)
            cam_left = self._left_column_member(cam)
            if hist_left and cam_left:
                already = cam.y() >= hist.y() + 40 and not self._history_camera_tabbed()
                self.splitDockWidget(hist, cam, Qt.Orientation.Vertical)
                if not already:
                    column = max(hist.height() + cam.height(), 400)
                    cam_h = max(240, column // 2)
                    hist_h = max(160, column - cam_h)
                    self.resizeDocks([hist, cam], [hist_h, cam_h], Qt.Orientation.Vertical)
            self._sync_panel_margins()
        finally:
            self._stacking_left = False

    def _sync_panel_margins(self) -> None:
        """Keep outer and inter-panel gutters equal (history | chat | thinking)."""
        left = self._docked_in(
            self.history_dock, Qt.DockWidgetArea.LeftDockWidgetArea
        ) or self._docked_in(
            self.camera_dock, Qt.DockWidgetArea.LeftDockWidgetArea
        )
        # Thinking on the right abuts the chat glass.
        right = self._docked_in(
            self.think_dock, Qt.DockWidgetArea.RightDockWidgetArea
        )
        bottom = self._docked_in(
            self.work_dock, Qt.DockWidgetArea.BottomDockWidgetArea
        )

        # Chat: OUTER against the window when a side is empty; HALF when a dock
        # shares that edge (dock contributes the other HALF → gap == OUTER).
        chat_l = _PANEL_HALF if left else _PANEL_OUTER
        chat_r = _PANEL_HALF if right else _PANEL_OUTER
        chat_b = _PANEL_HALF if bottom else _PANEL_BOTTOM
        if active_theme() == "filament" and not left and not right and not bottom:
            self._stage_layout.setContentsMargins(0, 0, 0, 0)
        else:
            self._stage_layout.setContentsMargins(chat_l, _PANEL_TOP, chat_r, chat_b)

        # Floating shells must stay margin-0 / opaque — docked gutters punch holes.
        hist_left = self._left_column_member(self.history_dock)
        cam_left = self._left_column_member(self.camera_dock)
        stacked = hist_left and cam_left

        if self.history_dock.isFloating():
            _set_shell_margins(self._history_shell, (0, 0, 0, 0))
        elif stacked:
            _set_shell_margins(
                self._history_shell,
                (_PANEL_OUTER, _PANEL_TOP, _PANEL_HALF, _PANEL_HALF),
            )
        else:
            _set_shell_margins(
                self._history_shell,
                (_PANEL_OUTER, _PANEL_TOP, _PANEL_HALF, _PANEL_BOTTOM),
            )
        if self.think_dock.isFloating():
            _set_shell_margins(self._think_shell, (0, 0, 0, 0))
        else:
            _set_shell_margins(
                self._think_shell,
                (_PANEL_HALF, _PANEL_TOP, _PANEL_OUTER, _PANEL_BOTTOM),
            )
        if self.work_dock.isFloating():
            _set_shell_margins(self._work_shell, (0, 0, 0, 0))
        else:
            _set_shell_margins(
                self._work_shell,
                (_PANEL_OUTER, _PANEL_HALF, _PANEL_OUTER, _PANEL_BOTTOM),
            )
        if self.camera_dock.isFloating():
            _set_shell_margins(self._camera_shell, (0, 0, 0, 0))
        elif stacked:
            _set_shell_margins(
                self._camera_shell,
                (_PANEL_OUTER, _PANEL_HALF, _PANEL_HALF, _PANEL_BOTTOM),
            )
        else:
            _set_shell_margins(
                self._camera_shell,
                (_PANEL_OUTER, _PANEL_TOP, _PANEL_HALF, _PANEL_BOTTOM),
            )

    def _sanitize_floating_docks(self) -> None:
        """Seal restored floats. Never slam them back into the column.

        A floating camera on the other monitor is a saved layout, not a ghost.
        Ghosts came from a translucent main HWND plus redocking after first
        paint (wide stage, then shrink, leftover orbit on the right). Floats
        stay their own opaque HWNDs; calendar and world are not docks.
        """
        for dock in (
            self.think_dock,
            self.work_dock,
            self.history_dock,
            self.camera_dock,
        ):
            apply_dock_chrome(dock, dock.isFloating())
        self._stack_left_instruments()
        self._sync_panel_margins()
        self._flush_glass_surface()

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
        self.resize(
            int(self.config.get("ui", {}).get("default_width", 1440)),
            int(self.config.get("ui", {}).get("default_height", 900)),
        )
        self._sync_panel_margins()
        if self.conversation.graphicsEffect() is not None:
            self.conversation.setGraphicsEffect(None)
        self._sync_idle_mode()

    def _idle_eligible(self) -> bool:
        return idle_eligible(self)

    def _sync_idle_mode(self) -> None:
        return sync_idle_mode(self)

    def _return_to_idle(self) -> None:
        return return_to_idle(self)

    def _away_rest_blocked(self) -> bool:
        return away_rest_blocked(self)

    def _arm_away_rest_timer(self) -> None:
        return arm_away_rest_timer(self)

    def _note_engagement(self) -> None:
        return note_engagement(self)

    def _enter_away_rest(self) -> None:
        return enter_away_rest(self)

    def _wake_from_away_rest(self) -> None:
        return wake_from_away_rest(self)

    def _persist_window_layout(self) -> None:
        """Write geometry. Rest must not persist a collapsed window."""
        if self._away_resting:
            self._wake_from_away_rest()
        if getattr(self, "_filament_parked", None) is not None and active_theme() == "filament":
            return
        save_window_layout(self)

    def _on_idle_readiness(self, snapshot) -> None:
        return on_idle_readiness(self, snapshot)

    def _sync_idle_voice_mode(self, mode: str | None=None) -> None:
        return sync_idle_voice_mode(self, mode)

    def _refresh_idle_face(self) -> None:
        return refresh_idle_face(self)

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
            self._stop_speech,
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
            self._stop_speech()
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
        self._stop_speech()
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
        self._note_engagement()
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
        self._sync_idle_mode()
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
        self._stop_speech()
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
        self._note_engagement()
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
            self._flush_held_inbound()
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
            self._flush_held_inbound()
        self._sync_idle_mode()

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

    def _refresh_history(self) -> None:
        return refresh_history(self)

    def _on_fact_decided(self, fact_ids: object, status: str) -> None:
        return on_fact_decided(self, fact_ids, status)

    def _on_history_selected(self, session_id: str) -> None:
        return on_history_selected(self, session_id)

    def _on_history_delete(self, session_id: str) -> None:
        return on_history_delete(self, session_id)

    def _on_history_new(self) -> None:
        return on_history_new(self)

    def _toast_finish_or_stop(self, message: str) -> None:
        return toast_finish_or_stop(self, message)

    def _request_session_load(self, session_id: str) -> None:
        return request_session_load(self, session_id)

    def _leave_room(self) -> None:
        return leave_room(self)

    def _open_file(self, path: str) -> None:
        return open_file(self, path)

    def _disk_moved_under_editor(self, target: Path, content: str) -> bool:
        return disk_moved_under_editor(self, target, content)

    def _save_file(self, path: str, content: str) -> None:
        return save_file(self, path, content)

    def _keep_note_dialog(self) -> None:
        return keep_note_dialog(self)

    def _pin_desk_item(self, path: str, pinned: bool) -> None:
        return pin_desk_item(self, path, pinned)

    def _drop_desk_item(self, path: str) -> None:
        return drop_desk_item(self, path)

    def _open_desk_item(self, path: str) -> None:
        return open_desk_item(self, path)

    def _reveal_desk_item(self, path: str) -> None:
        return reveal_desk_item(self, path)

    def _open_outside(self, path: str) -> None:
        return open_outside(self, path)

    def _keep_file_on_desk(self, path: str) -> None:
        from arelis.ui.workspace_host import record_artifact

        record_artifact(self, path, source="open", pin=True)
        self.workspace.show_desk()
        self._reveal_dock(self.work_dock, self.act_workspace)
        self.chat.add_system(f"On the desk: {Path(path).name}")

    def _on_event(self, event: Event) -> None:
        dispatch_event(self, event)

    def _on_sms_received(self, payload: dict[str, Any]) -> None:
        return on_sms_received(self, payload)


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

    def _flush_held_inbound(self) -> None:
        return flush_held_inbound(self)


    def _maybe_voice_sms(self, messages: list[InboundSms]) -> None:
        return maybe_voice_sms(self, messages)


    def _sync_notify_surface(self) -> None:
        return sync_notify_surface(self)

    def _on_notify_pill_clicked(self) -> None:
        return on_notify_pill_clicked(self)

    def _on_notify_chip_clicked(self) -> None:
        return on_notify_chip_clicked(self)

    def _on_notice_dismiss(self, notice_id: str) -> None:
        return on_notice_dismiss(self, notice_id)

    def _on_notice_snooze(self, notice_id: str) -> None:
        return on_notice_snooze(self, notice_id)

    def _on_notice_reply(self, notice_id: str) -> None:
        return on_notice_reply(self, notice_id)


    def _on_notice_open(self, notice_id: str) -> None:
        return on_notice_open(self, notice_id)

    def _on_sms_tile_shown(self, alias: str, phone: str) -> None:
        return on_sms_tile_shown(self, alias, phone)


    def _open_sms_chat(self, notice_id: str) -> None:
        return open_sms_chat(self, notice_id)


    def _on_sms_tile_send(self, key: str, body: str, alias: str, phone: str) -> None:
        return on_sms_tile_send(self, key, body, alias, phone)


    async def _operator_send_sms(self, alias: str, phone: str, body: str) -> None:
        return await operator_send_sms(self, alias, phone, body)


    def _sms_send_resolved(self, future, key: str) -> None:
        return sms_send_resolved(self, future, key)


    def _on_sms_send_finished(self, key: str, ok: bool, error: str) -> None:
        return on_sms_send_finished(self, key, ok, error)


    def _push_mobile_notice(self, kind: str, title: str, body: str) -> None:
        return push_mobile_notice(self, kind, title, body)


    def _bind_mobile_hub(self) -> None:
        return bind_mobile_hub(self)


    def _begin_job(self, tool: str) -> None:
        return begin_job(self, tool)

    def _finish_job(self, tool: str, *, ok: bool, output: str='') -> None:
        return finish_job(self, tool, ok=ok, output=output)

    def _on_job_tick(self) -> None:
        return on_job_tick(self)

    def _report_poll_state(self, key: str, message: str) -> None:
        return report_poll_state(self, key, message)

    def _on_notify_poll(self) -> None:
        return on_notify_poll(self)

    def _kick_mail_poll(self) -> None:
        return kick_mail_poll(self)

    def _on_mail_headers(self, rows: object) -> None:
        return on_mail_headers(self, rows)


