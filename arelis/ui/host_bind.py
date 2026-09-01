"""Point Qt signals at host functions. ArelisWindow does not grow mirrors."""

from __future__ import annotations

from arelis.ui.calendar_host import (
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
)
from arelis.ui.camera_host import (
    on_camera_ask,
    on_camera_dock_visibility,
    on_camera_pose,
    on_camera_pose_video,
    on_camera_record,
    on_camera_running_changed,
    on_camera_track,
    on_spatial_hands,
    on_spatial_recording,
)
from arelis.ui.event_host import dispatch_event
from arelis.ui.history_host import (
    on_fact_decided,
    on_history_delete,
    on_history_new,
    on_history_selected,
    show_rooms_menu,
)
from arelis.ui.idle_host import (
    enter_away_rest,
    note_engagement,
    on_idle_readiness,
    refresh_idle_face,
    sync_idle_mode,
)
from arelis.ui.notify_host import (
    on_artifact_requested,
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
)
from arelis.ui.settings_host import on_reach_changed, open_settings
from arelis.ui.sms_host import (
    on_notice_reply,
    on_sms_send_finished,
    on_sms_tile_send,
    on_sms_tile_shown,
    open_sms_chat,
)
from arelis.ui.workspace_host import (
    add_workspace_folder_dialog,
    drop_desk_item,
    keep_note_dialog,
    new_workspace_folder_dialog,
    open_desk_item,
    open_file,
    open_outside,
    pin_desk_item,
    remove_active_workspace_root,
    reveal_desk_item,
    save_file,
)


