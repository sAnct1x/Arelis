"""Thin ArelisWindow names that hosts and tests still call.

Bodies live on docks, Reality, FilamentDesk, history, notify, and SMS.
This mixin keeps ``window._foo`` working so the next sitting does not
reopen ``app.py`` for a View toggle.
"""

from __future__ import annotations

from typing import Any

from arelis.spatial.verbs import PhysicsAct
from arelis.ui.hands_host import on_hands_chip
from arelis.ui.history_host import (
    build_rooms_menu,
    enter_room_from_menu,
    show_rooms_menu,
    toast_finish_or_stop,
)
from arelis.ui.notify_host import sync_notify_surface
from arelis.ui.sms_host import operator_send_sms
from arelis.ui.window_docks import (
    docked_in,
    history_camera_tabbed,
    left_column_member,
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
from arelis.ui.world_host import (
    apply_physics_act,
    apply_physics_verb,
    apply_tile,
    hide_and_reset_world,
    on_world_window_closed,
    open_world,
    toggle_world,
    touch_solar,
    try_physics_verb,
)


class WindowAliases:
    def _reveal_dock(self, dock, action=None, *, asked: bool = False) -> None:
        return reveal_dock(self, dock, action, asked=asked)

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

    def _toggle_world(self, checked: bool, page: str = "", *, force: bool = False) -> None:
        return toggle_world(self, checked, page=page, force=force)

    def _hide_world(self) -> None:
        return hide_and_reset_world(self)

    def _try_physics_verb(self, text: str) -> bool:
        return try_physics_verb(self, text)

    def _apply_physics_verb(
        self,
        verb: str,
        *,
        name: str = "",
        flag: str = "",
        on: bool | None = None,
        page: str = "",
    ) -> None:
        return apply_physics_verb(self, verb, name=name, flag=flag, on=on, page=page)

    def _apply_physics_act(self, act: PhysicsAct) -> None:
        return apply_physics_act(self, act)

    def _touch_solar(self) -> None:
        return touch_solar(self)

    def _apply_tile(self, name: str, *, show: bool, page: str = "") -> None:
        return apply_tile(self, name, show=show, page=page)

    def _on_world_window_closed(self) -> None:
        return on_world_window_closed(self)

    def _on_hands_chip(self, on: bool) -> None:
        return on_hands_chip(self, on)

    def _on_dock_visibility(self, visible: bool) -> None:
        return on_dock_visibility(self, visible)

    def _docked_in(self, dock, area):
        return docked_in(self, dock, area)

    def _left_column_member(self, dock) -> bool:
        return left_column_member(self, dock)

    def _history_camera_tabbed(self) -> bool:
        return history_camera_tabbed(self)

    def _stack_left_instruments(self) -> None:
        return stack_left_instruments(self)

    def _sync_panel_margins(self) -> None:
        return sync_panel_margins(self)

    def _sanitize_floating_docks(self) -> None:
        return sanitize_floating_docks(self)

    def _show_rooms_menu(self, anchor) -> None:
        return show_rooms_menu(self, anchor)

    def _build_rooms_menu(self):
        return build_rooms_menu(self)

    def _enter_room_from_menu(self, room_id: str) -> None:
        return enter_room_from_menu(self, room_id)

    def _toast_finish_or_stop(self, message: str) -> None:
        return toast_finish_or_stop(self, message)

    def _sync_notify_surface(self) -> None:
        return sync_notify_surface(self)

    def _on_notify_poll(self) -> None:
        from arelis.ui.notify_host import on_notify_poll

        return on_notify_poll(self)

    def _on_mail_headers(self, rows: object) -> None:
        from arelis.ui.notify_host import on_mail_headers

        return on_mail_headers(self, rows)

    def _on_sms_received(self, payload: dict[str, Any]) -> None:
        from arelis.ui.sms_host import on_sms_received

        return on_sms_received(self, payload)

    def _open_file(self, path: str) -> None:
        from arelis.ui.workspace_host import open_file

        return open_file(self, path)

    def _save_file(self, path: str, content: str) -> None:
        from arelis.ui.workspace_host import save_file

        return save_file(self, path, content)

    def _apply_settings(self, values: dict[str, Any]) -> None:
        from arelis.ui.settings_host import apply_settings

        return apply_settings(self, values)

    async def _operator_send_sms(self, alias: str, phone: str, body: str) -> None:
        return await operator_send_sms(self, alias, phone, body)

    def _build_filament_menu(self):
        from arelis.ui.filament_desk import build_filament_menu

        return build_filament_menu(self)

    def _popup_filament_menu(self, global_pos) -> None:
        from arelis.ui.filament_desk import popup_filament_menu

        return popup_filament_menu(self, global_pos)

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
