"""Orbit idle face and away-rest. Window methods stay as delegates."""

from __future__ import annotations

from arelis.presence.readiness import ChipLevel
from arelis.ui.theme import active_theme


def idle_eligible(window) -> bool:
    """Orbit face: empty thread, nothing to decide. Docks may stay open."""
    if window.chat.has_messages:
        return False
    if window._turn_busy:
        return False
    if window.conversation.confirm_open():
        return False
    # Stay on the orbit while dictate/talk is latched on an empty thread.
    # Leaving idle here reparented the voice buttons and unchecked
    # Ctrl+Shift+M (conversation on, then immediately wake).
    overlay = window.conversation.notify_overlay
    if overlay is not None and overlay.expanded:
        return False
    return True


def sync_idle_mode(window) -> None:
    idle = idle_eligible(window)
    window.conversation.set_idle_mode(idle)
    instruments = any(
        not dock.isHidden()
        for dock in (
            window.think_dock,
            window.work_dock,
            window.history_dock,
            window.camera_dock,
        )
    ) or (not window.notify_inbox.isHidden()) or (not window.contacts_inbox.isHidden()) or (
        not window.calendar_window.isHidden()
    ) or (not window.world_window.isHidden())
    filament = active_theme() == "filament"
    window.readiness_strip.setVisible((not idle or instruments) and not filament)
    empty = getattr(window.chat, "empty", None)
    if empty is not None and hasattr(empty, "set_side_chrome"):
        empty.set_side_chrome(
            ghosts=idle
            and window.history_dock.isHidden()
            and window.camera_dock.isHidden()
            and not filament,
            readout=idle and not window.readiness_strip.isVisible() and not filament,
        )
    if filament:
        apply = getattr(window.conversation, "apply_filament_desk", None)
        if callable(apply):
            apply(True, chat_open=bool(getattr(window, "_filament_chat_open", False)))
    refresh_idle_face(window)


def return_to_idle(window) -> None:
    """Esc on an empty thread: close instruments and show Orbit."""
    if window.chat.has_messages:
        return
    window.think_dock.hide()
    window.work_dock.hide()
    window.history_dock.hide()
    window.camera_dock.hide()
    window.calendar_window.hide()
    window._hide_world()
    window._calendar_sync_timer.stop()
    window._calendar_sync_watchdog.stop()
    window.notify_inbox.hide()
    window.contacts_inbox.hide()
    overlay = window.conversation.notify_overlay
    if overlay is not None and overlay.expanded:
        overlay.collapse()
    window._away_resting = False
    window._away_hidden = {}
    window.conversation.input.clear()
    sync_idle_mode(window)


def away_rest_blocked(window) -> bool:
    if window._turn_busy:
        return True
    if window.conversation.confirm_open():
        return True
    if window.conversation.conversation_btn.isChecked():
        return True
    if window.conversation.mic_btn.isChecked():
        return True
    if window._drive_session:
        return True
    return False


def arm_away_rest_timer(window) -> None:
    timer = getattr(window, "_away_timer", None)
    if timer is None:
        return
    if not window._away_rest or window._away_resting:
        timer.stop()
        return
    timer.start(max(1, int(window._away_rest_min)) * 60 * 1000)


def note_engagement(window) -> None:
    """A real use: click, type, send, wake, Allow — not mouse-move or STATUS."""
    if window._away_resting:
        wake_from_away_rest(window)
        return
    arm_away_rest_timer(window)


def enter_away_rest(window) -> None:
    if not window._away_rest or window._away_resting:
        return
    if away_rest_blocked(window):
        arm_away_rest_timer(window)
        return
    hidden = {
        "thinking": not window.think_dock.isHidden(),
        "workspace": not window.work_dock.isHidden(),
        "history": not window.history_dock.isHidden(),
        "camera": not window.camera_dock.isHidden(),
        "calendar": not window.calendar_window.isHidden(),
        "notify": not window.notify_inbox.isHidden(),
        "contacts": not window.contacts_inbox.isHidden(),
    }
    if not any(hidden.values()):
        return
    window._away_hidden = hidden
    window._away_resting = True
    window.think_dock.hide()
    window.work_dock.hide()
    window.history_dock.hide()
    window.camera_dock.hide()
    window.calendar_window.hide()
    window._hide_world()
    window._calendar_sync_timer.stop()
    window._calendar_sync_watchdog.stop()
    window.notify_inbox.hide()
    window.contacts_inbox.hide()
    if hidden.get("camera"):
        try:
            window.camera.stop()
        except Exception:
            pass
    try:
        from arelis.ui.hands_host import park_hands

        park_hands(window)
    except Exception:
        pass
    overlay = window.conversation.notify_overlay
    if overlay is not None and overlay.expanded:
        overlay.collapse()
    window._away_timer.stop()
    sync_idle_mode(window)


