from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
import threading
import time
from collections.abc import Callable, MutableMapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
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

from arelis.browser.hold import format_drive_status
from arelis.browser.walls import your_turn_status
from arelis.config import (
    _parse_workspace_roots,
    deep_merge,
    load_config,
    merge_local_config,
)
from arelis.core.bus import EventBus, bind_app_bus
from arelis.core.events import Event, EventType
from arelis.core.failure_copy import plain_reason, tool_failure_notice
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.llm import (
    build_router,
    prefix_warmup_for,
    run_auto_lessons,
    run_model_preflight,
    run_model_warmup,
)
from arelis.llm.router import ModelRouter
from arelis.local_open import open_local_file, reveal_local_file
from arelis.mail import load_account
from arelis.memory import DEFAULT_EMBED_MODEL, MemoryIndexer, MemoryStore
from arelis.notify import NotificationCenter, new_notice
from arelis.notify.sources import (
    due_task_notices,
    load_today_events,
    mail_notices,
    peek_contact_mail_sync,
)
from arelis.paths import app_icon_path, display_path, logs_dir, outputs_dir
from arelis.presence.confirm_exec import execute_pending_confirm
from arelis.presence.confirm_persist import ConfirmPersister
from arelis.presence.inbound_runtime import InboundRuntime, attach_inbound
from arelis.presence.ipc_client import IpcClient
from arelis.presence.ipc_server import IpcServer
from arelis.presence.lock import external_core_available
from arelis.presence.pending_confirms import (
    PendingConfirm,
    PendingConfirmStore,
    pending_confirms_path,
)
from arelis.presence.readiness import ChipLevel, probe_readiness
from arelis.sms import (
    SmsSendError,
    explain_sms_error,
    resolve_operator_sms_target,
    send_operator_sms,
)
from arelis.sms_auto_reply import SmsAutoReply
from arelis.sms_inbound import (
    InboundSms,
    InboundSmsWatcher,
    floor_is_busy,
    format_held_inbound_voice_cue,
)
from arelis.sms_ingest import InboundIngestServer
from arelis.spatial import PHYSICS_ROOM_ID
from arelis.spatial.depth import ESTIMATOR, DepthBank
from arelis.spatial.grant import world_stage_allowed
from arelis.spatial.verbs import classify_physics_verb, is_time_verb, is_toy_verb
from arelis.spatial.scene import (
    GRAVITY,
    REACH_DEFAULT,
    WorldScene,
    clamp_reach,
    image_to_world,
)
from arelis.spatial.types import grab_drive
from arelis.tools import build_tool_registry
from arelis.ui.audio import SpeechPlayer
from arelis.ui.calendar_window import CalendarWindow
from arelis.ui.chrome import TitleBar
from arelis.ui.contacts_inbox import ContactsInboxWindow
from arelis.ui.dock_surface import apply_dock_chrome, apply_dock_surface, chrome_applying
from arelis.ui.first_run import prompt_for_workspace_root
from arelis.ui.foreground import flash_taskbar, process_owns_foreground
from arelis.ui.glass import GlassFrame, advance_rim_pulse, seal_tool_window
from arelis.ui.glass_dock import GlassDockWidget
from arelis.ui.layout_store import (
    clamp_away_rest_min,
    load_recent_workspace_files,
    load_ui_prefs,
    push_recent_workspace_file,
    restore_window_layout,
    save_ui_prefs,
    save_window_layout,
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
from arelis.ui.panels.workspace import is_workspace_listing, status_for_tool_result
from arelis.ui.readiness_strip import ReadinessStrip
from arelis.ui.settings_dialog import SettingsDialog
from arelis.ui.setup_wizard import prompt_for_model_setup
from arelis.ui.shortcuts import ShortcutsSheet
from arelis.ui.sms_chat import SmsChatRegistry, room_owns_doorbell, seed_bodies
from arelis.ui.spatial_hands import SpatialHands
from arelis.ui.stage import StageBackground, paint_atmosphere
from arelis.ui.status_copy import (
    THINKING_STATUS,
    WAITING_STATUS,
    tool_status_line,
)
from arelis.ui.surface_report import log_report
from arelis.ui.theme import (
    GLASS,
    app_font,
    load_fonts,
    qt_font_directory,
    stylesheet,
)
from arelis.ui.voice_control import VoiceController
from arelis.ui.window_resize import (
    configure_native_windows,
    cursor_for_hit,
    enable_win32_resize_frame,
    handle_native_resize,
    hit_test_resize,
    invalidate_window_surface,
    release_native_children,
    try_system_resize,
)
from arelis.ui.world_window import WorldWindow
from arelis.voice import VoiceService
from arelis.voice.pcm import write_wav
from arelis.voice.wake import WakeResult, classify_wake, looks_like_wake_attempt
from arelis.workspace import RootEntry, WorkspaceRoots, compose_stt_initial_prompt

log = logging.getLogger(__name__)

_WINDOW_RADIUS = int(GLASS["radius"])

# If a turn somehow ends without a terminal event, re-enable the composer
# rather than leaving the user with a dead window. The orchestrator guarantees
# ASSISTANT_DONE or ERROR, so reaching this is a bug, but a desktop app should
# not need restarting to recover from one.
_BUSY_WATCHDOG_MS = 8000
# One amber hairline on the thinking plate after a click, then rest.
_THINK_PULSE_MS = 600

# A spoken reply holds the microphone closed, so losing its terminal event
# costs the user conversation mode entirely. This is the backstop, sized for
# the worst honest case: one very long sentence being synthesized while the
# previous one plays. Every clip and every playback transition restarts it, so
# a genuinely long answer never trips it.
_SPEECH_WATCHDOG_MS = 45000

# One physical Ctrl+M / Ctrl+Shift+M can be delivered twice when the toggle
# reparents the composer mid-press. Longer than that echo, shorter than a
# deliberate second chord.
_VOICE_HOTKEY_ECHO_S = 0.12


def voice_restart_notices(
    *,
    listen_wanted: bool,
    listen_live: bool,
    speak_wanted: bool,
    speak_live: bool,
) -> list[str]:
    """One line per direction the running voice service cannot follow.

    VoiceService reads both directions once, at construction, and only wires
    itself to the speech events when speak was on at the time. Everything after
    that is a setting the service never sees: Speak turned on later stays
    silent, Speak turned off later still talks, and Listen turned on later
    answers every utterance with "voice input is off". The switch moves, the
    behaviour does not, and until now nothing said so.
    """
    notices: list[str] = []
    for label, wanted, live in (
        ("Listen", listen_wanted, listen_live),
        ("Speak", speak_wanted, speak_live),
    ):
        if wanted == live:
            continue
        state = "on" if wanted else "off"
        notices.append(
            f"Restart Arelis to finish turning {label} {state} — "
            f"the running voice service still has it {'off' if wanted else 'on'}."
        )
    return notices


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


def _parse_role_set_message(message: str) -> str | None:
    """Extract role name from orchestrator `/role` STATUS text, else None."""
    # "Role set to `research`. New messages use it unless you pick another chip."
    marker = "Role set to `"
    if marker not in message:
        return None
    rest = message.split(marker, 1)[1]
    role, _, _ = rest.partition("`")
    role = role.strip().lower()
    if role in {"fast", "research"}:
        return role
    return None


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
        self.world_window = WorldWindow(self.world_scene, self)
        self.world_window.hide()
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
        self.history.session_selected.connect(self._on_history_selected)
        self.history.session_delete_requested.connect(self._on_history_delete)
        self.history.new_requested.connect(self._on_history_new)
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

    def _reveal_dock(self, dock: QDockWidget, action: QAction | None = None) -> None:
        """Show an instrument once, with the same fade used by the View menu."""
        if getattr(self, "_away_resting", False):
            return
        if dock.isVisible():
            return
        dock.show()
        if action is not None:
            action.setChecked(True)
        self._animate_dock(dock)

    def _on_thinking_status_clicked(self) -> None:
        """The status line is a control: open Thinking, or pulse that plate."""
        # isVisible() is false whenever the parent window is hidden (tests, tray),
        # so the open/closed latch is isHidden() — same as the rest of the UI.
        if not self.think_dock.isHidden():
            self._pulse_thinking_instrument()
            return
        self._reveal_dock(self.think_dock, self.act_thinking)

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
        self.update()
        for frame in self._atmosphere_glass_frames():
            frame.update()

    def _build_voice(self) -> None:
        """Attach the microphone and the speaker, if voice is switched on.

        Each direction is independent. With voice off entirely the controls are
        hidden and none of this is constructed, which is what keeps a machine
        with no sound hardware behaving exactly as it does today.
        """
        self.voice_controller: VoiceController | None = None
        self.speech_player: SpeechPlayer | None = None
        # Wake STT is single-flight: ambient clips must not queue on the Whisper
        # lock ahead of conversation/dictate turns.
        self._wake_inflight = False
        self._wake_generation = 0
        # Mid-utterance provisional STT must not hold Whisper past speech-end.
        self._prov_generation = 0
        # A spoken reply is in flight from the moment the answer lands until
        # synthesis has finished and the player has drained. Both halves are
        # needed. Waiting only for the player reopens the microphone in the gap
        # between two sentences, because clips are rendered one at a time and an
        # empty queue usually means the next one is still in Piper. Waiting only
        # for synthesis reopens it while the last clip is still playing.
        self._speech_expected = False
        self._speech_playing = False
        self._speech_watchdog = QTimer(self)
        self._speech_watchdog.setSingleShot(True)
        self._speech_watchdog.timeout.connect(self._on_speech_watchdog)
        self.utterance_settled.connect(self._on_utterance_settled)
        self.wake_detected.connect(self._on_wake_detected)
        if self.voice is None:
            self.conversation.set_voice_available(False, "")
            return

        if self.voice.stt_enabled:
            controller = VoiceController(self.config, self)
            problem = controller.problem()
            self.conversation.set_voice_available(problem is None, problem or "")
            if problem is None:
                self.voice_controller = controller
                controller.utterance.connect(self._on_utterance)
                controller.provisional.connect(self._on_provisional_pcm)
                controller.status.connect(self._on_voice_status)
                controller.failed.connect(self._on_capture_failed)
                controller.mode_changed.connect(self._on_voice_mode)
                controller.barge_in.connect(self._on_barge_in)
                self._provisional_intent = None
                self.conversation.dictate_toggled.connect(controller.set_dictate)
                self.conversation.conversation_toggled.connect(controller.set_conversation)
                # Always-listen for Hey Arelis until dictate or conversation takes the mic.
                controller.start_wake()
                self._preload_voice()
        else:
            self.conversation.set_voice_available(False, "")

        if self.voice.tts_enabled:
            player = SpeechPlayer(self)
            if player.available():
                voice_cfg = self.config.get("voice") or {}
                player.set_output_device(str(voice_cfg.get("output_device") or ""))
                try:
                    player.set_volume(float(voice_cfg.get("output_volume", 1.0)))
                except (TypeError, ValueError):
                    player.set_volume(1.0)
                self.speech_player = player
                player.started.connect(lambda: self._on_playback(True))
                player.finished.connect(lambda: self._on_playback(False))
                player.failed.connect(self._on_playback_failed)

    # ------------------------------------------------------------------ voice

    def _on_provisional_pcm(self, pcm: bytes, rate: int, channels: int) -> None:
        """Mid-utterance peek: STT for weather/SMS intent only (no turn start)."""
        if self.voice is None or not bool(
            (self.config.get("agent") or {}).get("voice_speculate_preflight", True)
        ):
            return
        target = outputs_dir() / "voice" / f"prov_{uuid4().hex[:8]}.wav"
        try:
            write_wav(target, pcm, sample_rate=rate, channels=channels)
        except OSError:
            return
        generation = self._prov_generation
        future = asyncio.run_coroutine_threadsafe(
            self._ingest_provisional(str(target), generation),
            self.loop,
        )
        future.add_done_callback(
            lambda fut, gen=generation: self._provisional_resolved(fut, gen)
        )

    async def _ingest_provisional(self, path: str, generation: int) -> str:
        from arelis.voice.speculate import provisional_intents

        if self.voice is None:
            return ""
        text = await self.voice.ingest_audio(
            path,
            deliver="wake",
            proceed=lambda: generation == self._prov_generation,
        )
        if generation != self._prov_generation:
            return ""
        intent = provisional_intents(text or "")
        if intent is None:
            return ""
        self._provisional_intent = intent
        await self.bus.publish(
            Event(EventType.STATUS, {"message": intent.summary})
        )
        return intent.summary

    def _provisional_resolved(self, future, generation: int) -> None:
        try:
            summary = future.result()
        except Exception:
            return
        if generation != self._prov_generation:
            return
        if summary:
            try:
                self.thinking.append(str(summary), kind="status")
            except RuntimeError:
                pass

    def _on_utterance(self, pcm: bytes, rate: int, channels: int, deliver: str) -> None:
        """Hand a recorded utterance to the async side.

        The WAV is written here, on the Qt thread, because it is a couple of
        megabytes at most and because the async side must never reach back into
        Qt for the buffer. Everything after this point is the bus's problem:
        the coroutine transcribes off-thread and publishes a transcript, and a
        failure there reports itself rather than stranding a turn.
        """
        if deliver == "wake_oww":
            # Dedicated wake engine already matched — skip Whisper entirely.
            self.wake_detected.emit("")
            return
        if self.voice is None:
            return
        target = outputs_dir() / "voice" / f"capture_{uuid4().hex[:8]}.wav"
        try:
            write_wav(target, pcm, sample_rate=rate, channels=channels)
        except OSError as exc:
            self.chat.add_system(
                f"I could not save the recording. {plain_reason(exc)}"
            )
            self.thinking.append(f"capture write failed: {exc!r}", kind="status")
            self._on_utterance_settled(False)
            return
        if deliver == "wake":
            if self._wake_inflight:
                # Drop the clip rather than queue Whisper behind the last one.
                ctrl = self.voice_controller
                if ctrl is not None:
                    ctrl.trace.record_wake(
                        "wake_drop",
                        reason="inflight",
                        engine="whisper",
                        **ctrl.debug_state(),
                    )
                try:
                    target.unlink(missing_ok=True)
                except OSError:
                    pass
                return
            self._wake_inflight = True
            generation = self._wake_generation
            future = asyncio.run_coroutine_threadsafe(
                self._ingest_wake(str(target), generation),
                self.loop,
            )
            future.add_done_callback(
                lambda fut, gen=generation: self._wake_resolved(fut, gen)
            )
            return
        if deliver != "dictate":
            self.thinking.append("transcribing", kind="status")
        # Conversation/dictate take priority: invalidate any wake or provisional
        # peek still queued on the STT lock so Whisper serves the real clip.
        self._invalidate_wake()
        self._invalidate_provisional()
        future = asyncio.run_coroutine_threadsafe(
            self.voice.ingest_audio(str(target), deliver=deliver),
            self.loop,
        )
        future.add_done_callback(self._utterance_resolved)

    def _invalidate_wake(self) -> None:
        self._wake_generation += 1
        self._wake_inflight = False

    def _invalidate_provisional(self) -> None:
        self._prov_generation += 1
        self._provisional_intent = None

    async def _ingest_wake(self, path: str, generation: int) -> WakeResult | None:
        """Transcribe an idle clip; return wake classification (or None if superseded)."""
        if self.voice is None:
            return None
        text = await self.voice.ingest_audio(
            path,
            deliver="wake",
            proceed=lambda: generation == self._wake_generation,
        )
        if generation != self._wake_generation:
            return None
        return classify_wake(text or "")

    def _wake_resolved(self, future, generation: int) -> None:
        try:
            result = future.result()
        except Exception:
            result = None
        if generation == self._wake_generation:
            self._wake_inflight = False
        if not isinstance(result, WakeResult):
            return
        if generation != self._wake_generation:
            return
        # Trace what Whisper heard so silent misses are diagnosable.
        ctrl = self.voice_controller
        if ctrl is not None:
            ctrl.trace.record_wake(
                "wake_heard",
                matched=result.matched,
                engine="whisper",
                heard=(result.heard or "")[:80],
                remainder=(result.remainder or "")[:80],
                **ctrl.debug_state(),
            )
        try:
            if result.matched:
                self.wake_detected.emit(result.remainder)
            elif result.heard and looks_like_wake_attempt(result.heard):
                # Near-miss: name-ish but regex still failed — tell the operator.
                snippet = result.heard.strip()
                if len(snippet) > 60:
                    snippet = snippet[:57] + "…"
                self.thinking.append(
                    f'heard “{snippet}” — say “Hey Arelis” to wake',
                    kind="status",
                )
        except RuntimeError:
            pass

    def _on_wake_detected(self, remainder: object) -> None:
        """Wake phrase matched. Enter conversation; send remainder if any."""
        self._note_engagement()
        if remainder is None or self.voice_controller is None:
            return
        # Empty string is a valid match (wake-only utterance).
        if not isinstance(remainder, str):
            remainder = str(remainder)
        text = remainder.strip()
        if self.voice is not None:
            self.voice.speak_enabled = True
        self.config["_speak_replies"] = True
        # Sync the two-arcs toggle without re-emitting a false leave.
        btn = self.conversation.conversation_btn
        btn.blockSignals(True)
        btn.setChecked(True)
        btn.blockSignals(False)
        self.conversation.set_conversing(True)
        self.voice_controller.set_conversation(True)
        if self.voice is not None:
            self.voice.speak_enabled = True
        self.conversation.ack_wake()
        self.voice_controller.trace.record_wake(
            "wake_ack",
            engine=getattr(self.voice_controller, "_wake_engine", ""),
            remainder=text[:80],
            **self.voice_controller.debug_state(),
        )
        self.thinking.append("Wake heard — listening.", kind="status")
        if not text:
            return
        # Remainder that is only another wake / punctuation was already peeled.
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": text})),
            self.loop,
        )

    def _utterance_resolved(self, future) -> None:
        """Report back whether the recording produced anything. Async thread."""
        try:
            became_turn = bool(future.result())
        except Exception:
            became_turn = False
        try:
            self.utterance_settled.emit(became_turn)
        except RuntimeError:
            # The window went away while transcription was still running.
            pass

    def _on_utterance_settled(self, became_turn: bool) -> None:
        if became_turn or self.voice_controller is None:
            return
        # No turn will start, so no terminal event is coming. Conversation mode
        # has to be told, or it waits for one forever and stops listening.
        self.voice_controller.notify_utterance_dropped()

    def _preload_voice(self) -> None:
        """Warm Whisper once the asyncio loop is actually running."""
        if self.voice is None or not self.loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self.voice.preload(), self.loop)

    def _on_voice_mode(self, mode: str) -> None:
        self.conversation.set_dictating(mode == "dictate")
        self.conversation.set_conversing(mode == "conversation")
        self._sync_idle_voice_mode(mode)
        if self.voice is not None:
            self.voice.speak_enabled = mode == "conversation"
        # Agent loop reads this to bias spoken answers toward brevity.
        self.config["_speak_replies"] = mode == "conversation"
        if mode in {"dictate", "conversation"}:
            # Drop superseding wake/provisional jobs so they do not hold STT.
            self._invalidate_wake()
            self._invalidate_provisional()
        if mode not in {"off", ""}:
            # Loading Whisper takes tens of seconds the first time. Starting it
            # now means it happens while the user is still talking instead of
            # after they stop.
            self._preload_voice()
        if mode != "conversation":
            self._stop_speech()

    def _on_voice_status(self, message: str) -> None:
        self.thinking.append(message, kind="status")

    def _on_capture_failed(self, message: str) -> None:
        """The microphone side failed, so leave the mode rather than fake it.

        Unchecking the buttons alone used to be a lie: the controller stayed in
        conversation mode holding the device open while the composer showed
        voice as off.
        """
        self.chat.add_system(message)
        self.thinking.append(message, kind="status")
        if self.voice is not None:
            self.voice.speak_enabled = False
        if self.voice_controller is not None:
            self.voice_controller.stop_all()
        self.conversation.set_dictating(False)
        self.conversation.set_conversing(False)

    def _on_playback_failed(self, message: str) -> None:
        """A clip failed to play — abandon speech so conversation can listen again."""
        self.thinking.append(f"playback: {message}", kind="status")
        self._stop_speech()

    def _on_barge_in(self) -> None:
        """Talking over her. Cut playback now. The clip is not a turn.

        Spoken stop / allow / deny on that same clip is a later transcript
        (deliver control). This is the interrupt; that is not a second one.
        """
        self.thinking.append("interrupted", kind="status")
        self._stop_speech()

    def _arm_speech(self) -> None:
        """A spoken reply is in flight (or about to be).

        Armed on ASSISTANT_DONE.speak and on the first VOICE_AUDIO_READY.
        Streaming TTS can produce a clip before the turn ends; arming on the
        first clip covers that. Arming on DONE covers the gap where Piper is
        still rendering and nothing is playing yet, which used to read as
        "she has finished" and reopen the microphone in time to record her
        own opening words.
        """
        if self.voice is None or not self.voice.tts_enabled or not self.voice.speak_enabled:
            return
        if self._speech_expected:
            return
        self._speech_expected = True
        self._trace_voice("speech_armed")
        self._update_speaking()

    def _on_speech_synthesized(self, clips: int) -> None:
        """VOICE_SPEECH_DONE: no more clips are coming for this reply."""
        self._speech_expected = False
        self._trace_voice("speech_synthesized", clips=clips)
        self._update_speaking()

    def _on_playback(self, playing: bool) -> None:
        self._speech_playing = playing
        self._trace_voice("playback")
        self._update_speaking()

    def _update_speaking(self) -> None:
        # Include the player queue so VOICE_SPEECH_DONE cannot reopen the mic in
        # the gap between "synthesis finished" and "first clip starts playing".
        player_busy = self._speech_playing or (
            self.speech_player is not None and self.speech_player.has_work()
        )
        speaking = self._speech_expected or player_busy
        if speaking:
            self._speech_watchdog.start(_SPEECH_WATCHDOG_MS)
        else:
            self._speech_watchdog.stop()
        self.conversation.set_speaking(speaking)
        if self.voice_controller is not None:
            self.voice_controller.notify_speaking(speaking)
        if not speaking:
            self._flush_held_inbound()

    def _on_speech_watchdog(self) -> None:
        player_busy = self.speech_player is not None and self.speech_player.has_work()
        stuck = self._speech_expected or self._speech_playing or player_busy
        if not stuck:
            # Resync in case speaking was latched from a stale has_work read.
            self._update_speaking()
            return
        self.thinking.append("speech never reported finishing; listening again", kind="status")
        self._stop_speech()

    def _stop_speech(self) -> None:
        # Cancelling synthesis matters as much as stopping the player. The
        # player drops the clips it holds, but the service would keep rendering
        # the rest of the answer, and conversation mode stays deaf until that
        # loop reaches its terminal event.
        if self.voice is not None:
            self.voice.cancel_speech()
        if self.speech_player is not None:
            self.speech_player.stop()
        self._speech_expected = False
        self._speech_playing = False
        self._update_speaking()

    def _trace_voice(self, event: str, **fields: Any) -> None:
        if self.voice_controller is None:
            return
        self.voice_controller.trace.record(
            event,
            expect=self._speech_expected,
            playing=self._speech_playing,
            **fields,
            **self.voice_controller.debug_state(),
        )

    def _build_view_actions(self) -> None:
        self.act_thinking = QAction("thinking", self)
        self.act_thinking.setCheckable(True)
        self.act_thinking.setChecked(self.think_dock.isVisible())
        self.act_thinking.setShortcut(QKeySequence("Ctrl+1"))
        self.act_thinking.triggered.connect(self._toggle_thinking)
        self.addAction(self.act_thinking)

        self.act_workspace = QAction("workspace", self)
        self.act_workspace.setCheckable(True)
        self.act_workspace.setChecked(self.work_dock.isVisible())
        self.act_workspace.setShortcut(QKeySequence("Ctrl+2"))
        self.act_workspace.triggered.connect(self._toggle_workspace)
        self.addAction(self.act_workspace)

        self.act_history = QAction("history", self)
        self.act_history.setCheckable(True)
        self.act_history.setChecked(self.history_dock.isVisible())
        self.act_history.setShortcut(QKeySequence("Ctrl+3"))
        self.act_history.triggered.connect(self._toggle_history)
        self.addAction(self.act_history)

        self.act_notifications = QAction("notifications", self)
        self.act_notifications.setCheckable(True)
        self.act_notifications.setChecked(self.notify_inbox.isVisible())
        self.act_notifications.setShortcut(QKeySequence("Ctrl+4"))
        self.act_notifications.triggered.connect(self._toggle_notifications)
        self.addAction(self.act_notifications)
        self._on_notify_unread(self.notify_center.unread_count())

        self.act_camera = QAction("camera", self)
        self.act_camera.setCheckable(True)
        self.act_camera.setChecked(self.camera_dock.isVisible())
        self.act_camera.setShortcut(QKeySequence("Ctrl+5"))
        self.act_camera.triggered.connect(self._toggle_camera)
        self.addAction(self.act_camera)

        self.act_contacts = QAction("contacts", self)
        self.act_contacts.setCheckable(True)
        self.act_contacts.setChecked(self.contacts_inbox.isVisible())
        self.act_contacts.setShortcut(QKeySequence("Ctrl+6"))
        self.act_contacts.triggered.connect(self._toggle_contacts)
        self.addAction(self.act_contacts)

        self.act_calendar = QAction("calendar", self)
        self.act_calendar.setCheckable(True)
        self.act_calendar.setChecked(not self.calendar_window.isHidden())
        self.act_calendar.setShortcut(QKeySequence("Ctrl+7"))
        self.act_calendar.triggered.connect(self._toggle_calendar)
        self.addAction(self.act_calendar)

        self.act_world = QAction("world", self)
        self.act_world.setCheckable(True)
        self.act_world.setChecked(False)
        self.act_world.setShortcut(QKeySequence("Ctrl+8"))
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
        return aw is self or self.isAncestorOf(aw)

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
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(0, 0, -1, -1), _WINDOW_RADIUS, _WINDOW_RADIUS)
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
        if event.type() == QEvent.Type.LayoutRequest:
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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Frameless alone drops OS resize; re-add thick frame after the HWND exists.
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
            elif was_minimized:
                self._unpark_floating_docks()
            self._sync_chrome_state()
            self._apply_round_mask()
            self._clamp_dock_widths()
            if not (self.isMaximized() or self.isFullScreen()):
                enable_win32_resize_frame(self)
            self._sync_notify_surface()

    def nativeEvent(self, eventType, message):
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
        if world_stage_allowed():
            menu.addAction(self.act_world)
        menu.addSeparator()
        menu.addAction(self.act_always_on_top)
        menu.addAction(self.act_fullscreen)
        menu.addSeparator()
        menu.addAction(self.act_shortcuts)
        menu.addAction(self.act_notify_url)
        menu.addAction(self.act_reset)
        # Settings lives on the title-bar button (and Ctrl+,), not in View.
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def _show_rooms_menu(self, anchor) -> None:
        menu = self._build_rooms_menu()
        menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))

    def _build_rooms_menu(self) -> QMenu:
        """Places, not panels. Same enter/leave path as typing or saying it."""
        menu = QMenu(self)
        menu.setObjectName("RoomsMenu")
        store = self.config.get("_rooms")
        rooms = list(store.all()) if store is not None else []
        active = ""
        if store is not None:
            active = str(getattr(store, "active_id", "") or "")
        if not active:
            active = str(getattr(self.conversation.room, "room_id", "") or "")

        if not rooms:
            empty = QAction("no rooms yet", self)
            empty.setEnabled(False)
            menu.addAction(empty)
        else:
            busy = self._turn_busy
            for room in rooms:
                act = QAction(room.name or room.id, self)
                act.setCheckable(True)
                act.setChecked(room.id == active)
                act.setEnabled(not busy)
                if busy:
                    act.setToolTip("Finish or stop the current turn first.")
                elif room.purpose:
                    act.setToolTip(room.purpose)
                act.triggered.connect(
                    lambda _checked=False, rid=room.id: self._enter_room_from_menu(rid)
                )
                menu.addAction(act)
        menu.addSeparator()
        leave = QAction("leave", self)
        leave.setEnabled(bool(active) and not self._turn_busy)
        leave.triggered.connect(self._leave_room)
        menu.addAction(leave)
        return menu

    def _hang_up_conversation(self) -> None:
        """Leave hands-free talk. Wake stays on. The room does not change."""
        btn = self.conversation.conversation_btn
        if btn.isChecked():
            btn.setChecked(False)
        if self.voice_controller is not None:
            self.voice_controller.set_conversation(False)
        self.thinking.append("Listening for Hey Arelis.", kind="status")

    def _enter_room_from_menu(self, room_id: str) -> None:
        if not room_id:
            return
        if self._turn_busy:
            self._toast_finish_or_stop(
                "Finish or stop the current turn before switching rooms."
            )
            return
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.USER_MESSAGE, {"text": f"/room {room_id}"})),
            self.loop,
        )

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self._sync_chrome_state()
        self._apply_round_mask()

    def _toggle_always_on_top(self, checked: bool) -> None:
        self._apply_always_on_top(checked)

    def _apply_always_on_top(self, on: bool, *, persist: bool = True) -> None:
        self._always_on_top = bool(on)
        flags = self.windowFlags()
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        visible = self.isVisible()
        self.setWindowFlags(flags)
        if visible:
            self.show()  # showEvent re-applies WS_THICKFRAME for edge resize
        else:
            enable_win32_resize_frame(self)
        if hasattr(self, "act_always_on_top"):
            self.act_always_on_top.blockSignals(True)
            self.act_always_on_top.setChecked(self._always_on_top)
            self.act_always_on_top.blockSignals(False)
        if persist:
            save_ui_prefs(always_on_top=self._always_on_top)

    def _nudge_chat_font(self, delta: float) -> None:
        self._apply_chat_font_scale(self._chat_font_scale + delta)

    def _apply_chat_font_scale(self, scale: float, *, persist: bool = True) -> None:
        self._chat_font_scale = max(0.75, min(1.75, float(scale)))
        self.chat.set_text_scale(self._chat_font_scale)
        body = max(10, min(24, round(14 * self._chat_font_scale)))
        self.conversation.input.setStyleSheet(f"font-size: {body}px;")
        if persist:
            save_ui_prefs(chat_font_scale=self._chat_font_scale)

    def _on_reach_changed(self, reach: float) -> None:
        self._apply_world_reach(reach)

    def _apply_world_reach(self, reach: float, *, persist: bool = True) -> None:
        self._world_reach = clamp_reach(reach)
        if hasattr(self, "camera"):
            self.camera.set_reach(self._world_reach)
        if persist:
            save_ui_prefs(world_reach=self._world_reach)

    def _open_settings(self, tab: str = "") -> None:
        active_facts: list[dict[str, object]] = []
        if self.store is not None:
            active_facts = self.store.list_facts(status="active", limit=50)
        dlg = SettingsDialog(
            self.config,
            always_on_top=self._always_on_top,
            chat_font_scale=self._chat_font_scale,
            away_rest=self._away_rest,
            away_rest_min=self._away_rest_min,
            active_facts=active_facts,
            parent=self,
            on_test_mic=self._settings_test_mic,
            on_test_speak=self._settings_test_speak,
            on_reset_layout=self._reset_layout,
            initial_tab=tab,
        )
        dlg.applied.connect(self._apply_settings)

        def _on_memory_fact(fact_ids: object, status: str) -> None:
            self._on_fact_decided(fact_ids, status)
            if self.store is not None:
                dlg.set_active_facts(self.store.list_facts(status="active", limit=50))

        dlg.fact_decided.connect(_on_memory_fact)
        dlg.exec()

    def _settings_test_mic(self) -> str:
        if self.voice_controller is not None:
            problem = self.voice_controller.problem()
            if problem:
                return problem
            name = self.voice_controller.device_name() or "microphone"
            return f"Using {name}."
        from arelis.ui.audio import MicRecorder

        voice = self.config.get("voice") or {}
        mic = MicRecorder(
            sample_rate=int((voice.get("stt") or {}).get("sample_rate", 16000)),
            device_hint=str(voice.get("input_device") or ""),
            parent=self,
        )
        problem = mic.problem()
        if problem:
            return problem
        return f"Using {mic.device_name() or 'microphone'}."

    def _settings_test_speak(self) -> None:
        async def _speak() -> None:
            if self.voice is None or not self.voice.tts_enabled:
                raise RuntimeError("Speech is disabled.")
            out = outputs_dir() / "voice" / "settings_test.wav"
            out.parent.mkdir(parents=True, exist_ok=True)
            path = await self.voice.tts.synthesize("Arelis settings test.", out)
            if self.speech_player is None:
                raise RuntimeError("No playback device.")
            self.speech_player.enqueue(path, utterance=0)

        fut = asyncio.run_coroutine_threadsafe(_speak(), self.loop)

        def _done(f) -> None:
            try:
                f.result()
            except Exception as exc:
                self.thinking.append(f"Speak test failed: {exc}", kind="status")

        fut.add_done_callback(_done)

    def _apply_settings(self, values: dict[str, Any]) -> None:
        voice_patch = values.get("voice") or {}
        presence_patch = values.get("presence") or {}
        ui_prefs = values.get("ui_prefs") or {}

        deep_merge(self.config.setdefault("voice", {}), {
            k: v for k, v in voice_patch.items() if k not in {"stt", "tts"}
        })
        if "stt" in voice_patch:
            stt_cfg = self.config.setdefault("voice", {}).setdefault("stt", {})
            deep_merge(stt_cfg, voice_patch["stt"])
        if "tts" in voice_patch:
            tts_cfg = self.config.setdefault("voice", {}).setdefault("tts", {})
            deep_merge(tts_cfg, voice_patch["tts"])
        if presence_patch:
            deep_merge(self.config.setdefault("presence", {}), presence_patch)
            if "close_to_tray" in presence_patch:
                self._close_to_tray = bool(presence_patch["close_to_tray"])

        merge_local_config(
            {
                "voice": {
                    "enabled": bool(voice_patch.get("enabled", True)),
                    "input_device": str(voice_patch.get("input_device") or ""),
                    "output_device": str(voice_patch.get("output_device") or ""),
                    "output_volume": float(voice_patch.get("output_volume", 1.0)),
                    "stt": {"enabled": bool((voice_patch.get("stt") or {}).get("enabled", True))},
                    "tts": {"enabled": bool((voice_patch.get("tts") or {}).get("enabled", True))},
                },
                "presence": {
                    "close_to_tray": bool(presence_patch.get("close_to_tray", True)),
                },
            }
        )

        notify_patch = (values.get("ui") or {}).get("notifications") or {}
        if notify_patch:
            deep_merge(
                self.config.setdefault("ui", {}).setdefault("notifications", {}),
                notify_patch,
            )
            merge_local_config({"ui": {"notifications": notify_patch}})
            self.notify_center.set_config(self.config)
            self._sync_notify_surface()

        agent_patch = values.get("agent") or {}
        if agent_patch:
            deep_merge(self.config.setdefault("agent", {}), agent_patch)
            merge_local_config({"agent": dict(agent_patch)})
            self._schedule_readiness_probe()

        workspace_patch = values.get("workspace") or {}
        if "roots" in workspace_patch:
            self._apply_workspace_roots(list(workspace_patch.get("roots") or []))

        if self.voice_controller is not None and "input_device" in voice_patch:
            self.voice_controller.set_input_device(str(voice_patch.get("input_device") or ""))
        if self.speech_player is not None:
            if "output_device" in voice_patch:
                self.speech_player.set_output_device(str(voice_patch.get("output_device") or ""))
            if "output_volume" in voice_patch:
                try:
                    self.speech_player.set_volume(float(voice_patch["output_volume"]))
                except (TypeError, ValueError):
                    pass

        if "always_on_top" in ui_prefs:
            self._apply_always_on_top(bool(ui_prefs["always_on_top"]))
        if "chat_font_scale" in ui_prefs:
            self._apply_chat_font_scale(float(ui_prefs["chat_font_scale"]))
        if "away_rest" in ui_prefs or "away_rest_min" in ui_prefs:
            if "away_rest" in ui_prefs:
                self._away_rest = bool(ui_prefs["away_rest"])
            if "away_rest_min" in ui_prefs:
                self._away_rest_min = clamp_away_rest_min(ui_prefs["away_rest_min"])
            save_ui_prefs(
                away_rest=self._away_rest,
                away_rest_min=self._away_rest_min,
            )
            if not self._away_rest and self._away_resting:
                self._wake_from_away_rest()
            else:
                self._arm_away_rest_timer()

        # Soft-apply listen/speak availability without a full restart when possible.
        master = bool((self.config.get("voice") or {}).get("enabled", True))
        if master and self.voice is None:
            self.thinking.append(
                "Restart Arelis to load voice hardware after enabling Voice.",
                kind="status",
            )
        if self.voice is not None:
            stt_on = bool((self.config.get("voice") or {}).get("stt", {}).get("enabled", True))
            tts_on = bool((self.config.get("voice") or {}).get("tts", {}).get("enabled", True))
            for notice in voice_restart_notices(
                listen_wanted=master and stt_on,
                listen_live=bool(self.voice.stt_enabled),
                speak_wanted=master and tts_on,
                speak_live=bool(self.voice.tts_enabled),
            ):
                self.thinking.append(notice, kind="status")
            if not master or not stt_on:
                if self.voice_controller is not None:
                    self.voice_controller.stop_all()
                self.conversation.set_voice_available(False, "Voice listen is off in Settings.")
            elif self.voice_controller is not None:
                self.conversation.set_voice_available(True, "")
                self.voice_controller.resume_wake()
            if not master or not tts_on:
                self._stop_speech()

    def _apply_workspace_roots(
        self,
        roots: list[dict[str, object]],
        *,
        preferred_active: str | None = None,
    ) -> None:
        """Persist named roots to config.local.yaml and hot-refresh the shared sandbox."""
        if not roots:
            self.thinking.append("Keep at least one workspace root.", kind="status")
            return
        try:
            named = _parse_workspace_roots(roots)
        except Exception as exc:
            self.thinking.append(f"Workspace roots rejected: {exc}", kind="status")
            return
        merge_local_config({"workspace": {"roots": named}})
        entries = [
            RootEntry(
                name=str(item["name"]),
                path=Path(str(item["path"])).resolve(),
                read_only=bool(item.get("read_only", False)),
            )
            for item in named
        ]
        want = preferred_active or self.workspace_roots.active
        try:
            self.workspace_roots.replace_roots(entries, preferred_active=want)
        except Exception as exc:
            self.thinking.append(f"Workspace roots update failed: {exc}", kind="status")
            return
        self.config.setdefault("workspace", {})
        self.config["workspace"]["named_roots"] = named
        self.config["workspace"]["roots"] = [entry["path"] for entry in named]
        self.config["_workspace"] = self.workspace_roots
        self.workspace.set_projects(
            self.workspace_roots.names(),
            self.workspace_roots.active,
            paths={r.name: str(r.path) for r in self.workspace_roots.roots},
        )
        self.thinking.append(
            f"Workspace roots updated ({len(entries)}): "
            + ", ".join(self.workspace_roots.names()),
            kind="status",
        )

    def _workspace_root_dicts(self) -> list[dict[str, object]]:
        return [
            {
                "name": entry.name,
                "path": str(entry.path),
                "read_only": bool(entry.read_only),
            }
            for entry in self.workspace_roots.roots
        ]

    @staticmethod
    def _unique_root_name(base: str, taken: set[str]) -> str:
        name = (base or "project").strip() or "project"
        # Config keys should stay path-safe and qualifier-friendly.
        cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name)
        cleaned = cleaned.strip("-_") or "project"
        if cleaned not in taken:
            return cleaned
        n = 2
        while f"{cleaned}-{n}" in taken:
            n += 1
        return f"{cleaned}-{n}"

    def _register_workspace_folder(self, path: Path, *, make_active: bool = True) -> None:
        try:
            resolved = path.expanduser().resolve()
        except OSError as exc:
            self.thinking.append(f"Could not resolve folder: {exc}", kind="status")
            return
        if not resolved.is_dir():
            self.thinking.append(f"Not a folder: {resolved}", kind="status")
            return
        for entry in self.workspace_roots.roots:
            if entry.path.resolve() == resolved:
                self.workspace_roots.set_active(entry.name)
                self.workspace.set_active_project(entry.name)
                self.thinking.append(
                    f"Already a root — active project `{entry.name}`.",
                    kind="status",
                )
                return
        taken = set(self.workspace_roots.names())
        name = self._unique_root_name(resolved.name, taken)
        roots = self._workspace_root_dicts()
        roots.append({"name": name, "path": str(resolved), "read_only": False})
        self._apply_workspace_roots(
            roots, preferred_active=name if make_active else None
        )

    def _add_workspace_folder_dialog(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        start = str(Path.home() / "Documents")
        chosen = QFileDialog.getExistingDirectory(
            self, "Add folder to workspace", start
        )
        if chosen:
            self._register_workspace_folder(Path(chosen), make_active=True)

    def _new_workspace_folder_dialog(self) -> None:
        from PySide6.QtWidgets import QFileDialog, QInputDialog

        start = str(Path.home() / "Documents")
        parent = QFileDialog.getExistingDirectory(
            self, "Parent folder for new project", start
        )
        if not parent:
            return
        name, ok = QInputDialog.getText(self, "New folder", "Folder name:")
        if not ok:
            return
        folder_name = (name or "").strip()
        if not folder_name:
            self.thinking.append("Folder name required.", kind="status")
            return
        target = Path(parent) / folder_name
        try:
            target.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            self.thinking.append(f"Already exists: {target}", kind="status")
            return
        except OSError as exc:
            self.thinking.append(f"Could not create folder: {exc}", kind="status")
            return
        self._register_workspace_folder(target, make_active=True)

    def _remove_active_workspace_root(self) -> None:
        if len(self.workspace_roots) <= 1:
            self.thinking.append("Keep at least one workspace root.", kind="status")
            return
        active = self.workspace_roots.active
        roots = [r for r in self._workspace_root_dicts() if r["name"] != active]
        next_active = str(roots[0]["name"]) if roots else None
        self._apply_workspace_roots(roots, preferred_active=next_active)
        self.thinking.append(
            f"Removed `{active}` from the workspace (files untouched on disk).",
            kind="status",
        )

    def _toggle_thinking(self, checked: bool) -> None:
        self._note_engagement()
        self.think_dock.setVisible(checked)
        if checked:
            self._animate_dock(self.think_dock)

    def _toggle_workspace(self, checked: bool) -> None:
        self._note_engagement()
        self.work_dock.setVisible(checked)
        if checked:
            self._animate_dock(self.work_dock)

    def _toggle_history(self, checked: bool) -> None:
        self._note_engagement()
        self.history_dock.setVisible(checked)
        if checked:
            self._refresh_history()
            self._animate_dock(self.history_dock)
        self._stack_left_instruments()

    def _toggle_notifications(self, checked: bool) -> None:
        self._note_engagement()
        if checked:
            self._on_notify_poll()
            self.notify_inbox.show()
            self.notify_inbox.raise_()
            self.notifications.opened.emit()
        else:
            self.notify_inbox.hide()

        self._sync_notify_surface()
        self._sync_idle_mode()

    def _toggle_camera(self, checked: bool) -> None:
        self._note_engagement()
        self.camera_dock.setVisible(checked)
        if checked:
            self.camera.start()
            self._animate_dock(self.camera_dock)
        else:
            self.camera.stop()
        self._stack_left_instruments()

    def _toggle_contacts(self, checked: bool) -> None:
        self._note_engagement()
        if checked:
            self.contacts.show_list()
            self.contacts_inbox.show()
            self.contacts_inbox.raise_()
        else:
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
        else:
            self.calendar_window.hide()
            self._calendar_sync_timer.stop()
            self._calendar_sync_watchdog.stop()
        self._sync_idle_mode()

    def _open_world(self) -> None:
        self.act_world.setChecked(True)
        self._toggle_world(True)

    def _toggle_world(self, checked: bool) -> None:
        self._note_engagement()
        if not world_stage_allowed():
            self.act_world.setChecked(False)
            if checked:
                self.thinking.append(
                    "World is a source-checkout stage — not in the installer.",
                    kind="status",
                )
            return
        if checked:
            if self.conversation.room.room_id != PHYSICS_ROOM_ID:
                self.act_world.setChecked(False)
                self.thinking.append(
                    "World is the physics room. Say let's work on physics first.",
                    kind="status",
                )
                return
            if not getattr(self, "_world_placed", False):
                geo = self.frameGeometry()
                self.world_window.move(geo.x() + 48, geo.y() + 48)
                self._world_placed = True
            self.world_window.show()
            self.world_window.raise_()
            self.world_window.show_chooser()
            self.world_window.panel.refresh()
        else:
            self.world_window.hide()
        self._sync_idle_mode()

    def _hide_world(self) -> None:
        self.world_scene.reset()
        if hasattr(self, "world_depth"):
            self.world_depth.reset()
        if hasattr(self, "world_window"):
            self.world_window.hide()
            self.world_window.panel.refresh()
        if hasattr(self, "act_world"):
            self.act_world.setChecked(False)

    def _try_physics_verb(self, text: str) -> bool:
        """Closed lexicon in this room. True when it must not start a turn."""
        if self.conversation.room.room_id != PHYSICS_ROOM_ID:
            return False
        verb = classify_physics_verb(text)
        if not verb:
            return False
        self._apply_physics_verb(verb)
        return True

    def _apply_physics_verb(self, verb: str) -> None:
        from arelis.physics.runtime import get_system

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
                system.set_rate(1.0)
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
                "No discs in the solar lab. Spawn a particle, belt tracer, or L4 from "
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

    def _apply_tile(self, name: str, *, show: bool) -> None:
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
        toggle(show)

    def _run_ui_call(self, fn) -> None:
        if getattr(self, "_disposed", False) or getattr(self, "_force_quit", False):
            return
        if callable(fn):
            fn()

    def _calendar_service(self):
        from arelis.calendar.service import CalendarService

        return CalendarService(self.config)

    def _run_calendar(self, coro, *, ok_status: str = "google · just now") -> None:
        if getattr(self, "_disposed", False) or getattr(self, "_force_quit", False):
            coro.close()
            return
        if not self.loop.is_running():
            coro.close()
            return
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def _done() -> None:
            try:
                fut.result()
            except Exception as exc:
                from arelis.ui.dialog import notice

                self.calendar.set_status("sync failed", failed=True)
                notice(
                    self,
                    "calendar",
                    "Google did not take that change.",
                    detail=plain_reason(exc),
                    warning=True,
                )
                return
            self.calendar.reload()
            self.calendar.set_status(ok_status)

        fut.add_done_callback(lambda _f: self._ui_call.emit(_done))

    def _kick_calendar_sync(self) -> None:
        if self._force_quit or self._disposed:
            return
        if self.calendar_window.isHidden():
            return
        self.calendar.reload()
        if getattr(self, "_calendar_sync_inflight", False):
            return
        from arelis.calendar.secrets import load_calendar_secrets

        if not load_calendar_secrets().any_authorized():
            self.calendar.set_status("authorize google")
            return
        if not self.loop.is_running():
            return
        self._calendar_sync_inflight = True
        self.calendar.set_status("syncing…")
        self._calendar_sync_watchdog.start(int(self._calendar_sync_timeout_ms))
        fut = asyncio.run_coroutine_threadsafe(
            self._calendar_service().sync(), self.loop
        )

        def _done() -> None:
            try:
                if getattr(self, "_disposed", False) or getattr(self, "_force_quit", False):
                    return
                try:
                    summary = fut.result()
                except Exception as exc:
                    self.calendar.set_status("sync failed", failed=True)
                    self._report_poll_state(
                        "calendar_tile", f"Calendar sync stopped: {plain_reason(exc)}"
                    )
                    return
                self._report_poll_state("calendar_tile", "")
                self.calendar.reload()
                if summary.get("ok"):
                    names = [
                        name
                        for name, info in (summary.get("providers") or {}).items()
                        if info.get("ok")
                    ]
                    self.calendar.set_status(
                        f"{', '.join(names) or 'calendar'} · just now"
                    )
                else:
                    err = "; ".join(summary.get("errors") or []) or "sync failed"
                    self.calendar.set_status("sync failed", failed=True)
                    from arelis.ui.dialog import notice

                    notice(
                        self,
                        "calendar",
                        "Could not refresh the calendar.",
                        detail=err,
                        warning=True,
                    )
            finally:
                self._calendar_sync_inflight = False
                timer = getattr(self, "_calendar_sync_watchdog", None)
                if timer is not None:
                    try:
                        timer.stop()
                    except RuntimeError:
                        pass

        fut.add_done_callback(lambda _f: self._ui_call.emit(_done))

    def _on_calendar_sync_watchdog(self) -> None:
        if self._force_quit or self._disposed:
            self._calendar_sync_inflight = False
            return
        if not getattr(self, "_calendar_sync_inflight", False):
            return
        self._calendar_sync_inflight = False
        self.calendar.set_status("sync failed", failed=True)

    def _on_calendar_create(self, payload: dict[str, Any]) -> None:
        self._run_calendar(
            self._calendar_service().create(
                summary=str(payload.get("summary") or ""),
                starts_at=payload["starts_at"],
                ends_at=payload.get("ends_at"),
                all_day=bool(payload.get("all_day")),
                location=str(payload.get("location") or ""),
                description=str(payload.get("description") or ""),
                provider=str(payload.get("provider") or "") or None,
                calendar_id=str(payload.get("calendar_id") or "") or None,
            ),
            ok_status="created",
        )

    def _on_calendar_update(self, payload: dict[str, Any]) -> None:
        event_id = str(payload.get("event_id") or "")
        if not event_id:
            return
        self._run_calendar(
            self._calendar_service().update(
                event_id,
                summary=str(payload.get("summary") or ""),
                starts_at=payload.get("starts_at"),
                ends_at=payload.get("ends_at"),
                all_day=bool(payload.get("all_day")),
                location=str(payload.get("location") or ""),
                description=str(payload.get("description") or ""),
                provider=str(payload.get("provider") or "") or None,
                calendar_id=str(payload.get("calendar_id") or "") or None,
            ),
            ok_status="updated",
        )

    def _on_calendar_delete(self, event_id: str) -> None:
        from arelis.ui.dialog import confirm

        if not confirm(
            self,
            "delete event",
            "Remove this from Google Calendar?",
            confirm_text="Delete",
            destructive=True,
        ):
            return
        ev = None
        try:
            ev = self._calendar_service().get(event_id)
        except Exception:
            ev = None
        self._run_calendar(
            self._calendar_service().delete(
                event_id,
                provider=ev.provider if ev else None,
                calendar_id=ev.calendar_id if ev else None,
            ),
            ok_status="deleted",
        )

    def _on_calendar_task_add(self, title: str, due: str) -> None:
        if self.store is None:
            return
        try:
            self.store.add_task(title, due=due or None, source="explicit")
        except Exception as exc:
            from arelis.ui.dialog import notice

            notice(self, "tasks", "Could not add that task.", detail=str(exc), warning=True)
            return
        from arelis.core.bus import emit_nowait

        emit_nowait(Event(EventType.TASKS_CHANGED, {"action": "add"}))
        self.calendar.reload_tasks()

    def _on_calendar_task_status(self, task_id: int, status: str) -> None:
        if self.store is None:
            return
        self.store.set_task_status(task_id, status)
        from arelis.core.bus import emit_nowait

        emit_nowait(Event(EventType.TASKS_CHANGED, {"action": status, "id": task_id}))
        self.calendar.reload_tasks()

    def _on_calendar_task_remove(self, task_id: int) -> None:
        from arelis.ui.dialog import confirm

        if self.store is None:
            return
        existing = self.store.get_task(task_id)
        label = str((existing or {}).get("title") or "this task")
        if not confirm(
            self,
            "remove task",
            f"Remove {label}?",
            confirm_text="Remove",
            destructive=True,
        ):
            return
        self.store.remove_task(task_id)
        from arelis.core.bus import emit_nowait

        emit_nowait(Event(EventType.TASKS_CHANGED, {"action": "remove", "id": task_id}))
        self.calendar.reload_tasks()

    def _reveal_calendar_jobs(self) -> None:
        self.act_calendar.setChecked(True)
        self._toggle_calendar(True)
        self.calendar.show_jobs_tab()
        self.calendar.reload_jobs()

    def _on_calendar_job_save(self, payload: dict[str, Any]) -> None:
        from arelis.tools.schedule_jobs import save_job_from_payload
        from arelis.ui.dialog import notice

        result = save_job_from_payload(payload)
        if not result.ok:
            notice(
                self,
                "jobs",
                "Could not save that job.",
                detail=str(result.output),
                warning=True,
            )
            return
        job_id = str((result.data or {}).get("id") or "")
        self.calendar.reload_jobs(select_id=job_id)
        if result.data and result.data.get("registered") is False:
            notice(
                self,
                "jobs",
                "Saved, but Windows would not register it.",
                detail=str(result.output),
                warning=True,
            )

    def _on_calendar_job_delete(self, job_id: str) -> None:
        from arelis.jobs.store import get_job
        from arelis.tools.schedule_jobs import ScheduleTool
        from arelis.ui.dialog import confirm, notice

        job = get_job(job_id)
        label = job.name if job else job_id
        if not confirm(
            self,
            "delete job",
            f"Stop {label} and remove it from Windows?",
            confirm_text="Delete",
            destructive=True,
        ):
            return
        result = ScheduleTool()._delete(job_id)
        if not result.ok:
            notice(
                self,
                "jobs",
                "Could not delete that job.",
                detail=str(result.output),
                warning=True,
            )
            return
        self.calendar.reload_jobs()

    def _on_calendar_job_run(self, job_id: str) -> None:
        from arelis.tools.schedule_jobs import ScheduleTool
        from arelis.ui.dialog import notice

        result = ScheduleTool()._run_now(job_id)
        if not result.ok:
            notice(
                self,
                "jobs",
                "Could not start that job.",
                detail=str(result.output),
                warning=True,
            )
            return
        self.calendar.jobs_page.set_note("Started. The result will arrive by email.")

    def _on_contacts_inbox_closed(self) -> None:
        self.act_contacts.setChecked(False)
        self._sync_idle_mode()

    def _on_calendar_window_closed(self) -> None:
        self.act_calendar.setChecked(False)

    def _on_world_window_closed(self) -> None:
        self.act_world.setChecked(False)
        self._calendar_sync_timer.stop()
        self._calendar_sync_watchdog.stop()
        self._sync_idle_mode()

    def _on_notify_unread(self, count: int) -> None:
        if count > 0:
            self.act_notifications.setText(f"notifications ({count})")
        else:
            self.act_notifications.setText("notifications")

    def _on_notify_inbox_closed(self) -> None:
        self.act_notifications.setChecked(False)
        self._sync_notify_surface()
        self._sync_idle_mode()

    def _on_inbox_opened(self) -> None:
        self._sync_notify_surface()

    def _on_notify_mark_all_read(self) -> None:
        self.notify_center.clear_non_sticky()
        self._sync_notify_surface()

    def _on_notice_activated(self, notice_id: str) -> None:
        notice = self.notify_center.find(notice_id)
        if notice is not None and notice.unread:
            self.notify_center.mark_read(notice_id)
            self._sync_notify_surface()
        self.notifications.show_notice(notice_id)

    def _on_camera_dock_visibility(self, visible: bool) -> None:
        if chrome_applying(self.camera_dock):
            return
        if visible:
            self.camera.start()
        else:
            self.camera.stop()
        self._refresh_camera_capture_hook()

    def _on_camera_running_changed(self, _running: bool) -> None:
        self._refresh_camera_capture_hook()

    def _on_camera_track(self, on: bool) -> None:
        if on:
            if not getattr(self.camera, "_running", False):
                self.camera.start()
            ok = self.spatial.start_track(
                {"device": self.camera.current_device_name()}
            )
            if not ok:
                self.camera.track_btn.blockSignals(True)
                self.camera.track_btn.setChecked(False)
                self.camera.track_btn.blockSignals(False)
            return
        self.spatial.stop_track()
        self.camera.set_hands(())

    def _on_camera_record(self, on: bool) -> None:
        if on:
            path = self.spatial.start_record(
                {
                    "device": self.camera.current_device_name(),
                    "gravity": GRAVITY,
                    "rung": 3,
                    "estimator": ESTIMATOR,
                }
            )
            if path is None:
                self.camera.record_btn.blockSignals(True)
                self.camera.record_btn.setChecked(False)
                self.camera.record_btn.blockSignals(False)
            return
        self.spatial.stop_record()

    def _on_camera_pose(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 4:
            return
        rgb, t_capture, width, height = payload
        self.spatial.submit_frame(rgb, t_capture, width, height)

    def _on_camera_pose_video(self, frame: object, t_capture: float) -> None:
        self.spatial.submit_video(frame, t_capture)

    def _on_spatial_recording(self, on: bool) -> None:
        if self.camera.record_btn.isChecked() == on:
            return
        self.camera.record_btn.blockSignals(True)
        self.camera.record_btn.setChecked(on)
        self.camera.record_btn.blockSignals(False)

    def _hand_depth(self, who: str, hand: object, stamp: float, frame: object) -> float | None:
        """Palm-pinhole z, or none if the frame has no size."""
        if hand is None or not hasattr(self, "world_depth"):
            return None
        width = int(getattr(frame, "width", 0) or 0)
        height = int(getattr(frame, "height", 0) or 0)
        if width < 1 or height < 1:
            return None
        return self.world_depth.observe(
            who, hand, t=stamp, width=width, height=height
        )

    def _on_spatial_hands(self, frame: object) -> None:
        if frame is None:
            self._closed_off.clear()
            self.camera.set_hands(())
            if hasattr(self, "world_depth"):
                self.world_depth.reset()
            self.world_scene.drop(t=time.perf_counter())
            if hasattr(self, "world_window") and not self.world_window.isHidden():
                self.world_window.panel.clear_hand()
            return
        hands = getattr(frame, "hands", ())
        state = str(getattr(self.spatial, "last_state", "") or "idle")
        fps = float(getattr(self.spatial, "last_fps", 0.0) or 0.0)
        tracks = tuple(getattr(self.spatial, "last_tracks", ()) or ())
        closed_kinds: dict[str, str] = {}
        overlay_hands = list(hands)
        for track in tracks:
            st = str(getattr(track, "state", "") or "")
            who = str(getattr(track, "who", "") or "")
            if who and st in ("fist", "pinch"):
                closed_kinds[who] = st
            held = getattr(track, "hand", None)
            if (
                getattr(track, "coasting", False)
                and held is not None
                and not any(h is held for h in overlay_hands)
            ):
                overlay_hands.append(held)
        self.camera.set_hands(
            tuple(overlay_hands),
            closed=bool(closed_kinds),
            state=state,
            fps=fps,
            closed_kinds=closed_kinds,
        )
        world_up = hasattr(self, "world_window") and not self.world_window.isHidden()
        solar = world_up and self.world_window.solar_active()
        reach = getattr(self, "_world_reach", REACH_DEFAULT)
        stamp = float(getattr(frame, "t_capture", time.perf_counter()))
        apertures: list[tuple[tuple[float, float], tuple[float, float], bool]] = []
        alive: set[str] = set()
        ordered = sorted(
            tracks,
            key=lambda track: (
                0
                if str(getattr(track, "state", "") or "") in ("fist", "pinch")
                else 1,
                0
                if getattr(track, "who", "") == "Left"
                else 1
                if getattr(track, "who", "") == "Right"
                else 2,
                str(getattr(track, "who", "")),
            ),
        )
        for track in ordered:
            who = str(getattr(track, "who", "") or "")
            hand = getattr(track, "hand", None)
            st = str(getattr(track, "state", "") or "idle")
            held = self.world_scene.held_names()
            if who in held and st in ("fist", "pinch"):
                alive.add(who)
            if getattr(track, "coasting", False):
                if who in held and st in ("fist", "pinch"):
                    alive.add(who)
                    if self.world_scene.is_flicking(who):
                        self.world_scene.drop(t=stamp, who=who)
                        alive.discard(who)
                        continue
                    # Last closed pose still drives the ball. Skipping
                    # apply_pointer here was the freeze-then-jump.
                else:
                    continue
            if hand is None:
                if who:
                    self._closed_off.pop(who, None)
                if who in held:
                    self.world_scene.drop(t=stamp, who=who)
                elif who:
                    self.world_scene.forget_pending(who)
                continue
            thumb, index = hand.pinch_tips()
            holding = st in ("fist", "pinch")
            centroid, off = grab_drive(
                hand, closed=holding, offset=self._closed_off.get(who)
            )
            if who and off is not None:
                self._closed_off[who] = off
            elif who:
                self._closed_off.pop(who, None)
            tw, ti = image_to_world(*thumb, reach=reach), image_to_world(*index, reach=reach)
            cw = image_to_world(*centroid, reach=reach)
            if not solar:
                self.world_scene.apply_pointer(
                    cw[0],
                    cw[1],
                    holding,
                    t=stamp,
                    who=who,
                    kind=st if holding else "open",
                    z=self._hand_depth(who, hand, stamp, frame),
                )
            if st == "fist":
                apertures.append((cw, cw, True))
            elif st == "pinch":
                apertures.append((tw, ti, True))
            else:
                apertures.append((tw, ti, False))
        live = {
            str(getattr(track, "who", "") or "")
            for track in ordered
            if getattr(track, "hand", None) is not None
        }
        if tracks:
            self.world_scene.forget_absent(live, t=stamp)
        if not tracks and hands:
            hand = hands[0]
            holding = state in ("fist", "pinch", "both")
            kind = "fist" if state in ("fist", "both") else "pinch" if state == "pinch" else "open"
            centroid, off = grab_drive(
                hand, closed=holding, offset=self._closed_off.get("")
            )
            if off is not None:
                self._closed_off[""] = off
            else:
                self._closed_off.pop("", None)
            cw = image_to_world(*centroid, reach=reach)
            if not solar:
                self.world_scene.apply_pointer(
                    cw[0],
                    cw[1],
                    holding,
                    t=stamp,
                    kind=kind,
                    z=self._hand_depth("", hand, stamp, frame),
                )
            if holding and kind == "fist":
                apertures.append((cw, cw, True))
            elif holding:
                thumb, index = hand.pinch_tips()
                apertures.append(
                    (
                        image_to_world(*thumb, reach=reach),
                        image_to_world(*index, reach=reach),
                        True,
                    )
                )
            else:
                thumb, index = hand.pinch_tips()
                apertures.append(
                    (
                        image_to_world(*thumb, reach=reach),
                        image_to_world(*index, reach=reach),
                        False,
                    )
                )
        if self.world_scene.bodies:
            for body in self.world_scene.bodies:
                if (
                    body.attached
                    and body.holder
                    and body.holder not in alive
                    and not any(
                        str(getattr(track, "who", "") or "") == body.holder
                        for track in tracks
                    )
                ):
                    self.world_scene.drop(t=stamp, who=body.holder)
        if not hands and not tracks:
            self.world_scene.drop(t=stamp)
            if world_up:
                self.world_window.panel.clear_hand()
            return
        if world_up:
            if solar:
                if apertures:
                    (t0, i0, pinched) = apertures[0]
                    mx = (t0[0] + i0[0]) * 0.5
                    my = (t0[1] + i0[1]) * 0.5
                    span = math.hypot(t0[0] - i0[0], t0[1] - i0[1])
                    z = None
                    if tracks:
                        hand0 = getattr(ordered[0], "hand", None) if ordered else None
                        who0 = str(getattr(ordered[0], "who", "") or "") if ordered else ""
                        if hand0 is not None:
                            z = self._hand_depth(who0, hand0, stamp, frame)
                    self.world_window.solar.apply_hand(
                        mx, my, pinched=pinched, span=span, palm_z=z
                    )
                else:
                    self.world_window.solar.apply_hand(
                        0.5, 0.5, pinched=False, span=0.0, palm_z=None
                    )
            else:
                self.world_window.panel.set_apertures(apertures)

    def _refresh_camera_capture_hook(self) -> None:
        """Expose live capture to the camera tool while the dock session is up."""
        if getattr(self.camera, "_running", False):
            self.config["_camera_capture"] = self.camera.snapshot_blocking
        else:
            self.config.pop("_camera_capture", None)

    def _on_camera_ask(self, path: str) -> None:
        """Dock Ask Arelis: submit a look-on-ask turn naming the snapshot path."""
        path_text = display_path(path)
        text = (
            f"Look at the camera frame at {path_text}. What do you see?"
        )
        if not self.camera_dock.isVisible():
            self.camera_dock.show()
            self.camera_dock.raise_()
        self.conversation.input.setFocus()
        role = str(self._current_role or "fast")
        self._on_submit(text, role)

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

    def _on_dock_visibility(self, visible: bool) -> None:
        # Ignore the transient hide that setWindowFlags causes while swapping
        # floating chrome — otherwise View checks flip off and the panel vanishes.
        # _arelis_parked is the same kind of bookkeeping: the glass went to the
        # tray or the taskbar and took its floating panels with it, which is not
        # the user turning an instrument off.
        sender = self.sender()
        if isinstance(sender, QDockWidget) and (
            chrome_applying(sender) or getattr(sender, "_arelis_parked", False)
        ):
            return
        self._sync_view_checks()
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
        """Orbit face: empty thread, nothing to decide. Docks may stay open."""
        if self.chat.has_messages:
            return False
        if self._turn_busy:
            return False
        if self.conversation.confirm_open():
            return False
        # Stay on the orbit while dictate/talk is latched on an empty thread.
        # Leaving idle here reparented the voice buttons and unchecked
        # Ctrl+Shift+M (conversation on, then immediately wake).
        overlay = self.conversation.notify_overlay
        if overlay is not None and overlay.expanded:
            return False
        return True

    def _sync_idle_mode(self) -> None:
        idle = self._idle_eligible()
        self.conversation.set_idle_mode(idle)
        instruments = any(
            not dock.isHidden()
            for dock in (
                self.think_dock,
                self.work_dock,
                self.history_dock,
                self.camera_dock,
            )
        ) or (not self.notify_inbox.isHidden()) or (not self.contacts_inbox.isHidden()) or (
            not self.calendar_window.isHidden()
        ) or (not self.world_window.isHidden())
        self.readiness_strip.setVisible(not idle or instruments)
        empty = getattr(self.chat, "empty", None)
        if empty is not None and hasattr(empty, "set_side_chrome"):
            empty.set_side_chrome(
                ghosts=idle
                and self.history_dock.isHidden()
                and self.camera_dock.isHidden(),
                readout=idle and not self.readiness_strip.isVisible(),
            )
        self._refresh_idle_face()

    def _return_to_idle(self) -> None:
        """Esc on an empty thread: close instruments and show Orbit."""
        if self.chat.has_messages:
            return
        self.think_dock.hide()
        self.work_dock.hide()
        self.history_dock.hide()
        self.camera_dock.hide()
        self.calendar_window.hide()
        self._hide_world()
        self._calendar_sync_timer.stop()
        self._calendar_sync_watchdog.stop()
        self.notify_inbox.hide()
        self.contacts_inbox.hide()
        overlay = self.conversation.notify_overlay
        if overlay is not None and overlay.expanded:
            overlay.collapse()
        self._away_resting = False
        self._away_hidden = {}
        self.conversation.input.clear()
        self._sync_idle_mode()

    def _away_rest_blocked(self) -> bool:
        if self._turn_busy:
            return True
        if self.conversation.confirm_open():
            return True
        if self.conversation.conversation_btn.isChecked():
            return True
        if self.conversation.mic_btn.isChecked():
            return True
        if self._drive_session:
            return True
        return False

    def _arm_away_rest_timer(self) -> None:
        timer = getattr(self, "_away_timer", None)
        if timer is None:
            return
        if not self._away_rest or self._away_resting:
            timer.stop()
            return
        timer.start(max(1, int(self._away_rest_min)) * 60 * 1000)

    def _note_engagement(self) -> None:
        """A real use: click, type, send, wake, Allow — not mouse-move or STATUS."""
        if self._away_resting:
            self._wake_from_away_rest()
            return
        self._arm_away_rest_timer()

    def _enter_away_rest(self) -> None:
        if not self._away_rest or self._away_resting:
            return
        if self._away_rest_blocked():
            self._arm_away_rest_timer()
            return
        hidden = {
            "thinking": not self.think_dock.isHidden(),
            "workspace": not self.work_dock.isHidden(),
            "history": not self.history_dock.isHidden(),
            "camera": not self.camera_dock.isHidden(),
            "calendar": not self.calendar_window.isHidden(),
            "notify": not self.notify_inbox.isHidden(),
            "contacts": not self.contacts_inbox.isHidden(),
        }
        if not any(hidden.values()):
            return
        self._away_hidden = hidden
        self._away_resting = True
        self.think_dock.hide()
        self.work_dock.hide()
        self.history_dock.hide()
        self.camera_dock.hide()
        self.calendar_window.hide()
        self._hide_world()
        self._calendar_sync_timer.stop()
        self._calendar_sync_watchdog.stop()
        self.notify_inbox.hide()
        self.contacts_inbox.hide()
        if hidden.get("camera"):
            try:
                self.camera.stop()
            except Exception:
                pass
        overlay = self.conversation.notify_overlay
        if overlay is not None and overlay.expanded:
            overlay.collapse()
        self._away_timer.stop()
        self._sync_idle_mode()

    def _wake_from_away_rest(self) -> None:
        if not self._away_resting:
            self._arm_away_rest_timer()
            return
        hidden = dict(self._away_hidden)
        self._away_resting = False
        self._away_hidden = {}
        if hidden.get("thinking"):
            self.think_dock.show()
        if hidden.get("workspace"):
            self.work_dock.show()
        if hidden.get("history"):
            self.history_dock.show()
            self._refresh_history()
        if hidden.get("camera"):
            self.camera_dock.show()
            self.camera.start()
        if hidden.get("calendar"):
            self.calendar_window.show()
            self.calendar_window.raise_()
            self.calendar.reload()
            self._kick_calendar_sync()
            self._calendar_sync_timer.start()
        if hidden.get("notify"):
            self.notify_inbox.show()
            self.notify_inbox.raise_()
        if hidden.get("contacts"):
            self.contacts_inbox.show()
            self.contacts_inbox.raise_()
        self._stack_left_instruments()
        self._sync_idle_mode()
        self._arm_away_rest_timer()

    def _persist_window_layout(self) -> None:
        """Write geometry. Rest must not persist a collapsed window."""
        if self._away_resting:
            self._wake_from_away_rest()
        save_window_layout(self)

    def _on_idle_readiness(self, snapshot) -> None:
        self._readiness_snap = snapshot
        # The world-state line wants to know whether a picture can be made, and
        # this probe already asked. Parking the answer on the config keeps the
        # question off the per-turn path, which is no place for a socket.
        chip = snapshot.chip("image") if hasattr(snapshot, "chip") else None
        if chip is not None:
            self.config["_image_ready"] = chip.status == ChipLevel.OK
        self._refresh_idle_face()

    def _sync_idle_voice_mode(self, mode: str | None = None) -> None:
        """Idle copy under the orbit follows the latched voice mode.

        Falls back to the buttons when the controller has not reported yet, so a
        chord that latched conversation before the mic opened still shows.
        """
        idle = getattr(self.chat, "empty", None)
        if idle is None or not hasattr(idle, "set_voice_mode"):
            return
        if mode is None:
            if self.conversation.conversation_btn.isChecked():
                mode = "conversation"
            elif self.conversation.mic_btn.isChecked():
                mode = "dictate"
            else:
                # Cosmetic copy under the orbit. It runs from _refresh_idle_face,
                # which every terminal event goes through, so it must not be able
                # to raise: an idle label is not worth losing ASSISTANT_DONE and
                # leaving the composer stuck in its busy state.
                mode_fn = getattr(self.voice_controller, "mode", None)
                mode = mode_fn() if callable(mode_fn) else "off"
        idle.set_voice_mode(mode or "off")

    def _refresh_idle_face(self) -> None:
        idle = getattr(self.chat, "empty", None)
        if idle is None or not hasattr(idle, "set_sessions"):
            return
        self._sync_idle_voice_mode()
        sessions = self.history.recent_sessions(3)
        if sessions != self._idle_ghosts:
            self._idle_ghosts = sessions
            idle.set_sessions(sessions)
        ollama = "—"
        snap = self._readiness_snap
        if snap is not None:
            chip = snap.chip("ollama") if hasattr(snap, "chip") else None
            if chip is not None:
                ollama = str(chip.status.value).upper()
        listening = "OFF"
        vc = getattr(self, "voice_controller", None)
        if vc is not None and bool(getattr(vc, "listening", False)):
            listening = "ON"
        elif (
            self.conversation.mic_btn.isChecked()
            or self.conversation.conversation_btn.isChecked()
        ):
            listening = "ON"
        idle.set_readout(ollama=ollama, listening=listening)

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
        display = text or (
            f"({len(attachments)} attachment{'s' if len(attachments) != 1 else ''})"
            if attachments
            else ""
        )
        self.chat.add_user(text, attachments=attachments)
        self._sync_idle_mode()
        self.thinking.append(display, kind="trace")
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
        model = str((self.config.get("models") or {}).get(role) or self._current_model or "")
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
        ok, output = await execute_pending_confirm(item, self.config)
        await self.bus.publish(
            Event(
                EventType.STATUS,
                {
                    "message": (
                        output if ok else f"Pending send failed: {output}"
                    )
                },
            )
        )
        await self.bus.publish(
            Event(
                EventType.TOOL_RESULT,
                {
                    "tool": item.tool,
                    "ok": ok,
                    "output": output,
                    "data": {},
                    "source": "pending_confirm",
                },
            )
        )

    def _set_confirm_pending(self, pending: bool) -> None:
        self.readiness_strip.set_confirm_waiting(pending)
        if self.voice_controller is not None:
            self.voice_controller.notify_confirm_pending(pending)
        if not pending:
            self._flush_held_inbound()

    def _set_busy(self, busy: bool) -> None:
        self._turn_busy = busy
        self.conversation.set_busy(busy)
        self.history.set_switch_enabled(not busy)
        # Every turn status hangs off this one flag, so no shimmer can outlive the
        # turn that started it — including the turns that end at the watchdog
        # rather than at an answer.
        if busy:
            self.chat.show_progress(THINKING_STATUS)
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

    def _refresh_history(self) -> None:
        if self.store is None:
            return
        sessions = [
            {
                "id": str(row.get("id") or ""),
                "started_at": str(row.get("started_at") or ""),
                "title": str(row.get("title") or ""),
            }
            for row in self.store.list_sessions(limit=100)
        ]
        self.history.set_sessions(sessions)
        self.history.set_pending_facts(self.store.list_facts(status="pending", limit=50))
        if self.store.session_id:
            self.history.set_active(self.store.session_id)
        self._refresh_idle_face()

    def _on_fact_decided(self, fact_ids: object, status: str) -> None:
        """Approve/reject pending (History) or forget active (Settings → Memory)."""
        if self.store is None:
            return
        if status not in {"active", "rejected"}:
            return
        if isinstance(fact_ids, int):
            ids = [fact_ids]
        elif isinstance(fact_ids, (list, tuple)):
            ids = [int(x) for x in fact_ids]
        else:
            return
        changed = 0
        for fact_id in ids:
            if self.store.set_fact_status(fact_id, status):
                changed += 1
        if not changed:
            return
        label = "approved" if status == "active" else "rejected"
        if changed == 1:
            self.thinking.append(f"fact {label}", kind="status")
        else:
            self.thinking.append(f"{changed} facts {label}", kind="status")
        self._refresh_history()

    def _on_history_selected(self, session_id: str) -> None:
        if self._turn_busy:
            self._toast_finish_or_stop(
                "Finish or stop the current turn before switching conversations."
            )
            return
        self._request_session_load(session_id)

    def _on_history_delete(self, session_id: str) -> None:
        if self.store is None:
            return
        if self._turn_busy:
            self._toast_finish_or_stop(
                "Finish or stop the current turn before deleting a conversation."
            )
            return
        sid = str(session_id or "").strip()
        if not sid:
            return
        was_active = self.store.session_id == sid
        if not self.store.delete_session(sid):
            self.chat.add_system("Could not delete that conversation.")
            return
        self.thinking.append("Conversation deleted.", kind="status")
        self._refresh_history()
        if was_active:
            asyncio.run_coroutine_threadsafe(
                self.bus.publish(Event(EventType.SESSION_LOAD, {"new": True})),
                self.loop,
            )

    def _on_history_new(self) -> None:
        if self._turn_busy:
            self._toast_finish_or_stop(
                "Finish or stop the current turn before starting a new conversation."
            )
            return
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.SESSION_LOAD, {"new": True})),
            self.loop,
        )

    def _toast_finish_or_stop(self, message: str) -> None:
        """Single amber toast per busy episode (debounce L3 spam)."""
        now = time.monotonic()
        last = float(getattr(self, "_finish_stop_toast_at", 0.0) or 0.0)
        if now - last < 1.5:
            return
        self._finish_stop_toast_at = now
        self.chat.add_system(message)

    def _request_session_load(self, session_id: str) -> None:
        if not session_id:
            return
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.SESSION_LOAD, {"session_id": session_id})),
            self.loop,
        )

    def _leave_room(self) -> None:
        """The strip's leave button, routed through the same command as typing.

        Publishing the command rather than reaching for the orchestrator keeps
        the window free of a reference to it, the way session loads already do,
        and means both routes out of a room share one implementation.
        """
        if self._turn_busy:
            self._toast_finish_or_stop(
                "Finish or stop the current turn before leaving the room."
            )
            return
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.USER_MESSAGE, {"text": "/leave"})),
            self.loop,
        )

    def _open_file(self, path: str) -> None:
        if not path:
            self.chat.add_system(
                "open needs a path — pick a file or type one under the workspace roots"
            )
            return
        self._reveal_dock(self.work_dock, self.act_workspace)
        try:
            hit = self.workspace_roots.resolve_read(path)
        except Exception as exc:
            self.chat.add_system(f"I could not open that file. {plain_reason(exc)}")
            self.thinking.append(f"open failed: {exc!r}", kind="status")
            return
        if not hit.path.is_file():
            label = hit.qualified(multi=len(self.workspace_roots) > 1)
            self.chat.add_system(f"Not a file: {label}")
            return
        try:
            text = hit.path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            self.chat.add_system(f"I could not read that file. {plain_reason(exc)}")
            self.thinking.append(f"open failed: {exc!r}", kind="status")
            return
        label = hit.qualified(multi=len(self.workspace_roots) > 1)
        if self.workspace.has_unsaved_changes():
            # Opening a file replaces the buffer, so an open on top of unsaved
            # edits is a discard. It stays possible — it is what the operator
            # clicked — but it says so once first, since the edits are about to
            # be gone with no undo behind them.
            if self._workspace_discard_armed != str(hit.path):
                self._workspace_discard_armed = str(hit.path)
                self.chat.add_system(
                    f"Unsaved changes in {self.workspace.loaded_label()}. "
                    f"Save them first, or press open again to discard them and load {label}."
                )
                return
        self._workspace_discard_armed = ""
        self.workspace.set_file(
            label, text, root_name=hit.root_name, abs_path=str(hit.path), force=True
        )
        self.workspace.set_recent(push_recent_workspace_file(label))
        self.thinking.append(f"workspace open {label}", kind="status")

    def _disk_moved_under_editor(self, target: Path, content: str) -> bool:
        """True when target changed since the editor loaded it, and not to this text.

        Only the file the editor is actually holding can be stale — a save to
        any other path is a plain write with nothing to lose.
        """
        loaded = self.workspace.loaded_abs()
        if not loaded or str(target) != loaded or not target.is_file():
            return False
        try:
            on_disk = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return on_disk != self.workspace.baseline_text() and on_disk != content

    def _save_file(self, path: str, content: str) -> None:
        if not path:
            self.chat.add_system("save needs a path")
            return
        self._reveal_dock(self.work_dock, self.act_workspace)
        try:
            hit = self.workspace_roots.resolve(path, for_create=True, for_write=True)
        except Exception as exc:
            self.chat.add_system(f"I could not save there. {plain_reason(exc)}")
            self.thinking.append(f"save failed: {exc!r}", kind="status")
            return
        label = hit.qualified(multi=len(self.workspace_roots) > 1)
        if self._disk_moved_under_editor(hit.path, content):
            # The other half of the clobber: she edited the file after it was
            # opened, so this save carries a buffer that predates her work and
            # would drop it. Overwriting is allowed, once it is a decision.
            if self._workspace_overwrite_armed != str(hit.path):
                self._workspace_overwrite_armed = str(hit.path)
                self.chat.add_system(
                    f"{label} changed on disk after you opened it — saving now would "
                    "overwrite that version. Press save again to overwrite it, or open "
                    "the file again to load what is on disk."
                )
                return
        self._workspace_overwrite_armed = ""
        try:
            hit.path.parent.mkdir(parents=True, exist_ok=True)
            hit.path.write_text(content, encoding="utf-8")
        except OSError as exc:
            self.chat.add_system(f"I could not save that file. {plain_reason(exc)}")
            self.thinking.append(f"save failed: {exc!r}", kind="status")
            return
        self.workspace.set_file(
            label, content, root_name=hit.root_name, abs_path=str(hit.path), force=True
        )
        self.workspace.set_recent(push_recent_workspace_file(label))
        self.thinking.append(f"workspace saved {label}", kind="status")
        self.chat.add_system(f"Saved {label}")

    def _on_event(self, event: Event) -> None:
        """Render one bus event. Runs on the Qt thread via BusBridge.

        ASSISTANT_DONE and ERROR are the only two events that clear the busy
        state, so the orchestrator guarantees one of them per turn. Everything
        else here is presentation.
        """
        t = event.type
        p = event.payload
        if t == EventType.USER_MESSAGE:
            # Typed messages are already on screen: _on_submit paints them
            # before publishing. A spoken one has no such moment, so this is
            # where the user first sees what she heard, and where the turn is
            # marked busy. Busy is set here rather than at the end of the
            # recording on purpose: if transcription fails there is no turn, so
            # there would be no terminal event to release the composer.
            # Phone talk uses the same path: the companion is not the glass.
            if p.get("source") in {"voice", "mobile"}:
                text = p.get("text") or ""
                attachments = p.get("attachments") if p.get("source") == "mobile" else None
                self._mobile_foreign = p.get("source") == "mobile" and bool(
                    p.get("foreign")
                )
                if not self._mobile_foreign:
                    self.chat.add_user(text, attachments=list(attachments or []) or None)
                    self.thinking.append(text, kind="trace")
                self._set_busy(True)
                if p.get("source") == "voice":
                    prov = getattr(self, "_provisional_intent", None)
                    if prov is not None:
                        from arelis.voice.speculate import speculation_matches_final

                        if not speculation_matches_final(prov, text):
                            self.thinking.append(
                                "Provisional hear cancelled (final transcript differed).",
                                kind="status",
                            )
                        self._provisional_intent = None
        elif t == EventType.VOICE_TRANSCRIPT:
            # Dictation never becomes a turn. It lands in the composer for the
            # user to edit and send themselves.
            if p.get("deliver") == "dictate":
                self.conversation.insert_dictation(p.get("text") or "")
        elif t == EventType.PHYSICS_VERB:
            # Closed verbs never publish USER_MESSAGE, so conversation would
            # wait for a turn that does not exist. Drop the awaiting latch
            # the same way an empty transcript does, then mutate the scene.
            if self.voice_controller is not None:
                self.voice_controller.notify_utterance_dropped()
            self._apply_physics_verb(str(p.get("verb") or ""))
        elif t == EventType.CONVERSATION_END:
            # Spoken hangup. Same latch as Ctrl+Shift+M off: the two-arcs
            # button, speak_replies, and wake listen. No turn starts.
            if self.voice_controller is not None:
                self.voice_controller.notify_utterance_dropped()
            self._hang_up_conversation()
        elif t == EventType.VOICE_AUDIO_READY:
            # Streaming TTS can deliver the first clip before ASSISTANT_DONE.
            # Arm here so the mic stays deaf across that early Piper work too.
            if not self._speech_expected:
                self._arm_speech()
            # Each clip is proof that synthesis is still making progress, which
            # is what keeps the speech watchdog from firing during a long answer.
            if self._speech_expected:
                self._speech_watchdog.start(_SPEECH_WATCHDOG_MS)
            if self.speech_player is not None:
                self.speech_player.enqueue(
                    str(p.get("path") or ""), int(p.get("utterance") or 0)
                )
        elif t == EventType.VOICE_SPEECH_DONE:
            self._on_speech_synthesized(int(p.get("clips") or 0))
        elif t == EventType.ASSISTANT_DELTA:
            if self._mobile_foreign:
                return
            self._clear_model_loading()
            # Keep the status line until the answer is finished. Clearing it on
            # the first token made tool turns flash: a preamble hid "thinking…",
            # then retract put it back. Tool copy still replaces this line.
            self.conversation.set_turn_visible(True)
            if not self._assistant_streaming:
                self.chat.begin_assistant()
                self._assistant_streaming = True
            self.chat.append_delta(p.get("text", ""))
        elif t == EventType.ASSISTANT_RETRACT:
            if self._mobile_foreign:
                return
            # The round turned out to be a tool call, so what was on screen was
            # a preamble. The agent loop mirrors it into the thinking dock.
            # Drop any speech that streamed from that preamble.
            self.chat.discard_stream()
            # This is the moment the thread empties itself, and the one that made
            # three spoken SMS turns look dead. Something has to remain.
            if self._turn_busy:
                self.chat.show_progress(THINKING_STATUS)
            self._assistant_streaming = False
            self._stop_speech()
        elif t == EventType.ASSISTANT_DONE:
            if self._mobile_foreign:
                self._assistant_streaming = False
                self._mobile_foreign = False
                self._set_busy(False)
                self._refresh_history()
                return
            # Repaint from the payload rather than the accumulated deltas: it is
            # the authoritative answer, and it is the version that has the
            # Sources list appended. finish_assistant is idempotent when the
            # same body was already finalized (voice race with _close_stream).
            self._clear_model_loading()
            text = p.get("text") or ""
            if self._assistant_streaming:
                self.chat.finish_assistant(text)
            elif text:
                self.chat.finish_assistant(text)
            self._assistant_streaming = False
            # Do not dismiss an SMS auto-reply card just because a chat turn
            # finished: those confirms live outside the agent loop.
            confirm_id = self.conversation.confirm._confirm_id
            if not str(confirm_id).startswith("sms-auto-"):
                self.conversation.dismiss_confirm()
                self._set_confirm_pending(False)
            # Arm speech before clearing busy, not after. Both feed the same
            # decision in the voice controller, and clearing busy first leaves a
            # window where the turn is over and no reply is pending, which is
            # exactly the state that means "start listening again".
            if p.get("speak"):
                self._arm_speech()
            self._set_busy(False)
            self._refresh_history()
        elif t == EventType.MOBILE_SYNC:
            sid = str(p.get("session_id") or "")
            current = str(getattr(self.store, "session_id", "") or "")
            if sid and current and sid != current:
                return
            rows = p.get("messages") or []
            if isinstance(rows, list) and rows:
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    role = str(row.get("role") or "")
                    text = str(row.get("text") or "")
                    if role == "user" and text:
                        self.chat.add_user(text)
                    elif role == "assistant" and text:
                        self.chat.finish_assistant(text)
        elif t == EventType.SESSION_LOADED:
            if p.get("silent"):
                return
            if not p.get("ok"):
                self.chat.add_system(str(p.get("error") or "Could not load that conversation."))
                return
            self._assistant_streaming = False
            self.conversation.dismiss_confirm()
            self._set_confirm_pending(False)
            self.thinking.clear()
            messages = p.get("messages") or []
            if isinstance(messages, list):
                self.chat.load_messages(
                    [
                        {
                            "role": str(m.get("role") or ""),
                            "content": str(m.get("content") or ""),
                            "note": str(m.get("note") or ""),
                        }
                        for m in messages
                        if isinstance(m, dict)
                    ]
                )
            else:
                self.chat.clear()
            sid = str(p.get("session_id") or "")
            self._refresh_history()
            if sid:
                self.history.set_active(sid)
            self._drive_session = False
            self.conversation.set_drive(False)
            if p.get("new"):
                self.thinking.append("new conversation", kind="status")
            elif sid:
                self.thinking.append(f"loaded conversation {sid[:8]}", kind="status")
            # Re-surface in thinking after clear/load. This line is not a
            # conversation; painting it into chat used to hide the orbit.
            if self._inbound_banner:
                self.thinking.append(self._inbound_banner, kind="status")
            self._sync_idle_mode()
        elif t == EventType.ROOM_CHANGED:
            room_id = str(p.get("room_id") or "")
            self.conversation.room.set_room(
                room_id,
                name=str(p.get("name") or ""),
                purpose=str(p.get("purpose") or ""),
                root=str(p.get("root") or ""),
            )
            # The room owns a project, so the dock's switcher has to follow or
            # the two disagree about where a bare path lands.
            self.workspace.set_active_project(self.workspace_roots.active)
            self.camera.set_spatial_available(
                room_id == PHYSICS_ROOM_ID and world_stage_allowed()
            )
            self.spatial.set_room(room_id)
            if room_id != PHYSICS_ROOM_ID:
                self._hide_world()
            self.thinking.append(
                f"room  {room_id or 'general'}", kind="status"
            )
            self._sync_idle_mode()
        elif t == EventType.CALENDAR_CHANGED:
            if not self.calendar_window.isHidden():
                self.calendar.reload()
        elif t == EventType.TASKS_CHANGED:
            if not self.calendar_window.isHidden():
                self.calendar.reload_tasks()
        elif t == EventType.JOBS_CHANGED:
            if not self.calendar_window.isHidden():
                self.calendar.reload_jobs(select_id=str(p.get("id") or ""))
        elif t == EventType.THINKING:
            text = str(p.get("text") or "")
            if p.get("stream"):
                self.thinking.extend_stream(text)
            else:
                self.thinking.append(text, kind="trace")
            self._reveal_dock(self.think_dock, self.act_thinking)
        elif t == EventType.STATUS:
            msg = p.get("message", "")
            self.thinking.append(msg, kind="status")
            # Inbound listen/token belongs in thinking, not chat. A system
            # line here used to mark the thread as started and hide the orbit
            # on a cold launch the operator never typed into.
            if str(msg).startswith(("Inbound notify", "Phone notifications")):
                self._inbound_banner = str(msg)
            if msg.startswith("Active project set to"):
                self.workspace.set_active_project(self.workspace_roots.active)
            # /role ack: keep the composer pill in sync with the default role.
            role_set = _parse_role_set_message(str(msg))
            if role_set:
                self._current_role = role_set
                self.conversation.role.blockSignals(True)
                self.conversation.role.setCurrentText(role_set)
                self.conversation.role.blockSignals(False)
            self._schedule_readiness_probe()
        elif t == EventType.MODEL_SWITCH:
            self._current_model = p.get("to") or self._current_model
            self._current_role = p.get("role") or self._current_role
            self.thinking.append(
                f"{p.get('from')} → {p.get('to')} ({p.get('role')})",
                kind="model",
            )
            self._schedule_readiness_probe()
        elif t == EventType.TOOL_CONFIRM:
            if self._mobile_foreign:
                return
            self.conversation.ask_confirm(
                str(p.get("id") or ""),
                str(p.get("tool") or ""),
                str(p.get("summary") or ""),
                detail=str(p.get("detail") or ""),
                note=str(p.get("note") or ""),
                batch_ok=bool(p.get("batch_ok", True)),
                headline=str(p.get("headline") or ""),
            )
            self._set_confirm_pending(True)
            # The turn is blocked on a person, not working. Shimmering "writing
            # the text…" over an Allow card describes the wrong side of the wait.
            if self._turn_busy:
                self.chat.show_progress(WAITING_STATUS)
            self.conversation.set_turn_visible(True)
            self._reveal_dock(self.think_dock, self.act_thinking)
            self.thinking.append(f"allow  {p.get('headline') or p.get('summary')}", kind="tool")
        elif t == EventType.TOOL_CONFIRM_REPLY:
            # Timeout / remote skip — dismiss the open card if it matches.
            cid = str(p.get("id") or "")
            open_id = str(self.conversation.confirm._confirm_id or "")
            if cid and cid == open_id:
                self.conversation.dismiss_confirm()
                self._set_confirm_pending(False)
                if p.get("reason") == "timeout":
                    self.thinking.append("confirm timed out — denied", kind="status")
                elif p.get("reason") == "voice":
                    said = "allow" if p.get("decision") == "allow" else "deny"
                    self.thinking.append(f"voice {said}", kind="status")
        elif t == EventType.TOOL_START:
            tool = p.get("tool")
            args = p.get("args") or {}
            # Short args for thinking — never dump file bodies
            brief = {k: (str(v)[:60] + "…" if len(str(v)) > 60 else v) for k, v in args.items()}
            self.thinking.append(f"{tool} {brief}", kind="tool")
            if str(tool or "") == "workspace" and isinstance(args, dict):
                self._workspace_tool_args = dict(args)
            # Said in the transcript, in the user's words, whether or not the
            # Thinking dock is open. `weather {'days': 2}` is for me; "checking
            # the weather" is for her.
            self.chat.show_progress(tool_status_line(str(tool or ""), args))
            self.conversation.set_turn_visible(True)
            self._reveal_dock(self.think_dock, self.act_thinking)
            # File / image work surfaces the workspace band (Pass C).
            if str(tool or "") in {
                "workspace",
                "analyze",
                "image",
                "research_report",
                "doc_extract",
                "ocr",
            }:
                self._reveal_dock(self.work_dock, self.act_workspace)
            # The shimmer is set for every tool now, so image needs no special
            # case beyond its own Thinking line.
            if str(tool or "") == "image":
                self.thinking.append("Generating image…", kind="status")
            if str(tool or "") in {"image", "research_report"}:
                self._begin_job(str(tool))
            if str(tool or "") == "browser":
                action = str(args.get("action") or "")
                self._drive_session = True
                self.conversation.set_drive(True, format_drive_status(action, args))
        elif t == EventType.TOOL_RESULT:
            self.thinking.append(f"ok={p.get('ok')} {p.get('tool')}", kind="tool")
            # Back to the bare waiting state: the errand is over but the turn is
            # not, and leaving "checking the weather…" up would be a small lie
            # that runs for the rest of the round.
            if self._turn_busy:
                self.chat.show_progress(THINKING_STATUS)
            data = p.get("data") or {}
            intro = str(data.get("intro") or "").strip()
            if p.get("tool") == "agenda" and p.get("ok") and data.get("open"):
                self.act_calendar.setChecked(True)
                self._toggle_calendar(True)
            if p.get("tool") == "agenda" and p.get("ok") and data.get("close"):
                self.act_calendar.setChecked(False)
                self._toggle_calendar(False)
            if p.get("tool") == "schedule" and p.get("ok"):
                self._reveal_calendar_jobs()
                job_id = str(data.get("id") or "")
                if job_id:
                    self.calendar.reload_jobs(select_id=job_id)
            if p.get("tool") == "tile" and p.get("ok"):
                self._apply_tile(
                    str(data.get("name") or ""),
                    show=bool(data.get("open")) and not data.get("close"),
                )
            if p.get("tool") == "browser":
                if intro:
                    self.chat.add_system(intro)
                code = str(data.get("code") or "")
                wall = str(data.get("wall") or "")
                if code in {"YOUR_TURN", "SECRET_FIELD"}:
                    kind = wall or ("login" if code == "SECRET_FIELD" else "")
                    line = your_turn_status(kind)
                    self.conversation.set_drive_your_turn(line)
                    note = ""
                    for raw in str(p.get("output") or "").splitlines():
                        if raw.strip().lower().startswith("your turn"):
                            note = raw.strip()
                            break
                    self.chat.add_system(note or "Your turn — the page stays.")
                    self.thinking.append(f"your turn  {kind or code}", kind="status")
                else:
                    out = str(p.get("output") or "").strip()
                    if out:
                        self.conversation.set_drive_status(out.splitlines()[0][:80])
            if p.get("tool") in {"image", "image_edit"}:
                if p.get("ok"):
                    self.chat.add_system("Image ready — open in Workspace")
                else:
                    self.chat.add_system(
                        tool_failure_notice("image", str(p.get("output") or ""))
                    )
            if str(p.get("tool") or "") in {"image", "research_report"}:
                self._finish_job(
                    str(p.get("tool") or "job"),
                    ok=bool(p.get("ok")),
                    output=str(p.get("output") or ""),
                )
            if p.get("tool") == "send_sms" and p.get("ok"):
                self.sms_chats.append_outbound(
                    body=str(data.get("body") or ""),
                    alias=str(data.get("alias") or ""),
                    phone=str(data.get("phone") or ""),
                )
            if p.get("tool") in {"workspace", "analyze"}:
                payload_args = p.get("args") if isinstance(p.get("args"), dict) else {}
                action = str(
                    payload_args.get("action")
                    or self._workspace_tool_args.get("action")
                    or ""
                )
                out = str(p.get("output") or "")
                status = status_for_tool_result(
                    str(p.get("tool") or ""),
                    ok=bool(p.get("ok")),
                    action=action,
                    output=out,
                )
                if status:
                    self.workspace.append_output(status)
                if not p.get("ok") and out:
                    # Wrong/empty path used to look like a silent Open no-op, so
                    # the failure still reaches chat. It goes through the copy
                    # boundary first: "Not a file: C:/typo.csv" is the whole
                    # answer and passes through, while analyze's own advice to
                    # the model — "Call vision(path=…) for an image" — does not.
                    self.chat.add_system(
                        tool_failure_notice(str(p.get("tool") or ""), str(out))
                    )
                    self._reveal_dock(self.work_dock, self.act_workspace)
            if p.get("tool") == "workspace" and p.get("ok"):
                payload_args = p.get("args") if isinstance(p.get("args"), dict) else {}
                action = str(
                    payload_args.get("action")
                    or self._workspace_tool_args.get("action")
                    or ""
                )
                display = str(data.get("path") or "")
                abs_path = str(data.get("abs_path") or "")
                root_name = str(data.get("root_name") or "")
                if is_workspace_listing(action, str(p.get("output") or ""), abs_path):
                    self.workspace.browse_to(abs_path, root_name=root_name)
                    self._reveal_dock(self.work_dock, self.act_workspace)
                elif display:
                    read_from = abs_path or display
                    target = Path(read_from)
                    if target.is_dir():
                        self.workspace.browse_to(read_from, root_name=root_name)
                        self._reveal_dock(self.work_dock, self.act_workspace)
                    elif target.is_file():
                        try:
                            content = Path(read_from).read_text(
                                encoding="utf-8", errors="replace"
                            )
                            placed = self.workspace.set_file(
                                display, content, root_name=root_name, abs_path=abs_path
                            )
                            if placed:
                                self.workspace.set_recent(
                                    push_recent_workspace_file(display)
                                )
                            else:
                                self.chat.add_system(
                                    f"I wrote {display}, but you have unsaved edits open in the "
                                    "editor, so I left them alone. Open the file again to see my "
                                    "version — that replaces what is in the editor."
                                )
                            self._reveal_dock(self.work_dock, self.act_workspace)
                        except Exception as exc:
                            # The write landed; only the editor refresh did not. Saying
                            # nothing leaves the same impression the clobber bug did —
                            # that the file on screen is the file on disk.
                            self.chat.add_system(
                                f"I wrote {display}, but could not read it back into the "
                                f"editor: {plain_reason(exc)}. The version on disk is mine; "
                                "open the file again to see it."
                            )
                            self.thinking.append(
                                f"workspace read-back failed: {exc}", kind="status"
                            )
                    else:
                        # ok=True naming a path that is neither a file nor a
                        # directory. The editor cannot move, and staying quiet
                        # reads the same way the clobber bug did: whatever is on
                        # screen looks like what is on disk.
                        self.chat.add_system(
                            f"I reported writing {display}, but could not read it "
                            "back — nothing is at that path now. Treat the write as "
                            "failed and check the file before relying on it."
                        )
                        self.thinking.append(
                            f"workspace read-back failed: {read_from} is not on disk",
                            kind="status",
                        )
            if p.get("tool") == "workspace":
                self._workspace_tool_args = {}
        elif t == EventType.IMAGE_READY:
            path = p.get("path")
            if path:
                self.workspace.show_image(path)
                self.workspace.append_output(f"Image ready — {Path(str(path)).name}")
                self._reveal_dock(self.work_dock, self.act_workspace)
        elif t == EventType.FILE_READY:
            abs_path = str(p.get("abs_path") or p.get("path") or "").strip()
            name = str(p.get("title") or "").strip()
            if not name and abs_path:
                name = Path(abs_path).name
            if abs_path and p.get("show_card", True):
                self.chat.add_file_card(name or Path(abs_path).name, abs_path)
            if abs_path and p.get("open"):
                try:
                    open_local_file(abs_path)
                except OSError as exc:
                    leaf = Path(abs_path).name or "that file"
                    self.chat.add_system(
                        f"I could not open {leaf}. {plain_reason(exc)}"
                    )
            if abs_path and p.get("reveal"):
                try:
                    reveal_local_file(abs_path)
                except OSError as exc:
                    leaf = Path(abs_path).name or "that file"
                    self.chat.add_system(
                        f"I could not show {leaf}. {plain_reason(exc)}"
                    )
        elif t == EventType.SMS_RECEIVED:
            self._on_sms_received(p)
        elif t == EventType.TURN_CANCEL:
            # Voice stop publishes cancel from the orchestrator. The stop
            # button publishes it too — skip the echo so we do not double-cut.
            if self._ignore_cancel_echo:
                self._ignore_cancel_echo = False
            else:
                self._apply_stop_ui(publish_confirm_skip=False)
                if not self._force_quit and not self._disposed:
                    self._later(0, self._show_next_pending_confirm)
        elif t == EventType.TURN_PAUSE:
            if str(p.get("reason") or "") == "your_turn":
                kind = str(p.get("kind") or "")
                self.conversation.set_drive_your_turn(your_turn_status(kind))
        elif t == EventType.TURN_RESUME:
            if str(p.get("reason") or "") == "wall_cleared":
                self.conversation.set_drive_paused(False)
                self.conversation.set_drive_status("continuing…")
                self.thinking.append("wall gone — continuing", kind="status")
        elif t == EventType.ERROR:
            if self._mobile_foreign:
                self._mobile_foreign = False
                if p.get("scope") != "voice":
                    self._assistant_streaming = False
                    self._set_busy(False)
                return
            message = p.get("message", "Error")
            # The publisher's own split: `message` is for the person, `detail` is
            # the exception. Thinking used to get the chat line twice over and the
            # detail nowhere, so the one place with room for it showed the least.
            detail = str(p.get("detail") or "").strip()
            self.chat.add_system(message)
            self.thinking.append(message, kind="status")
            if detail and detail != message:
                self.thinking.append(detail, kind="status")
            # A voice failure happens outside any turn. Ending the turn on it
            # would re-enable the composer and dismiss a confirm card that the
            # agent loop is still waiting on, stranding the turn for good.
            if p.get("scope") != "voice":
                self._assistant_streaming = False
                self.conversation.dismiss_confirm()
                self._set_confirm_pending(False)
                self._stop_speech()
                self._set_busy(False)

    def _on_sms_received(self, payload: dict[str, Any]) -> None:
        """Bubble first. A visible room swallows the doorbell. Voice waits on the floor."""
        if self._force_quit or self._disposed:
            return
        msg = InboundSms(
            id=str(payload.get("id") or ""),
            sender=str(payload.get("from") or "(unknown)"),
            body=str(payload.get("body") or ""),
            time=str(payload.get("time") or ""),
            contact_alias=str(payload.get("contact_alias") or ""),
            contact_name=str(payload.get("contact_name") or ""),
            media_path=str(payload.get("media_path") or ""),
            media_url=str(payload.get("media_url") or ""),
            media_kind=str(payload.get("media_kind") or ""),
        )
        alias = msg.contact_alias or ""
        title = msg.display_from
        self.sms_chats.append_inbound(
            body=msg.body,
            alias=alias,
            phone=msg.sender,
            sender=msg.sender,
            title=title,
            media_path=msg.media_path,
            media_kind=msg.media_kind,
        )
        self._alert_if_background()
        _window, state = self.sms_chats.room_state(
            alias=alias, phone=msg.sender, sender=msg.sender
        )
        if room_owns_doorbell(state):
            return
        notice = self.notify_center.add(
            new_notice(
                kind="sms",
                title=title,
                body=msg.body,
                group_key=f"sms:{alias or msg.sender}",
                voice_cue=format_held_inbound_voice_cue([msg]),
                data={
                    "from": msg.sender,
                    "alias": alias,
                    "time": msg.time,
                    "message_id": msg.id,
                },
            )
        )
        self._sync_notify_surface()
        if notice is None:
            return
        if self._floor_busy():
            self._held_inbound.append(msg)
            return
        self._maybe_voice_sms([msg])

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
        if not self._held_inbound or self._floor_busy():
            return
        held = self._held_inbound
        self._held_inbound = []
        self._maybe_voice_sms(held)

    def _maybe_voice_sms(self, messages: list[InboundSms]) -> None:
        if not messages:
            return
        if self.notify_center.mode("sms") != "voice":
            return
        known = [m for m in messages if m.contact_alias or m.contact_name]
        if not known:
            return
        if self.voice is None or not self.voice.speak_enabled:
            return
        cue = format_held_inbound_voice_cue(known)
        if not cue:
            return
        self._arm_speech()
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.VOICE_SPEAK, {"text": cue})),
            self.loop,
        )

    def _sync_notify_surface(self) -> None:
        # Reachable before the mailbox windows exist: restoring a saved layout
        # that was maximized calls setWindowState from inside __init__, and the
        # WindowStateChange lands here. That raised AttributeError, which run_ui
        # turns into "Arelis window failed to start" — so a maximized glass could
        # be closed one evening and refuse to open at all the next.
        if not hasattr(self, "notify_inbox"):
            return
        head = self.notify_center.head()
        extra = self.notify_center.extra_count()
        maximized = self.isMaximized() or self.isFullScreen()
        mailbox_open = self.notify_inbox.isVisible()
        overlay = self.conversation.notify_overlay
        overlay.show_notice(
            head, extra=extra, maximized=maximized, mailbox_open=mailbox_open
        )
        chip_text = ""
        if head is not None:
            chip_text = head.pill_label()
            if extra:
                chip_text = f"{chip_text} · +{extra}"
        self.readiness_strip.set_notify_chip(
            chip_text, visible=maximized and head is not None and not mailbox_open
        )
        self.notifications.set_notices(
            self.notify_center.visible_items(),
            unread=self.notify_center.unread_count(),
        )
        self._on_notify_unread(self.notify_center.unread_count())
        idle = self._idle_eligible()
        if idle != bool(self.conversation._idle_mode):
            self._sync_idle_mode()

    def _on_notify_pill_clicked(self) -> None:
        head = self.notify_center.head()
        if head is not None and not head.sticky:
            self.notify_center.mark_read(head.id)
        self._sync_notify_surface()

    def _on_notify_chip_clicked(self) -> None:
        head = self.notify_center.head()
        if head is None:
            return
        self._on_notice_open(head.id)

    def _on_notice_dismiss(self, notice_id: str) -> None:
        self.notify_center.dismiss(notice_id)
        self._sync_notify_surface()

    def _on_notice_snooze(self, notice_id: str) -> None:
        self.notify_center.snooze(
            notice_id, datetime.now().astimezone() + timedelta(minutes=15)
        )
        self._sync_notify_surface()

    def _on_notice_reply(self, notice_id: str) -> None:
        self._open_sms_chat(notice_id)

    def _on_notice_open(self, notice_id: str) -> None:
        self.act_notifications.setChecked(True)
        self._toggle_notifications(True)
        if notice_id:
            self.notifications.show_notice(notice_id)

    def _on_sms_tile_shown(self, alias: str, phone: str) -> None:
        """Showing a room marks that person's SMS group read so the pill drops."""
        from arelis.contacts import normalize_phone

        keys: list[str] = []
        if alias:
            keys.append(f"sms:{alias}")
        if phone:
            keys.append(f"sms:{phone}")
            digits = normalize_phone(phone)
            if digits and f"sms:{digits}" not in keys:
                keys.append(f"sms:{digits}")
        marked = False
        for key in keys:
            notice = self.notify_center.find_group(key)
            if notice is not None and notice.unread:
                self.notify_center.mark_read(notice.id)
                marked = True
        if marked:
            self._sync_notify_surface()

    def _open_sms_chat(self, notice_id: str) -> None:
        notice = self.notify_center.find(notice_id)
        if notice is None or notice.kind != "sms":
            return
        alias = str(notice.data.get("alias") or "").strip()
        phone = str(notice.data.get("from") or "").strip()
        window = self.sms_chats.open(
            alias=alias,
            phone=phone,
            sender=phone,
            title=notice.title,
            seed=seed_bodies(notice),
        )
        if window is None:
            self.thinking.append(
                "No number on that text — cannot open a chat.",
                kind="status",
            )
            return
        if notice.unread:
            self.notify_center.mark_read(notice.id)
            self._sync_notify_surface()

    def _on_sms_tile_send(self, key: str, body: str, alias: str, phone: str) -> None:
        if self.loop is None or not self.loop.is_running():
            self.sms_chats.system(key, "Arelis is not ready to send.")
            return
        future = asyncio.run_coroutine_threadsafe(
            self._operator_send_sms(alias, phone, body),
            self.loop,
        )
        future.add_done_callback(
            lambda fut, k=key: self._sms_send_resolved(fut, k)
        )

    async def _operator_send_sms(self, alias: str, phone: str, body: str) -> None:
        from arelis.sms_android import AndroidSmsProvider, load_sms_account

        resolved = resolve_operator_sms_target(alias=alias, phone=phone)
        if isinstance(resolved, str):
            raise SmsSendError(resolved)
        account = load_sms_account()
        if account is None:
            raise SmsSendError("SMS is not configured.")
        await send_operator_sms(
            phone=resolved.phone_e164,
            body=body,
            provider=AndroidSmsProvider(account, live=True),
        )

    def _sms_send_resolved(self, future, key: str) -> None:
        try:
            future.result()
        except Exception as exc:
            try:
                self.sms_send_finished.emit(key, False, explain_sms_error(exc))
            except RuntimeError:
                pass
            return
        try:
            self.sms_send_finished.emit(key, True, "")
        except RuntimeError:
            pass

    def _on_sms_send_finished(self, key: str, ok: bool, error: str) -> None:
        if not ok:
            self.sms_chats.system(key, error or "Send failed.")

    def _push_mobile_notice(self, kind: str, title: str, body: str) -> None:
        ingest = self.sms_ingest
        hub = getattr(ingest, "mobile", None) if ingest is not None else None
        if hub is not None:
            hub.push_notice(kind, title, body)

    def _bind_mobile_hub(self) -> None:
        """Let the phone ask whether this window can think."""
        ingest = self.sms_ingest
        if ingest is None:
            return
        from arelis.config import load_persona

        def transcribe(path: Path) -> str:
            voice = self.voice
            if voice is None or not voice.stt_enabled:
                raise RuntimeError("voice is off on the PC")
            fut = asyncio.run_coroutine_threadsafe(
                voice.stt.transcribe(path),
                self.loop,
            )
            return str(fut.result(timeout=90) or "")

        def speak_for_phone(text: str) -> bytes | None:
            voice = self.voice
            if voice is None or not voice.tts_enabled:
                return None
            from arelis.paths import outputs_dir
            from arelis.voice.speech_text import prepare_spoken_text

            spoken = prepare_spoken_text(text or "", max_chars=voice.max_spoken_chars)
            if not spoken:
                return None
            dest = outputs_dir() / "voice" / "mobile-speak.wav"
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                fut = asyncio.run_coroutine_threadsafe(
                    voice.tts.synthesize(spoken, dest),
                    self.loop,
                )
                path = fut.result(timeout=90)
                data = Path(path).read_bytes()
                return data or None
            except Exception:
                log.exception("phone speech failed")
                return None

        def place() -> dict:
            rooms = self.config.get("_rooms")
            room = getattr(rooms, "active", None) if rooms is not None else None
            return {
                "workspace": self.workspace_roots.active,
                "roots": self.workspace_roots.names(),
                "room": (
                    {
                        "id": room.id,
                        "name": room.name,
                        "root": room.root,
                    }
                    if room is not None
                    else None
                ),
            }

        def list_files(scope: str, rel: str, room_id: str = "") -> dict:
            from arelis.mobile import browse_files

            rooms = self.config.get("_rooms")
            room = None
            if rooms is not None and room_id:
                room = rooms.get(room_id)
            return browse_files(
                self.workspace_roots,
                scope=scope,
                rel=rel,
                room_name=getattr(room, "name", "") or "",
                room_root=getattr(room, "root", "") or "",
            )

        def open_file(path: str) -> tuple[bytes, str, str] | None:
            import mimetypes

            from arelis.mobile import GLANCE_MAX_BYTES

            hit = self.workspace_roots.resolve_read(path)
            if not hit.path.is_file():
                return None
            data = hit.path.read_bytes()
            if len(data) > GLANCE_MAX_BYTES:
                raise ValueError("file is larger than 8 MB — open it on the PC")
            mime, _ = mimetypes.guess_type(hit.path.name)
            return data, mime or "application/octet-stream", hit.path.name

        def list_chats() -> list:
            store = self.store
            if store is None:
                return []
            return [
                {
                    "id": str(row.get("id") or ""),
                    "started_at": str(row.get("started_at") or ""),
                    "title": str(row.get("title") or ""),
                    "room_id": str(row.get("room_id") or ""),
                }
                for row in store.list_sessions(limit=80)
            ]

        def current_chat() -> dict:
            store = self.store
            if store is None:
                return {}
            sid = str(store.session_id or "")
            if not sid:
                return {}
            row = store.get_session(sid) or {}
            title = str(row.get("title") or "").strip() or "(untitled)"
            return {
                "id": sid,
                "title": title,
                "started_at": str(row.get("started_at") or ""),
                "room_id": str(row.get("room_id") or ""),
            }

        def view_chat(sid: str) -> dict | None:
            store = self.store
            if store is None:
                return None
            wanted = str(sid or "").strip()
            row = store.get_session(wanted) if wanted else None
            if row is None:
                return None
            rooms = self.config.get("_rooms")
            room_id = str(row.get("room_id") or "")
            room = rooms.get(room_id) if rooms is not None and room_id else None
            title = str(row.get("title") or "").strip() or "(untitled)"
            transcript = []
            for msg in store.get_messages(wanted):
                role = str(msg.get("role") or "")
                text = str(msg.get("content") or "")
                if role in {"user", "assistant"} and text:
                    transcript.append({"role": role, "text": text, "glances": []})
            return {
                "chat": {
                    "id": wanted,
                    "title": title,
                    "started_at": str(row.get("started_at") or ""),
                    "room_id": room_id,
                },
                "transcript": transcript,
                "place": {
                    "workspace": self.workspace_roots.active,
                    "roots": self.workspace_roots.names(),
                    "room": (
                        {
                            "id": room.id,
                            "name": room.name,
                            "root": room.root,
                        }
                        if room is not None
                        else None
                    ),
                },
            }

        def mint_chat() -> dict | None:
            store = self.store
            if store is None:
                return None
            sid = store.mint_session()
            return view_chat(sid)

        ingest.mobile.bind(
            warmup=lambda: bool(
                getattr(self.router, "warmup_pending", lambda: False)()
            ),
            busy=lambda: bool(self._turn_busy),
            model=lambda: str(getattr(self, "_current_model", "") or ""),
            session_ready=lambda: True,
            transcribe=transcribe,
            persona=lambda: load_persona(self.config),
            files=list_files,
            open_file=open_file,
            place=place,
            chats=list_chats,
            current_chat=current_chat,
            view_chat=view_chat,
            mint_chat=mint_chat,
            speak=speak_for_phone,
        )
        # Phone status is this hub, not the desktop widget. Seed the open
        # thread so a reconnect during warmup still has the real conversation,
        # then Gemma lines from the pocket can copy in on top.
        store = self.store
        sid = str(getattr(store, "session_id", "") or "")
        if store is not None and sid:
            ingest.mobile.replace_transcript(
                [
                    {"role": row.get("role"), "content": row.get("content")}
                    for row in store.get_messages(sid)
                ]
            )

    def _begin_job(self, tool: str) -> None:
        self._job_name = tool
        self._job_t0 = time.monotonic()
        self.notify_center.upsert_job(tool, elapsed_s=0)
        self._job_tick.start()
        self._sync_notify_surface()

    def _finish_job(self, tool: str, *, ok: bool, output: str = "") -> None:
        self._job_tick.stop()
        self._job_t0 = None
        self._job_name = ""
        if ok:
            self.notify_center.upsert_job(tool, done=True, output=output)
            self._push_mobile_notice("job", f"{tool} finished", output or f"{tool} is ready.")
        else:
            self.notify_center.upsert_job(tool, failed=True, output=output)
            self._push_mobile_notice("job", f"{tool} failed", output or f"{tool} failed.")
        self._sync_notify_surface()

    def _on_job_tick(self) -> None:
        if self._job_t0 is None or not self._job_name:
            self._job_tick.stop()
            return
        self.notify_center.upsert_job(
            self._job_name, elapsed_s=time.monotonic() - self._job_t0
        )
        self._sync_notify_surface()

    def _report_poll_state(self, key: str, message: str) -> None:
        """Speak poll failure/recovery, but ignore single-shot network blips.

        IMAP peek fails on timeout, DNS, and unreachable-network as often as
        the Wi-Fi hiccups. Reporting every transition taught the rail to be
        ignored. Two consecutive failures (or two consecutive recoveries)
        still surface; a lone blip does not.
        """
        if message:
            self._poll_fail_streak[key] = self._poll_fail_streak.get(key, 0) + 1
            self._poll_ok_streak[key] = 0
            self._poll_state[key] = message
            if (
                self._poll_fail_streak[key] >= 2
                and self._poll_spoken.get(key) != "down"
            ):
                self._poll_spoken[key] = "down"
                self.thinking.append(message, kind="status")
            return
        self._poll_ok_streak[key] = self._poll_ok_streak.get(key, 0) + 1
        self._poll_fail_streak[key] = 0
        self._poll_state[key] = ""
        if (
            self._poll_ok_streak[key] >= 2
            and self._poll_spoken.get(key) == "down"
        ):
            self._poll_spoken[key] = "up"
            self.thinking.append(
                f"{key} notifications are working again.", kind="status"
            )

    def _on_notify_poll(self) -> None:
        if self._force_quit or self._disposed:
            return
        now = datetime.now().astimezone()
        try:
            events = load_today_events(self.config)
            self.notify_center.apply_calendar(events, now)
        except Exception as exc:
            self._report_poll_state(
                "calendar", f"Calendar notifications stopped: {plain_reason(exc)}"
            )
        else:
            self._report_poll_state("calendar", "")
        if self.store is not None and self.notify_center.enabled("task"):
            try:
                rows = self.store.list_tasks(status="open", limit=40)
                for notice in due_task_notices(
                    rows, today=now.date(), remember=self.notify_center.remember_task
                ):
                    self.notify_center.add(notice)
            except Exception as exc:
                self._report_poll_state(
                    "task", f"Task due notices stopped: {plain_reason(exc)}"
                )
            else:
                self._report_poll_state("task", "")
        self._sync_notify_surface()
        mail_cfg = (self.config.get("ui") or {}).get("notifications") or {}
        mail_every = max(45.0, float(mail_cfg.get("mail_poll_s") or 90))
        if (
            self.notify_center.enabled("email")
            and not self._mail_poll_inflight
            and (time.monotonic() - self._mail_poll_at) >= mail_every
        ):
            self._kick_mail_poll()

    def _kick_mail_poll(self) -> None:
        self._mail_poll_inflight = True
        self._mail_poll_at = time.monotonic()

        def _work() -> None:
            try:
                rows: object = peek_contact_mail_sync(self.config)
            except Exception as exc:
                rows = exc
            self.mail_headers_ready.emit(rows)

        threading.Thread(target=_work, daemon=True, name="arelis-mail-peek").start()

    def _on_mail_headers(self, rows: object) -> None:
        self._mail_poll_inflight = False
        if isinstance(rows, BaseException):
            # Email notices are switched on and the user is waiting for them.
            # A debug log is not a place anybody is looking.
            self._report_poll_state("mail", plain_reason(rows))
            return
        if not isinstance(rows, list):
            return
        self._report_poll_state("mail", "")
        for notice in mail_notices(rows, remember=self.notify_center.remember_mail):
            self.notify_center.add(notice)
        self._sync_notify_surface()


