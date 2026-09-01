"""View menu, atmosphere, chrome events, theme switch.

Mixin on ArelisWindow. Same HWND. Not a second QMainWindow.
"""

from __future__ import annotations

import asyncio
import logging
import time

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
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
    QMenu,
)

from arelis.presence.readiness import ChipLevel, probe_readiness
from arelis.ui.glass import GlassFrame, advance_rim_pulse
from arelis.ui.hands_host import park_hands, resume_hands
from arelis.ui.idle_host import note_engagement, sync_idle_mode
from arelis.ui.notify_host import on_notify_unread
from arelis.ui.scale import default_window_size
from arelis.ui.settings_host import (
    apply_chat_font_scale,
    nudge_chat_font,
    open_settings,
    toggle_always_on_top,
    toggle_fullscreen,
)
from arelis.ui.shortcuts import ShortcutsSheet
from arelis.ui.stage import paint_atmosphere
from arelis.ui.theme import (
    GLASS,
    THEME_CHOICES,
    active_theme,
    theme_from_config,
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
from arelis.ui.world_host import world_available

log = logging.getLogger(__name__)

_WINDOW_RADIUS = int(GLASS["radius"])
_BUSY_WATCHDOG_MS = 8000
_THINK_PULSE_MS = 600
_VOICE_HOTKEY_ECHO_S = 0.12

_PANEL_OUTER = 12
_PANEL_HALF = 6
_PANEL_TOP = 12
_PANEL_BOTTOM = 14



class WindowChrome:
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

    def _on_contacts_inbox_closed(self) -> None:
        self.act_contacts.setChecked(False)
        sync_idle_mode(self)

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