def bind_window_hosts(window) -> None:
    """Connect docks, panels, and timers to the host modules.

    Call once after the window owns calendar timers and the job tick.
    Filament span / floats stay on the window until FilamentDesk binds them.
    """
    window.title_bar.rooms_menu_requested.connect(lambda a: show_rooms_menu(window, a))
    window.title_bar.settings_requested.connect(lambda: open_settings(window))
    window.readiness_strip.settings_requested.connect(lambda: open_settings(window))

    window.sms_chats.set_send_handler(
        lambda key, body, alias, phone: on_sms_tile_send(window, key, body, alias, phone)
    )
    window.sms_chats.set_shown_handler(
        lambda alias, phone: on_sms_tile_shown(window, alias, phone)
    )
    window.spatial.frame_ready.connect(lambda frame: on_spatial_hands(window, frame))
    window.spatial.recording_changed.connect(lambda on: on_spatial_recording(window, on))
    window.camera.track_toggled.connect(lambda on: on_camera_track(window, on))
    window.camera.record_toggled.connect(lambda on: on_camera_record(window, on))
    window.camera.pose_frame.connect(lambda payload: on_camera_pose(window, payload))
    window.camera.pose_video.connect(
        lambda frame, t: on_camera_pose_video(window, frame, t)
    )
    window.camera.reach_changed.connect(lambda reach: on_reach_changed(window, reach))
    window.camera.ask_arelis.connect(lambda path: on_camera_ask(window, path))
    window.camera.running_changed.connect(
        lambda running: on_camera_running_changed(window, running)
    )
    window.camera_dock.visibilityChanged.connect(
        lambda visible: on_camera_dock_visibility(window, visible)
    )

    window.conversation.input.textChanged.connect(lambda: note_engagement(window))
    window.conversation.leave_room_requested.connect(lambda: _leave(window))
    window.conversation.new_requested.connect(lambda: on_history_new(window))
    window.conversation.session_clicked.connect(
        lambda session_id: on_history_selected(window, session_id)
    )
    window.conversation.idle_conditions_changed.connect(lambda: sync_idle_mode(window))

    window.workspace.open_requested.connect(lambda path: open_file(window, path))
    window.workspace.save_requested.connect(
        lambda path, content: save_file(window, path, content)
    )
    window.workspace.add_root_requested.connect(
        lambda: add_workspace_folder_dialog(window)
    )
    window.workspace.new_root_requested.connect(
        lambda: new_workspace_folder_dialog(window)
    )
    window.workspace.remove_root_requested.connect(
        lambda: remove_active_workspace_root(window)
    )
    window.workspace.keep_requested.connect(lambda: keep_note_dialog(window))
    window.workspace.pin_requested.connect(
        lambda path, pinned: pin_desk_item(window, path, pinned)
    )
    window.workspace.drop_requested.connect(lambda path: drop_desk_item(window, path))
    window.workspace.desk_open_requested.connect(
        lambda path: open_desk_item(window, path)
    )
    window.workspace.reveal_requested.connect(
        lambda path: reveal_desk_item(window, path)
    )
    window.workspace.outside_requested.connect(lambda path: open_outside(window, path))

    window.history.session_selected.connect(
        lambda session_id: on_history_selected(window, session_id)
    )
    window.history.session_delete_requested.connect(
        lambda session_id: on_history_delete(window, session_id)
    )
    window.history.new_requested.connect(lambda: on_history_new(window))
    window.history.fact_decided.connect(
        lambda fact_ids, status: on_fact_decided(window, fact_ids, status)
    )

    window.notifications.unread_changed.connect(
        lambda count: on_notify_unread(window, count)
    )
    window.notifications.opened.connect(lambda: on_inbox_opened(window))
    window.notifications.notice_activated.connect(
        lambda notice_id: on_notice_activated(window, notice_id)
    )
    window.notifications.chat_requested.connect(
        lambda notice_id: open_sms_chat(window, notice_id)
    )
    window.notifications.artifact_requested.connect(
        lambda notice_id, how: on_artifact_requested(window, notice_id, how)
    )
    window.notifications.mark_read_btn.clicked.connect(
        lambda: on_notify_mark_all_read(window)
    )
    window.notify_inbox.closed.connect(lambda: on_notify_inbox_closed(window))
    window.calendar_window.closed.connect(lambda: on_calendar_window_closed(window))

    overlay = window.conversation.notify_overlay
    overlay.dismiss_requested.connect(lambda nid: on_notice_dismiss(window, nid))
    overlay.snooze_requested.connect(lambda nid: on_notice_snooze(window, nid))
    overlay.reply_requested.connect(lambda nid: on_notice_reply(window, nid))
    overlay.open_requested.connect(lambda nid: on_notice_open(window, nid))
    overlay.artifact_requested.connect(
        lambda nid, how: on_artifact_requested(window, nid, how)
    )
    overlay.pill_clicked.connect(lambda: on_notify_pill_clicked(window))
    overlay.collapsed.connect(lambda: sync_idle_mode(window))

    window.readiness_updated.connect(lambda snap: on_idle_readiness(window, snap))
    window.readiness_strip.notify_chip.clicked.connect(
        lambda: on_notify_chip_clicked(window)
    )
    window.mail_headers_ready.connect(lambda rows: on_mail_headers(window, rows))
    window.sms_send_finished.connect(
        lambda key, ok, error: on_sms_send_finished(window, key, ok, error)
    )
    window.bridge.event_arrived.connect(lambda event: dispatch_event(window, event))

    window._away_timer.timeout.connect(lambda: enter_away_rest(window))
    window._notify_timer.timeout.connect(lambda: on_notify_poll(window))
    window._calendar_sync_timer.timeout.connect(lambda: kick_calendar_sync(window))
    window._calendar_sync_watchdog.timeout.connect(
        lambda: on_calendar_sync_watchdog(window)
    )
    window._job_tick.timeout.connect(lambda: on_job_tick(window))

    window.calendar.create_requested.connect(
        lambda payload: on_calendar_create(window, payload)
    )
    window.calendar.update_requested.connect(
        lambda payload: on_calendar_update(window, payload)
    )
    window.calendar.delete_requested.connect(
        lambda event_id: on_calendar_delete(window, event_id)
    )
    window.calendar.sync_requested.connect(lambda: kick_calendar_sync(window))
    window.calendar.task_add_requested.connect(
        lambda title, due: on_calendar_task_add(window, title, due)
    )
    window.calendar.task_status_requested.connect(
        lambda task_id, status: on_calendar_task_status(window, task_id, status)
    )
    window.calendar.task_remove_requested.connect(
        lambda task_id: on_calendar_task_remove(window, task_id)
    )
    window.calendar.job_save_requested.connect(
        lambda payload: on_calendar_job_save(window, payload)
    )
    window.calendar.job_delete_requested.connect(
        lambda job_id: on_calendar_job_delete(window, job_id)
    )
    window.calendar.job_run_requested.connect(
        lambda job_id: on_calendar_job_run(window, job_id)
    )


def _leave(window) -> None:
    from arelis.ui.history_host import leave_room

    leave_room(window)


def apply_startup_hosts(window) -> None:
    """History + idle after voice is attached. One-shot from the constructor."""
    from arelis.ui.history_host import refresh_history
    from arelis.ui.idle_host import arm_away_rest_timer
    from arelis.ui.voice_host import build_voice

    arm_away_rest_timer(window)
    build_voice(window)
    if window.voice_controller is not None:
        window.voice_controller.listening_changed.connect(
            lambda _on: refresh_idle_face(window)
        )
    refresh_history(window)
    sync_idle_mode(window)
