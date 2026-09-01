"""Filament desk controller. Same HWND as sodium; second GUI, not a hue swap.

Sodium is the shipped window. Filament is listed as ``filament (testing)``.
One opaque desk — never ``WA_TranslucentBackground``. No second process.
Field stays paint (``filament_field``). Tiles stay tiles (``filament_tile``).
``apply_filament_desk`` and the conversation Drive strip stay on conversation.

State lives on the window (``_filament_span``, ``_filament_home``, …).
This object reads and writes those attributes. It does not keep a second span.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QApplication, QDockWidget, QMenu

from arelis.config import merge_local_config
from arelis.spatial import PHYSICS_ROOM_ID
from arelis.ui.dock_surface import apply_dock_chrome
from arelis.ui.filament_field import (
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
    origin_on_a_desk,
    play_tile_grow,
)
from arelis.ui.glass import seal_tool_window
from arelis.ui.hands_host import apply_hands_face, on_hands_chip
from arelis.ui.theme import active_theme
from arelis.ui.window_resize import place_frameless_rect
from arelis.ui.world_host import world_available


class FilamentDesk:
    """Controller for the Filament face on an existing ArelisWindow."""

    def __init__(self, window) -> None:
        self.window = window
        self._bound = False

    def bind(self) -> None:
        """Wire title-bar span, float chips, Hands, and chat-tile close."""
        if self._bound:
            return
        w = self.window
        bar = getattr(w, "title_bar", None)
        if bar is not None:
            bar.span_requested.connect(self._filament_set_span)
        floats = getattr(w, "_filament_floats", None)
        if floats is not None:
            floats.opened.connect(self._on_filament_float)
            floats.hands_toggled.connect(self._on_hands_toggled)
        tile = getattr(w, "_filament_chat_tile", None)
        if tile is not None:
            tile.closed.connect(self._on_filament_chat_closed)
        self._bound = True

    def take_hwnd(self) -> None:
        """Enter Filament on the existing HWND. Sodium chrome parks."""
        self._filament_enter_presence()

    def release_hwnd(self) -> None:
        """Leave to sodium. Seal the desk and unmount chat."""
        self._filament_leave_presence()

    def _on_hands_toggled(self, on: bool) -> None:
        on_hands_chip(self.window, on)

    def _filament_weather(self) -> str:
        w = self.window
        conv = getattr(w, "conversation", None)
        if conv is None:
            return "idle"
        if getattr(conv, "_speaking", False):
            w._filament_woken = True
            return "speak"
        if getattr(conv, "_busy", False) or getattr(w, "_turn_busy", False):
            w._filament_woken = True
            return "think"
        if conv.conversation_btn.isChecked() or conv.mic_btn.isChecked():
            w._filament_woken = True
            return "listen"
        if getattr(w, "_away_resting", False):
            w._filament_woken = False
            return "idle"
        if not getattr(w, "_filament_woken", False):
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
        seal_tool_window(self.window)

    def _filament_pin_home(self) -> QRect | None:
        """Always the OS primary desk. Never the screen the HWND drifted onto."""
        w = self.window
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is None:
            screen = w.screen()
        if screen is None:
            return QRect(w._filament_home) if w._filament_home is not None else None
        w._filament_home = QRect(screen.availableGeometry())
        return QRect(w._filament_home)

    def _filament_set_span(self, n: int) -> None:
        w = self.window
        want = clamp_filament_span(n)
        w._filament_span = want
        w.title_bar.set_span_choice(want)
        w.config.setdefault("ui", {})["filament_span"] = want
        merge_local_config({"ui": {"filament_span": want}})
        if active_theme() == "filament":
            self._filament_place_entity()

    def _filament_place_entity(self) -> None:
        """Grow or shrink to the chosen 1 / 2 / 3 desks."""
        w = self.window
        if not self._filament_can_claim_desk():
            w.title_bar.set_span_choice(w._filament_span)
            return
        home = self._filament_pin_home()
        union, pinned, count = filament_span_geometry(w, w._filament_span, home)
        have = len(filament_row_desks(w, pinned)[0])
        w.title_bar.set_span_choice(w._filament_span)
        w.title_bar.set_span_available(have)
        if pinned is None:
            return
        # Place during __init__ used to take the app down. The HWND is real
        # after show; showEvent already re-places.
        if not w.isVisible() or w.windowHandle() is None:
            self._filament_apply_shape()
            return
        if count <= 1:
            self._filament_fill_home_desk(pinned)
        else:
            placed = place_frameless_rect(w, union)
            if not home_band_in_window(w, pinned).isValid():
                placed = place_frameless_rect(w, union) or placed
            # HWND on the union with a stale Qt cache still counts. Snapping
            # home here is how a working 3-span got thrown away.
            if not placed and not home_band_in_window(w, pinned).isValid():
                self._filament_fill_home_desk(pinned)
        self._filament_apply_shape()
        empty = getattr(getattr(w, "chat", None), "empty", None)
        layout_idle = getattr(empty, "_layout_idle", None)
        if callable(layout_idle):
            layout_idle()
        w.title_bar.sync_window_state(w)
        # dirty_rect is the old band. New desk glass has to void-fill once.
        w.update()

    def _filament_fill_home_desk(self, pinned: QRect) -> None:
        """Sit on the primary work area. showMaximized follows the HWND to the wrong desk."""
        if pinned is None or not pinned.isValid():
            return
        place_frameless_rect(self.window, pinned)

    def _filament_is_spanned(self) -> bool:
        w = self.window
        if w._filament_span >= 2:
            home = self._filament_pin_home()
            if home is None:
                return True
            return w.width() >= int(home.width() * 1.2)
        home = self._filament_pin_home()
        if home is None:
            return bool(w.isMaximized() or w.isFullScreen())
        geo = w.geometry()
        return (
            abs(geo.x() - home.x()) <= 16
            and abs(geo.width() - home.width()) <= 24
            and abs(geo.height() - home.height()) <= 24
        )

    def _filament_toggle_span(self) -> None:
        """Maximize snaps back to the chosen 1 / 2 / 3. It does not cycle
        desks and it does not fullscreen — F11 follows the HWND left."""
        w = self.window
        if w.isFullScreen() or w.isMaximized():
            w.showNormal()
        self._filament_place_entity()

    def _filament_apply_shape(self) -> None:
        w = self.window
        w.clearMask()
        if not self._filament_can_claim_desk():
            w._filament.set_span(w._filament_span)
            self._filament_place_chrome()
            return
        home = self._filament_pin_home()
        union, pinned, desks = filament_chosen_desks(w, w._filament_span, home)
        count = len(desks)
        work = filament_work_region(union, desks)
        if not work.isEmpty() and count >= 2:
            w.setMask(work)
        band = home_band_from_union(union, pinned)
        if not band.isValid() or band.width() < 280:
            band = home_band_in_window(w, pinned)
        win_w = max(1, int(w.width()))
        if band.isValid() and band.width() >= 280:
            desk_left = int(band.x())
            desk_w = int(band.width())
        else:
            desk_left = 0
            desk_w = win_w
        w._filament.set_span(
            max(1, count),
            desk_left=float(desk_left),
            desk_width=float(desk_w),
        )
        self._filament_place_chrome()

    def _filament_place_chrome(self) -> None:
        """Slim 1/2/3 bar sits on the primary overlap, above the field."""
        w = self.window
        bar = w.title_bar
        bar.set_slim(True)
        home = self._filament_pin_home()
        union, pinned, _count = filament_span_geometry(w, w._filament_span, home)
        glass = QRect(0, 0, max(1, int(w.width())), max(32, int(w.height())))
        band = chrome_band_on_glass(union, pinned, glass)
        if bar.parent() is not w:
            bar.setParent(w)
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        bar.set_home_band(0, 0, 0)
        bar.setGeometry(band)
        bar.show()
        bar.raise_()
        w.chrome_bar.hide()
        w.readiness_strip.hide()

    def _filament_dock_chrome(self) -> None:
        w = self.window
        bar = w.title_bar
        stack = getattr(w, "_chrome_stack", None)
        bar.set_home_band(0, 0, 0)
        if stack is not None and bar.parent() is not stack:
            lay = stack.layout()
            if lay is not None:
                lay.insertWidget(0, bar)
        bar.set_slim(False)
        w.chrome_bar.show()

    def _filament_lock_tiles(self, on: bool) -> None:
        w = self.window
        docks = {
            "thinking": w.think_dock,
            "files": w.work_dock,
            "history": w.history_dock,
            "camera": w.camera_dock,
        }
        sides = (
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        if on:
            if w._filament_dock_areas is None:
                w._filament_dock_areas = {
                    name: dock.allowedAreas() for name, dock in docks.items()
                }
            for name, dock in docks.items():
                dock.setAllowedAreas(Qt.DockWidgetArea.NoDockWidgetArea)
                bind_tile_opacity(dock, name, w._filament_opacity)
                bind_tile_size(
                    dock, name, w._filament_tile_sizes, w._filament_tile_pos
                )
                if not getattr(dock, "_filament_afloat_bound", False):
                    dock._filament_afloat_bound = True
                    dock.topLevelChanged.connect(
                        lambda floating, d=dock, n=name: self._filament_refuse_dock(
                            d, n, floating
                        )
                    )
            for widget, name in self._filament_extra_tiles():
                bind_tile_opacity(widget, name, w._filament_opacity)
                bind_tile_size(
                    widget, name, w._filament_tile_sizes, w._filament_tile_pos
                )
        else:
            parked = w._filament_dock_areas or {}
            w._filament_dock_areas = None
            for name, dock in docks.items():
                dock.setAllowedAreas(parked.get(name, sides))
                apply_tile_opacity(dock, 1.0)
            for widget, _name in self._filament_extra_tiles():
                apply_tile_opacity(widget, 1.0)
            w.calendar_window.setMinimumSize(720, 520)

    def _filament_extra_tiles(self) -> list[tuple[object, str]]:
        w = self.window
        extras: list[tuple[object, str]] = [
            (w._filament_chat_tile, "chat"),
            (w.calendar_window, "days"),
            (w.notify_inbox, "notify"),
            (w.contacts_inbox, "contacts"),
        ]
        world = getattr(w, "world_window", None)
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
        w = self.window
        local = w.mapFromGlobal(global_pos)
        bar = getattr(w, "chrome_bar", None)
        if (
            w._filament_chrome_peek
            and bar is not None
            and bar.isVisible()
            and bar.geometry().contains(local)
        ):
            return True
        if w._filament.hit_band(w.rect()).contains(local):
            return True
        if w._filament.prompt_rect(w.rect()).contains(local):
            return True
        floats = getattr(w, "_filament_floats", None)
        if floats is not None:
            hits = list(floats.chips().values())
            hits.extend(getattr(floats, "_beads", {}).values())
            for btn in hits:
                if not btn.isVisible():
                    continue
                top = QRect(btn.mapTo(w, QPoint(0, 0)), btn.size())
                if top.contains(local):
                    return True
        return False

    def _filament_on_mouse_move(self, event) -> None:
        """Sodium used to peek chrome on hover. Filament keeps the slim bar."""
        return

    def _filament_set_chrome_peek(self, on: bool) -> None:
        w = self.window
        if active_theme() != "filament":
            return
        w._filament_chrome_peek = bool(on)
        bar = getattr(w, "chrome_bar", None)
        if bar is None:
            return
        bar.setVisible(on)
        if on:
            bar.raise_()

    def _filament_enter_presence(self) -> None:
        w = self.window
        if w._filament_parked is not None:
            return
        w.act_fullscreen.setEnabled(False)
        # Capture before showNormal. After it, both flags are false and
        # leave would restore a normal window the user never asked for.
        was_full = w.isFullScreen()
        was_max = w.isMaximized()
        parked_geo = QByteArray(w.saveGeometry())
        if was_full or was_max:
            w.showNormal()
        w._filament_woken = False
        w._filament_home = None
        self._filament_pin_home()
        w.title_bar.set_span_choice(w._filament_span)
        world = getattr(w, "world_window", None)
        w._filament_parked = {
            "geometry": parked_geo,
            "maximized": was_max,
            "fullscreen": was_full,
            "docks": {
                "think": not w.think_dock.isHidden(),
                "work": not w.work_dock.isHidden(),
                "history": not w.history_dock.isHidden(),
                "camera": not w.camera_dock.isHidden(),
                "notify": not w.notify_inbox.isHidden(),
                "contacts": not w.contacts_inbox.isHidden(),
                "calendar": not w.calendar_window.isHidden(),
                "world": world is not None and not world.isHidden(),
            },
        }
        w._filament_hiding = True
        try:
            w.title_bar.set_slim(True)
            w.readiness_strip.hide()
            w.think_dock.hide()
            w.work_dock.hide()
            w.history_dock.hide()
            w.camera_dock.hide()
            w.notify_inbox.hide()
            w.contacts_inbox.hide()
            w.calendar_window.hide()
            if world is not None:
                world.hide()
        finally:
            w._filament_hiding = False
        self._filament_apply_glass(True)
        self._filament_lock_tiles(True)
        self._filament_place_entity()
        apply = getattr(w.conversation, "apply_filament_desk", None)
        if callable(apply):
            apply(True, chat_open=False)
        w._sync_panel_margins()
        w._sync_view_checks()
        from arelis.ui.idle_host import sync_idle_mode

        sync_idle_mode(w)
        self._place_filament_floats()
        self._filament_apply_shape()
        w._flush_glass_surface()
        w.update()

    def _filament_leave_presence(self) -> None:
        w = self.window
        w.act_fullscreen.setEnabled(True)
        parked = w._filament_parked
        w._filament_parked = None
        w._filament_home = None
        w._filament_chrome_peek = False
        self._filament_set_chat_open(False)
        self._filament_lock_tiles(False)
        self._filament_apply_glass(False)
        w.clearMask()
        self._filament_dock_chrome()
        w.readiness_strip.show()
        apply = getattr(w.conversation, "apply_filament_desk", None)
        if callable(apply):
            apply(False)
        if parked is None:
            w._sync_panel_margins()
            from arelis.ui.idle_host import sync_idle_mode

            sync_idle_mode(w)
            return
        docks = parked.get("docks") or {}
        w._filament_hiding = True
        try:
            w.think_dock.setVisible(bool(docks.get("think")))
            w.work_dock.setVisible(bool(docks.get("work")))
            w.history_dock.setVisible(bool(docks.get("history")))
            w.camera_dock.setVisible(bool(docks.get("camera")))
            if docks.get("notify"):
                w.notify_inbox.show()
            else:
                w.notify_inbox.hide()
            if docks.get("contacts"):
                w.contacts_inbox.show()
            else:
                w.contacts_inbox.hide()
            if docks.get("calendar"):
                w.calendar_window.show()
            else:
                w.calendar_window.hide()
            world = getattr(w, "world_window", None)
            if world is not None:
                if docks.get("world"):
                    world.show()
                else:
                    world.hide()
        finally:
            w._filament_hiding = False
        if self._filament_can_claim_desk():
            geo = parked.get("geometry")
            if parked.get("fullscreen"):
                w.showFullScreen()
            elif parked.get("maximized"):
                w.showMaximized()
            else:
                w.showNormal()
                if geo:
                    w.restoreGeometry(geo)
        w._sync_panel_margins()
        w._sync_view_checks()
        from arelis.ui.idle_host import sync_idle_mode

        sync_idle_mode(w)
        w._apply_round_mask()
        w.update()

    def _sync_filament_face(self) -> None:
        w = self.window
        on = active_theme() == "filament"
        floats = getattr(w, "_filament_floats", None)
        if floats is None:
            return
        if on:
            self.take_hwnd()
            floats.setVisible(True)
            self._place_filament_floats()
            apply_hands_face(w)
        else:
            floats.setVisible(False)
            self.release_hwnd()
            apply_hands_face(w)
        empty = getattr(getattr(w, "chat", None), "empty", None)
        if empty is not None and hasattr(empty, "apply_theme_face"):
            empty.apply_theme_face()

    def _place_filament_floats(self, *, reshape: bool = True) -> None:
        w = self.window
        floats = getattr(w, "_filament_floats", None)
        if floats is None or active_theme() != "filament":
            return
        history = getattr(w, "history_dock", None)
        think = getattr(w, "think_dock", None)
        work = getattr(w, "work_dock", None)
        cal = getattr(w, "calendar_window", None)
        camera = getattr(w, "camera_dock", None)
        notify = getattr(w, "notify_inbox", None)
        contacts = getattr(w, "contacts_inbox", None)
        world = getattr(w, "world_window", None)
        floats.skip("reality", not world_available())
        hidden = set()
        if not world_available():
            hidden.add("reality")
        w._filament.set_hidden_faces(hidden)
        floats.set_open("history", self._filament_plate_open(history))
        floats.set_open("thinking", self._filament_plate_open(think))
        floats.set_open("files", self._filament_plate_open(work))
        floats.set_open("days", self._filament_plate_open(cal))
        floats.set_open("camera", self._filament_plate_open(camera))
        floats.set_open("notify", self._filament_plate_open(notify))
        floats.set_open("contacts", self._filament_plate_open(contacts))
        floats.set_open("reality", self._filament_plate_open(world))
        floats.set_open("chat", bool(w._filament_chat_open))
        live: set[str] = set()
        if self._filament_weather() == "think" or getattr(
            w, "_confirm_waiting", False
        ):
            live.add("thinking")
        unread = 0
        center = getattr(w, "notify_center", None)
        if center is not None:
            unread = int(center.unread_count())
        if unread > 0 and not self._filament_plate_open(notify):
            live.add("notify")
        w._filament.set_live_faces(live)
        w._filament.set_load("camera" if self._filament_plate_open(camera) else "")
        floats.place(w.rect())
        self._filament_sync_tethers()
        if reshape:
            self._filament_apply_shape()

    def _filament_sync_tethers(self) -> None:
        w = self.window
        tiles = {
            "history": getattr(w, "history_dock", None),
            "thinking": getattr(w, "think_dock", None),
            "files": getattr(w, "work_dock", None),
            "days": getattr(w, "calendar_window", None),
            "camera": getattr(w, "camera_dock", None),
            "notify": getattr(w, "notify_inbox", None),
            "contacts": getattr(w, "contacts_inbox", None),
            "reality": getattr(w, "world_window", None),
            "chat": getattr(w, "_filament_chat_tile", None),
        }
        open_faces = {
            name
            for name, widget in tiles.items()
            if widget is not None and not widget.isHidden()
        }
        w._filament.set_open_faces(open_faces)
        for name, widget in tiles.items():
            if widget is None or widget.isHidden():
                w._filament.bind_tether(name, None)
                continue
            geo = widget.frameGeometry()
            local = QRect(w.mapFromGlobal(geo.topLeft()), geo.size())
            anchor = w._filament.anchor_point(name, w.rect())
            w._filament.bind_tether(name, attach_on_rect(local, anchor))

    def _on_filament_float(self, name: str) -> None:
        w = self.window
        if name == "chat":
            self._filament_set_chat_open(not w._filament_chat_open)
            return
        if name == "rooms":
            chips = w._filament_floats.chips()
            w._show_rooms_menu(chips.get("rooms") or w)
            return
        if name == "history":
            w.act_history.trigger()
        elif name == "thinking":
            w.act_thinking.trigger()
        elif name == "files":
            w.act_workspace.trigger()
        elif name == "days":
            w.act_calendar.trigger()
        elif name == "camera":
            w.act_camera.trigger()
        elif name == "notify":
            w.act_notifications.trigger()
        elif name == "contacts":
            w.act_contacts.trigger()
        elif name == "reality":
            self._filament_open_reality()

    def _filament_open_reality(self) -> None:
        """The particle is the door. Orbit still cannot open the plate."""
        w = self.window
        if not world_available():
            from arelis.ui.world_host import toggle_world

            toggle_world(w, True)
            return
        if self._filament_plate_open(getattr(w, "world_window", None)):
            from arelis.ui.world_host import toggle_world

            toggle_world(w, False)
            return
        room_id = str(getattr(w.conversation.room, "room_id", "") or "")
        if room_id != PHYSICS_ROOM_ID:
            w._enter_room_from_menu(PHYSICS_ROOM_ID)
        from arelis.ui.world_host import toggle_world

        toggle_world(w, True, force=True)

    def _filament_refuse_dock(self, dock: QDockWidget, name: str, floating: bool) -> None:
        if active_theme() != "filament" or floating or dock.isHidden():
            return
        dock.setAllowedAreas(Qt.DockWidgetArea.NoDockWidgetArea)
        dock.setFloating(True)
        apply_dock_chrome(dock, True)

    def _filament_dress_tile(self, widget, name: str) -> None:
        w = self.window
        w._filament_woken = True
        widget.setMinimumSize(240, 180)
        apply_tile_opacity(widget, w._filament_opacity.get(name, DEFAULT_OPACITY))
        bind_tile_opacity(widget, name, w._filament_opacity)
        apply_tile_size(widget, name, w._filament_tile_sizes)
        bind_tile_size(widget, name, w._filament_tile_sizes, w._filament_tile_pos)

    def _filament_present_tile(self, dock: QDockWidget, name: str) -> None:
        if active_theme() != "filament" or dock.isHidden():
            return
        dock.setAllowedAreas(Qt.DockWidgetArea.NoDockWidgetArea)
        dock.setFloating(True)
        apply_dock_chrome(dock, True)
        self._filament_dress_tile(dock, name)
        self._filament_place_near_title(dock, name)

    def _filament_place_near_title(self, widget, name: str) -> None:
        w = self.window
        p = w._filament.title_point(name, w.rect())
        origin = w.mapToGlobal(QPoint(int(p.x()) + 12, int(p.y()) + 24))
        size = w._filament_tile_sizes.get(name) or DEFAULT_SIZES.get(name, (320, 280))
        parked = w._filament_tile_pos.get(name)
        if (
            active_theme() == "filament"
            and parked is not None
            and origin_on_a_desk(parked[0], parked[1], size[0], size[1])
        ):
            dest = QRect(int(parked[0]), int(parked[1]), int(size[0]), int(size[1]))
            start = w._filament.bead_point(name, w.rect())
            local = QRect(w.mapFromGlobal(dest.topLeft()), dest.size())
            w._filament.bind_tether(name, attach_on_rect(local, start))
            widget.setMinimumSize(240, 180)
            apply_tile_opacity(
                widget, w._filament_opacity.get(name, DEFAULT_OPACITY)
            )
            widget.setGeometry(dest)
            widget.show()
            widget.raise_()
            self._place_filament_floats()
            return
        if active_theme() == "filament":
            dest = QRect(w.mapFromGlobal(origin), QSize(int(size[0]), int(size[1])))
            start = w._filament.bead_point(name, w.rect())
            w._filament.bind_tether(name, attach_on_rect(dest, start))
            play_tile_grow(
                widget,
                origin,
                size,
                opacity=w._filament_opacity.get(name, DEFAULT_OPACITY),
            )
            self._place_filament_floats()
            return
        widget.move(origin)
        widget.show()
        widget.raise_()

    def _filament_set_chat_open(self, on: bool) -> None:
        w = self.window
        want = bool(on)
        if want == w._filament_chat_open and (
            want is False or w.conversation.chat.parent() is w._filament_chat_tile.body
        ):
            if want:
                w._filament_chat_tile.show()
                w._filament_chat_tile.raise_()
            self._place_filament_floats()
            return
        if want:
            self._filament_mount_chat()
            w._filament_chat_open = True
            self._filament_dress_tile(w._filament_chat_tile, "chat")
            self._filament_place_near_title(w._filament_chat_tile, "chat")
        else:
            if active_theme() == "filament":
                flush_tile_geom(w._filament_chat_tile)
            self._filament_unmount_chat()
            w._filament_chat_open = False
            w._filament_chat_tile.hide()
        apply = getattr(w.conversation, "apply_filament_desk", None)
        if callable(apply) and active_theme() == "filament":
            apply(True, chat_open=want)
        self._place_filament_floats()

    def _on_filament_chat_closed(self) -> None:
        if self.window._filament_chat_open:
            self._filament_set_chat_open(False)

    def _filament_mount_chat(self) -> None:
        w = self.window
        conv = w.conversation
        tile = w._filament_chat_tile
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
        apply_tile_size(tile, "chat", w._filament_tile_sizes)

    def _filament_unmount_chat(self) -> None:
        w = self.window
        conv = w.conversation
        tile = w._filament_chat_tile
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

    def _build_filament_menu(self) -> QMenu:
        """Leave hatch when chrome is gone. Themes first so sodium is one click."""
        w = self.window
        w._sync_view_checks()
        menu = QMenu(w)
        menu.setObjectName("FilamentMenu")
        themes = menu.addMenu("themes")
        for act in w._theme_actions.values():
            themes.addAction(act)
        menu.addSeparator()
        settings = menu.addAction("settings")
        from arelis.ui.settings_host import open_settings

        settings.triggered.connect(lambda: open_settings(w))
        chat = menu.addAction("chat")
        chat.setCheckable(True)
        chat.setChecked(bool(w._filament_chat_open))
        chat.triggered.connect(lambda c=False: self._filament_set_chat_open(bool(c)))
        desks = menu.addMenu("desks")
        have = len(filament_row_desks(w, w._filament_home)[0])
        for n, label in ((1, "1 monitor"), (2, "2 monitors"), (3, "3 monitors")):
            act = desks.addAction(label)
            act.setCheckable(True)
            act.setChecked(w._filament_span == n)
            act.setEnabled(n <= max(1, have))
            act.triggered.connect(lambda _c=False, k=n: self._filament_set_span(k))
        rooms = w._build_rooms_menu()
        rooms.setTitle("rooms")
        menu.addMenu(rooms)
        menu.addSeparator()
        menu.addAction(w.act_thinking)
        menu.addAction(w.act_workspace)
        menu.addAction(w.act_history)
        menu.addAction(w.act_notifications)
        menu.addAction(w.act_camera)
        menu.addAction(w.act_contacts)
        menu.addAction(w.act_calendar)
        if world_available():
            menu.addAction(w.act_world)
        menu.addSeparator()
        menu.addAction(w.act_always_on_top)
        menu.addAction(w.act_shortcuts)
        return menu

    def _popup_filament_menu(self, global_pos) -> None:
        self._build_filament_menu().exec(global_pos)


def _of(window) -> FilamentDesk:
    for name in ("filament", "desk"):
        desk = getattr(window, name, None)
        if isinstance(desk, FilamentDesk) and desk.window is window:
            return desk
    return FilamentDesk(window)


def filament_weather(window) -> str:
    return _of(window)._filament_weather()


def filament_can_claim_desk(window) -> bool:
    return _of(window)._filament_can_claim_desk()


def filament_apply_glass(window, on: bool) -> None:
    _of(window)._filament_apply_glass(on)


def filament_pin_home(window) -> QRect | None:
    return _of(window)._filament_pin_home()


def filament_set_span(window, n: int) -> None:
    _of(window)._filament_set_span(n)


def filament_place_entity(window) -> None:
    _of(window)._filament_place_entity()


def filament_fill_home_desk(window, pinned: QRect) -> None:
    _of(window)._filament_fill_home_desk(pinned)


def filament_is_spanned(window) -> bool:
    return _of(window)._filament_is_spanned()


def filament_toggle_span(window) -> None:
    _of(window)._filament_toggle_span()


def filament_apply_shape(window) -> None:
    _of(window)._filament_apply_shape()


def filament_place_chrome(window) -> None:
    _of(window)._filament_place_chrome()


def filament_dock_chrome(window) -> None:
    _of(window)._filament_dock_chrome()


def filament_lock_tiles(window, on: bool) -> None:
    _of(window)._filament_lock_tiles(on)


def filament_extra_tiles(window) -> list[tuple[object, str]]:
    return _of(window)._filament_extra_tiles()


def filament_plate_open(widget) -> bool:
    return FilamentDesk._filament_plate_open(widget)


def filament_native_hit(window, event_type, message):
    return _of(window)._filament_native_hit(event_type, message)


def filament_wants_click(window, global_pos) -> bool:
    return _of(window)._filament_wants_click(global_pos)


def filament_on_mouse_move(window, event) -> None:
    _of(window)._filament_on_mouse_move(event)


def filament_set_chrome_peek(window, on: bool) -> None:
    _of(window)._filament_set_chrome_peek(on)


def filament_enter_presence(window) -> None:
    _of(window).take_hwnd()


def filament_leave_presence(window) -> None:
    _of(window).release_hwnd()


def take_hwnd(window) -> None:
    _of(window).take_hwnd()


def release_hwnd(window) -> None:
    _of(window).release_hwnd()


def bind(window) -> None:
    _of(window).bind()


def sync_filament_face(window) -> None:
    _of(window)._sync_filament_face()


def place_filament_floats(window, *, reshape: bool = True) -> None:
    _of(window)._place_filament_floats(reshape=reshape)


def filament_sync_tethers(window) -> None:
    _of(window)._filament_sync_tethers()


def on_filament_float(window, name: str) -> None:
    _of(window)._on_filament_float(name)


def filament_open_reality(window) -> None:
    _of(window)._filament_open_reality()


def filament_refuse_dock(window, dock: QDockWidget, name: str, floating: bool) -> None:
    _of(window)._filament_refuse_dock(dock, name, floating)


def filament_dress_tile(window, widget, name: str) -> None:
    _of(window)._filament_dress_tile(widget, name)


def filament_present_tile(window, dock: QDockWidget, name: str) -> None:
    _of(window)._filament_present_tile(dock, name)


def filament_place_near_title(window, widget, name: str) -> None:
    _of(window)._filament_place_near_title(widget, name)


def filament_set_chat_open(window, on: bool) -> None:
    _of(window)._filament_set_chat_open(on)


def on_filament_chat_closed(window) -> None:
    _of(window)._on_filament_chat_closed()


def filament_mount_chat(window) -> None:
    _of(window)._filament_mount_chat()


def filament_unmount_chat(window) -> None:
    _of(window)._filament_unmount_chat()


def build_filament_menu(window) -> QMenu:
    return _of(window)._build_filament_menu()


def popup_filament_menu(window, global_pos) -> None:
    _of(window)._popup_filament_menu(global_pos)