def force_windows_qt_platform(env: MutableMapping[str, str]) -> None:
    """Insist on the real Windows Qt backend, whatever the environment says.

    A stray QT_QPA_PLATFORM is a process that starts, runs, logs normally and
    never shows a window — the worst shape a failure can take, because there is
    nothing to look at while you work out why. offscreen is the value that
    actually gets set by accident, exported by a test run and inherited by the
    next launch from the same shell, but minimal and vnc go wrong identically.

    This used to be run_ui.ps1's job, and it no longer has one: the desktop
    shortcut points straight at pythonw.exe so that no console is ever created
    for a shell to hide, which means there is no shell left to clear the variable
    before Python starts.

    ARELIS_ALLOW_OFFSCREEN is the way out, for headless checks that mean it.
    """
    if sys.platform != "win32":
        return
    if env.get("ARELIS_ALLOW_OFFSCREEN"):
        return
    if env.get("QT_QPA_PLATFORM", "windows").lower() != "windows":
        env["QT_QPA_PLATFORM"] = "windows"


async def _drain_event_loop(
    loop: asyncio.AbstractEventLoop, *, budget_s: float
) -> None:
    """Stop what is still running before the loop is taken out from under it.

    Stopping the loop with work in flight is not free, whatever the exit code
    says. The visible symptom was tidy enough to ignore — "Task was destroyed but
    it is pending" for EventBus.run and MemoryIndexer.run_batch, then an
    "Indexed 3 workspace file(s)" line arriving two and a half seconds after quit
    had finished — but the second half of that is the part that matters. The
    indexer does its writing in ``asyncio.to_thread``, so cancelling the task
    only abandons the *await*: the worker thread carries on into memory.db while
    the interpreter is shutting down around it. A process exiting during a SQLite
    write is how an archive of every conversation someone has had becomes a file
    that no longer opens.

    So the order here is deliberate. Cancel first, so nothing new is started;
    wait for the cancellations to land, so tasks unwind through their own finally
    blocks; then wait on the default executor, which is the only way to know that
    the last statement has been written rather than merely that nobody is waiting
    for it. Async generators go last because closing them can await.

    Every wait is bounded. A shutdown that hangs is worse than one that leaves a
    warning in the log, and the caller passes a tighter ceiling for tray Quit
    than for an ordinary close.
    """
    current = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks(loop) if t is not current and not t.done()]
    for task in pending:
        task.cancel()
    if pending:
        _done, still = await asyncio.wait(pending, timeout=budget_s)
        if still:
            log.info(
                "loop drain: %d task(s) did not stop within %.2fs", len(still), budget_s
            )
    # asyncio.wait rather than wait_for throughout, and that is the whole reason
    # the ceilings above are real. wait_for cancels what it is waiting on and then
    # waits for *that* to finish, so a task which swallows CancelledError — a bare
    # `except Exception` around an await is enough — turns the bound into a hang.
    # asyncio.wait just stops waiting.
    executor_stopped = asyncio.ensure_future(loop.shutdown_default_executor())
    _done, still = await asyncio.wait([executor_stopped], timeout=budget_s)
    if still:
        # Giving up here means the process may still exit with a write in flight,
        # which is the thing this function exists to prevent. It is the lesser
        # evil: a quit that never returns is a program the user has to kill, and
        # they will then be exiting mid-write anyway with no record of why.
        log.warning(
            "loop drain: background writes still running after %.2fs — exiting anyway",
            budget_s,
        )
    try:
        await loop.shutdown_asyncgens()
    except Exception:
        log.debug("loop drain: asyncgen shutdown failed", exc_info=True)