def wake_from_away_rest(window) -> None:
    if not window._away_resting:
        arm_away_rest_timer(window)
        return
    hidden = dict(window._away_hidden)
    window._away_resting = False
    window._away_hidden = {}
    if hidden.get("thinking"):
        window.think_dock.show()
    if hidden.get("workspace"):
        window.work_dock.show()
    if hidden.get("history"):
        window.history_dock.show()
        from arelis.ui.history_host import refresh_history

        refresh_history(window)
    if hidden.get("camera"):
        window.camera_dock.show()
        window.camera.start()
    if hidden.get("calendar"):
        window.calendar_window.show()
        window.calendar_window.raise_()
        window.calendar.reload()
        from arelis.ui.calendar_host import kick_calendar_sync

        kick_calendar_sync(window)
        window._calendar_sync_timer.start()
    if hidden.get("notify"):
        window.notify_inbox.show()
        window.notify_inbox.raise_()
    if hidden.get("contacts"):
        window.contacts_inbox.show()
        window.contacts_inbox.raise_()
    window._stack_left_instruments()
    sync_idle_mode(window)
    arm_away_rest_timer(window)
    try:
        from arelis.ui.hands_host import resume_hands

        resume_hands(window)
    except Exception:
        pass


def on_idle_readiness(window, snapshot) -> None:
    window._readiness_snap = snapshot
    # The world-state line wants to know whether a picture can be made, and
    # this probe already asked. Parking the answer on the config keeps the
    # question off the per-turn path, which is no place for a socket.
    chip = snapshot.chip("image") if hasattr(snapshot, "chip") else None
    if chip is not None:
        window.config["_image_ready"] = chip.status == ChipLevel.OK
    refresh_idle_face(window)


def sync_idle_voice_mode(window, mode: str | None = None) -> None:
    """Idle copy under the orbit follows the latched voice mode.

    Falls back to the buttons when the controller has not reported yet, so a
    chord that latched conversation before the mic opened still shows.
    """
    idle = getattr(window.chat, "empty", None)
    if idle is None or not hasattr(idle, "set_voice_mode"):
        return
    if mode is None:
        if window.conversation.conversation_btn.isChecked():
            mode = "conversation"
        elif window.conversation.mic_btn.isChecked():
            mode = "dictate"
        else:
            # Cosmetic copy under the orbit. It runs from _refresh_idle_face,
            # which every terminal event goes through, so it must not be able
            # to raise: an idle label is not worth losing ASSISTANT_DONE and
            # leaving the composer stuck in its busy state.
            mode_fn = getattr(window.voice_controller, "mode", None)
            mode = mode_fn() if callable(mode_fn) else "off"
    idle.set_voice_mode(mode or "off")


def refresh_idle_face(window) -> None:
    idle = getattr(window.chat, "empty", None)
    if idle is None or not hasattr(idle, "set_sessions"):
        return
    sync_idle_voice_mode(window)
    sessions = window.history.recent_sessions(3)
    if sessions != window._idle_ghosts:
        window._idle_ghosts = sessions
        idle.set_sessions(sessions)
    ollama = "—"
    snap = window._readiness_snap
    if snap is not None:
        chip = snap.chip("ollama") if hasattr(snap, "chip") else None
        if chip is not None:
            ollama = str(chip.status.value).upper()
    listening = "OFF"
    vc = getattr(window, "voice_controller", None)
    if not getattr(window, "_voice_ear_ready", True):
        listening = "getting"
    elif vc is not None and bool(getattr(vc, "listening", False)):
        listening = "ON"
    elif (
        window.conversation.mic_btn.isChecked()
        or window.conversation.conversation_btn.isChecked()
    ):
        listening = "ON"
    idle.set_readout(ollama=ollama, listening=listening)


def bind_idle(window) -> None:
    overlay = window.conversation.notify_overlay
    overlay.collapsed.connect(lambda: sync_idle_mode(window))
    window.conversation.idle_conditions_changed.connect(
        lambda: sync_idle_mode(window)
    )
    window.conversation.input.textChanged.connect(lambda: note_engagement(window))
    window.readiness_updated.connect(lambda snap: on_idle_readiness(window, snap))
    window._away_timer.timeout.connect(lambda: enter_away_rest(window))