_HANDOFF_WAIT_S = 8.0
_HANDOFF_SLICE_S = 0.35
_HANDOFF_MAX_TRIES = 24


def _raise_running_instance(config: dict[str, Any]) -> int:
    """Second launch: put the Arelis that is already running back on screen.

    The UI lock is held, so this copy must not open a window — two glasses over
    one memory.db is not a thing anyone wants. But refusing quietly is worse than
    it sounds: the running instance is usually hidden in the tray, so the visible
    result of double-clicking Arelis was nothing at all, and the honest response
    to that is to click it again. Every launch/close/relaunch complaint about this
    program has started there.

    A held lock always means a living process. Windows releases both the named
    mutex and the byte lock when a process ends, however it ends, so there is no
    such thing here as a stale lock left by a crash — if the lock is held, someone
    is home. The wait-and-retry lives in ``_second_launch``; this function is the
    last-resort notice after that wait has already asked and the other copy still
    did not answer.
    """
    from arelis.presence.activate import activate_existing_ui
    from arelis.ui.dialog import notice

    if activate_existing_ui(config):
        log.info("second launch: asked the running Arelis to show itself")
        return 0
    # Held lock, no answer. Nothing here may kill the other process — it is the
    # one holding the conversation, the memory and possibly an unsent draft — so
    # say so and name where to look, which is the one outcome that is neither a
    # second window nor silence.
    log.warning("second launch: UI lock held but no Arelis answered on IPC")
    try:
        configure_native_windows()
        app = QApplication.instance() or QApplication([])
        app.setApplicationName("Arelis")
        icon_path = app_icon_path()
        if icon_path.is_file():
            app.setWindowIcon(QIcon(str(icon_path)))
        app.setFont(app_font(load_fonts()))
        app.setStyleSheet(stylesheet())
        notice(
            None,
            "Arelis is already running",
            "Arelis is already open, but it did not answer the request to come "
            "to the front.",
            detail=(
                "Look for the Arelis icon in the notification area — Windows "
                "often keeps it in the overflow behind the chevron — and choose "
                f"Open Arelis. If it is not responding at all, {logs_dir()}"
                "\\arelis.log has the last thing it did."
            ),
            warning=True,
        )
    except Exception:
        log.exception("second launch: could not show the already-running notice")
    return 1


def _second_launch(config: dict[str, Any], ui_lock: Any) -> int | None:
    """Ask the living glass to show, or wait for it to finish quitting.

    Returns an exit code if this process should stop, or None if it now holds
    the UI lock and should open a window. The gap this covers is Quit: IPC is
    already down, the lock is still held, and a shortcut click in that window
    used to either show the already-running dialog or (if the lock then dropped
    mid-click) open a second glass on top of the dying one.
    """
    from arelis.presence.activate import activate_existing_ui
    from arelis.presence.lock import lock_file_pid, pid_is_alive

    if activate_existing_ui(config):
        log.info("second launch: asked the running Arelis to show itself")
        return 0
    deadline = time.monotonic() + _HANDOFF_WAIT_S
    tries = 0
    while tries < _HANDOFF_MAX_TRIES and time.monotonic() < deadline:
        time.sleep(_HANDOFF_SLICE_S)
        tries += 1
        if activate_existing_ui(config):
            log.info("second launch: running Arelis answered on the retry")
            return 0
        if ui_lock.acquire():
            log.info("second launch: previous Arelis exited; this copy will open")
            return None
        path = getattr(ui_lock, "path", None)
        if path is not None:
            pid = lock_file_pid(path)
            if pid is not None and not pid_is_alive(pid) and ui_lock.acquire():
                log.info("second launch: lock holder is gone; this copy will open")
                return None
    return _raise_running_instance(config)


def run_ui(config: dict[str, Any] | None = None) -> int:
    # Before any QApplication — a native child HWND is the offset ghost, and
    # this attribute is what stops one winId() from promoting every sibling.
    configure_native_windows()
    # Remembered because first run may need to reload from disk, and a config
    # handed in by a caller (tests, harnesses) must not be silently replaced.
    config_was_given = config is not None
    config = config or load_config()
    # Single glass: a second launch raises the first rather than opening again.
    from arelis.presence.lock import PresenceLock, ui_lock_path

    ui_lock = PresenceLock(ui_lock_path(config))
    if not ui_lock.acquire():
        handed = _second_launch(config, ui_lock)
        if handed is not None:
            return handed

    _ui_lock_gate = threading.Lock()
    _ui_lock_out = False

    def _release_ui_lock() -> None:
        nonlocal _ui_lock_out
        with _ui_lock_gate:
            if _ui_lock_out:
                return
            _ui_lock_out = True
            ui_lock.release()

    def _bind_workspace(cfg: dict[str, Any]) -> WorkspaceRoots:
        roots = WorkspaceRoots.from_config(cfg)
        cfg["_workspace"] = roots
        # Teach Whisper the configured project names without losing the jargon
        # seed.
        stt = cfg.setdefault("voice", {}).setdefault("stt", {})
        stt["initial_prompt"] = compose_stt_initial_prompt(cfg, roots)
        return roots

    workspace = _bind_workspace(config)
    force_windows_qt_platform(os.environ)
    from arelis.ui.solar_gl import prepare_desktop_gl

    prepare_desktop_gl(os.environ)
    os.environ.setdefault("QT_QPA_FONTDIR", str(qt_font_directory()))

    # A scheduled task holds the absolute path it was created with, so installing a
    # packaged build after running from a checkout leaves every job pointing at an
    # interpreter that has moved. Costs a small file read when nothing has changed.
    from arelis.jobs.schedule import repoint_moved_tasks_on_launch

    repoint_moved_tasks_on_launch()

    # Group taskbar buttons (python.exe vs pythonw.exe otherwise diverge).
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
                "Arelis.Desktop"
            )
        except Exception:
            pass

    configure_native_windows()
    from arelis.ui.solar_gl import gl_wanted

    if gl_wanted():
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_UseDesktopOpenGL, True
        )
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Arelis")
    icon_path = app_icon_path()
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    families = load_fonts()
    app.setFont(app_font(families))
    app.setStyleSheet(stylesheet())

    # First run: ask which folder Arelis may work in. It happens here rather than
    # beside the other config work above because it needs a QApplication, and the
    # QApplication cannot be created until the font and platform environment is
    # set. Nothing between the two reads the workspace.
    # Returns None when the question has already been answered, which is every
    # launch after the first.
    if not config_was_given and prompt_for_workspace_root() is not None:
        config = load_config()
        workspace = _bind_workspace(config)
    if not config_was_given and prompt_for_model_setup() is not None:
        config = load_config()
        workspace = _bind_workspace(config)
    # Required so hiding the last window to the tray does not kill the process.
    presence_cfg_early = (config or {}).get("presence") or {}
    if bool(presence_cfg_early.get("close_to_tray", True)):
        app.setQuitOnLastWindowClosed(False)

    bus = EventBus()
    bridge = BusBridge()

    async def mirror(event: Event) -> None:
        bridge.feed(event)

    bus.subscribe(None, mirror)
    from arelis.core.event_audit import attach_event_audit

    attach_event_audit(bus, config)

    router = build_router(config)
    # Write-through archive. The job runner constructs SessionMemory() with no
    # sink, so scheduled turns neither read nor pollute this file. The same
    # store is handed to recall so search sees what this session just wrote.
    store = MemoryStore()
    # Cold glass launch is a new conversation (ChatGPT-style). Last night
    # stays in History. Tray / un-minimize do not come through here.
    store.start_glass_session()
    tools = build_tool_registry(
        config,
        workspace,
        memory_store=store,
        provider=router.provider,
        router=router,
    )
    memory = SessionMemory.from_config(config, sink=store)
    orchestrator = Orchestrator(bus, router, tools, config, memory, workspace=workspace)
    voice = VoiceService(bus, config)
    embed_model = str(
        (config.get("memory") or {}).get("embed_model") or DEFAULT_EMBED_MODEL
    )
    docs_cfg = (config.get("memory") or {}).get("docs") or {}
    mail_cfg = (config.get("memory") or {}).get("mail") or {}
    email_cfg = (config.get("tools") or {}).get("email") or {}
    mail_account = load_account() if mail_cfg.get("enabled", False) else None
    indexer = MemoryIndexer(
        store,
        router.provider,
        model=embed_model,
        workspace=workspace,
        index_docs=bool(docs_cfg.get("enabled", True)),
        max_file_bytes=int(docs_cfg.get("max_file_bytes", 524288)),
        chunk_chars=int(docs_cfg.get("chunk_chars", 1200)),
        chunk_overlap=int(docs_cfg.get("chunk_overlap", 200)),
        index_mail=bool(mail_cfg.get("enabled", False)),
        mail_account=mail_account,
        mail_host=str(email_cfg.get("imap_host", "imap.gmail.com")),
        mail_port=int(email_cfg.get("imap_port", 993)),
        mail_timeout_s=float(email_cfg.get("timeout_s", 30)),
        mail_max_messages=int(mail_cfg.get("max_messages", 40)),
        mail_retention_days=int(mail_cfg.get("retention_days", 30)),
        mail_max_body_chars=int(mail_cfg.get("max_body_chars", 4000)),
        mail_min_interval_s=float(mail_cfg.get("min_interval_s", 900)),
    )

    # Qt owns the main thread, so the whole async side (bus, orchestrator,
    # Ollama streaming, tools) runs on its own loop in a background thread.
    # Everything crossing back into Qt goes through BusBridge's signal, and
    # everything crossing out goes through run_coroutine_threadsafe. Touching
    # widgets directly from the async side would be a data race.
    loop = asyncio.new_event_loop()

    def loop_thread() -> None:
        asyncio.set_event_loop(loop)
        # Held in a local for the lifetime of the loop. A bare create_task is
        # only weakly referenced and can be collected while still running.
        bus_task = loop.create_task(bus.run())
        loop.bus_task = bus_task  # type: ignore[attr-defined]
        loop.run_forever()

    thread = threading.Thread(target=loop_thread, name="arelis-asyncio", daemon=True)
    thread.start()

    # Non-blocking for the window: a slow or absent Ollama must not delay
    # Qt. The first chat turn does wait — otherwise it races this warmup
    # and pays the prefix prefill twice.
    router.arm_warmup()

    async def _startup_models() -> None:
        try:
            await run_model_preflight(bus, router.provider, config.get("models"))
            await run_model_warmup(
                bus, router, prefix=prefix_warmup_for(config, tools)
            )
            agent_cfg = config.get("agent") or {}
            await run_auto_lessons(
                bus, enabled=bool(agent_cfg.get("auto_lessons", True))
            )
        finally:
            router.mark_warmup_done()

    asyncio.run_coroutine_threadsafe(_startup_models(), loop)

    try:
        window = ArelisWindow(
            config,
            bridge,
            loop,
            bus,
            voice,
            store=store,
            restore_session_id=None,
            indexer=indexer,
            router=router,
        )
    except Exception:
        logging.getLogger(__name__).exception("Arelis window failed to start")
        _release_ui_lock()
        raise
    asyncio.run_coroutine_threadsafe(orchestrator.resume_last_room(), loop)
    # Inbound: by default the UI owns ingest. Close-to-tray keeps it alive when
    # the window hides; `arelis --core` can own ingest instead.
    presence_cfg = config.get("presence") or {}
    use_external = bool(presence_cfg.get("use_external_core", False))
    spawn_attach = os.environ.get("ARELIS_ATTACH_CORE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    # Attach when config asks, a core is already up, or core spawned us.
    core_up = external_core_available(config)
    attach_core = use_external or core_up or spawn_attach
    close_to_tray = bool(presence_cfg.get("close_to_tray", True))
    persister = ConfirmPersister(bus, window._pending_store)
    persister.start()
    if attach_core and (core_up or spawn_attach):
        # Never bind :8765 when attaching (or when core is about to own it).
        window.inbound_runtime = InboundRuntime(owned=False)
        ipc_enabled = bool(presence_cfg.get("ipc_enabled", True))
        if ipc_enabled:
            try:
                window.ipc_client = IpcClient(
                    bus,
                    host=str(presence_cfg.get("ipc_host") or "127.0.0.1"),
                    port=int(presence_cfg.get("ipc_port") or 8766),
                    on_open_ui=lambda _msg: QTimer.singleShot(
                        0, window._on_activation_request
                    ),
                    # Our own core may have fallen forward past the configured
                    # port because another account on this PC holds it. The
                    # handshake names the account, so scanning cannot attach us
                    # to the wrong one.
                    search_ports=True,
                )

                async def _start_ipc() -> None:
                    assert window.ipc_client is not None
                    window.ipc_client.start()

                asyncio.run_coroutine_threadsafe(_start_ipc(), loop)
            except ValueError as exc:
                asyncio.run_coroutine_threadsafe(
                    bus.publish(
                        Event(
                            EventType.STATUS,
                            {"message": f"Core IPC client not started: {exc}"},
                        )
                    ),
                    loop,
                )
        asyncio.run_coroutine_threadsafe(
            bus.publish(
                Event(
                    EventType.STATUS,
                    {
                        "message": (
                            "Detached Arelis core owns inbound notify. "
                            "Pending send confirms restore from disk; live SMS/"
                            "confirm events use the Core↔UI IPC bridge when attached."
                        )
                    },
                )
            ),
            loop,
        )
    else:
        hint = (
            "close to tray keeps listening; Quit from the tray to stop"
            if close_to_tray
            else "Arelis must stay open"
        )
        runtime = attach_inbound(
            bus,
            loop,
            config,
            owned=True,
            stay_open_hint=hint,
        )
        window.inbound_runtime = runtime
        window.sms_ingest = runtime.ingest
        window.sms_watcher = runtime.watcher
        window.sms_auto_reply = runtime.auto_reply
        window._bind_mobile_hub()
        for message in runtime.status_messages:
            asyncio.run_coroutine_threadsafe(
                bus.publish(Event(EventType.STATUS, {"message": message})),
                loop,
            )
        # With no core there is nothing on the bridge port, and a second launch
        # asking to be shown was talking to nobody — which is the whole of why
        # clicking the shortcut while tray-hidden did nothing. The UI answers for
        # itself in that case, over the same protocol and the same fall-forward
        # ports, so activate_existing_ui does not care which of the two replied.
        if bool(presence_cfg.get("ipc_enabled", True)):
            try:
                window.ipc_server = IpcServer(
                    bus,
                    host=str(presence_cfg.get("ipc_host") or "127.0.0.1"),
                    port=int(presence_cfg.get("ipc_port") or 8766),
                    on_open_ui=lambda _reason: QTimer.singleShot(
                        0, window._on_activation_request
                    ),
                )
            except ValueError as exc:
                log.warning("UI activation listener not started: %s", exc)
            else:

                async def _serve_activation() -> None:
                    assert window.ipc_server is not None
                    try:
                        await window.ipc_server.start()
                    except OSError as exc:
                        # Not fatal and not worth a dialog: everything else about
                        # this launch works, and the cost is that the next
                        # double-click has to fall back to the tray icon.
                        log.warning("UI activation listener could not bind: %s", exc)
                        window.ipc_server = None

                asyncio.run_coroutine_threadsafe(_serve_activation(), loop)

    window.setup_tray(app)
    parked = window._pending_store.list()
    if parked:
        window.queue_pending_confirms(parked)
        asyncio.run_coroutine_threadsafe(
            bus.publish(
                Event(
                    EventType.STATUS,
                    {
                        "message": (
                            f"{len(parked)} pending send confirm(s) waiting — "
                            "allow or skip in the card (nothing was sent while away)."
                        )
                    },
                )
            ),
            loop,
        )

    window.show()
    window.raise_()
    window.activateWindow()
    window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)

    def _deferred_memory_backup() -> None:
        try:
            from arelis.memory.backup import backup_memory_db

            backup_memory_db(store.path)
        except Exception:
            log.debug("deferred memory backup failed", exc_info=True)

    threading.Thread(
        target=_deferred_memory_backup,
        name="arelis-memory-backup",
        daemon=True,
    ).start()

    # After the window, not before: this reaches the network, and the first seconds of a
    # launch belong to the person who double-clicked something. Declines to do anything at
    # all unless this copy came from the installer, so a checkout is never offered a
    # release that would overwrite the code being edited.
    from arelis.ui.update_prompt import schedule_update_check

    schedule_update_check(window)
    try:
        code = app.exec()

        # Tray Quit is meant to feel instant, so every wait below is a ceiling
        # rather than a duration, and the force-quit ceilings are the tighter of
        # the two — the same distinction closeEvent already draws.
        force = bool(window._force_quit)
        drain_budget_s = 0.75 if force else 3.0

        async def shutdown() -> None:
            if window.ipc_client is not None:
                await window.ipc_client.stop()
                window.ipc_client = None
            if window.ipc_server is not None:
                try:
                    await asyncio.wait_for(window.ipc_server.stop(), timeout=1.0)
                except Exception:
                    pass
                window.ipc_server = None
            if window.inbound_runtime is not None:
                # closeEvent may already have stopped owned inbound; tolerate double-stop.
                try:
                    await asyncio.wait_for(window.inbound_runtime.stop(), timeout=2.0)
                except Exception:
                    pass
                if window.inbound_runtime.owned:
                    window.sms_ingest = None
                    window.sms_watcher = None
                    window.sms_auto_reply = None
            # IPC and ingest are down. Drop the single-instance lock before
            # model unload / browser close so a shortcut click during Quit
            # can take over instead of stacking a second glass or waiting on
            # a lock the dying copy still holds.
            _release_ui_lock()
            bus.stop()
            # Do not await model unload forever — just drop the HTTP client.
            try:
                await asyncio.wait_for(router.close(), timeout=2.0)
            except Exception:
                pass
            try:
                browser = tools.get("browser")
                session = getattr(browser, "session", None) if browser else None
                if session is not None:
                    await asyncio.wait_for(session.close(), timeout=2.0)
            except Exception:
                pass
            await _drain_event_loop(loop, budget_s=drain_budget_s)

        fut = asyncio.run_coroutine_threadsafe(shutdown(), loop)
        try:
            fut.result(timeout=2.0 if force else 8.0)
        except Exception:
            log.warning("shutdown did not finish in time", exc_info=True)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        return code
    finally:
        _release_ui_lock()
