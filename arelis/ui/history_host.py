"""History dock, session load, and the rooms menu. Window methods stay as delegates."""

from __future__ import annotations

import asyncio
import time

from PySide6.QtCore import QPoint
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from arelis.core.events import Event, EventType


def show_rooms_menu(window, anchor) -> None:
    menu = window._build_rooms_menu()
    menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))


def build_rooms_menu(window) -> QMenu:
    """Places, not panels. Same enter/leave path as typing or saying it."""
    menu = QMenu(window)
    menu.setObjectName("RoomsMenu")
    store = window.config.get("_rooms")
    rooms = list(store.all()) if store is not None else []
    active = ""
    if store is not None:
        active = str(getattr(store, "active_id", "") or "")
    if not active:
        active = str(getattr(window.conversation.room, "room_id", "") or "")

    if not rooms:
        empty = QAction("no rooms yet", window)
        empty.setEnabled(False)
        menu.addAction(empty)
    else:
        busy = window._turn_busy
        for room in rooms:
            act = QAction(room.name or room.id, window)
            act.setCheckable(True)
            act.setChecked(room.id == active)
            act.setEnabled(not busy)
            if busy:
                act.setToolTip("Finish or stop the current turn first.")
            elif room.purpose:
                act.setToolTip(room.purpose)
            act.triggered.connect(
                lambda _checked=False, rid=room.id: window._enter_room_from_menu(rid)
            )
            menu.addAction(act)
    menu.addSeparator()
    leave = QAction("leave", window)
    leave.setEnabled(bool(active) and not window._turn_busy)
    leave.triggered.connect(window._leave_room)
    menu.addAction(leave)
    return menu


def enter_room_from_menu(window, room_id: str) -> None:
    if not room_id:
        return
    if window._turn_busy:
        window._toast_finish_or_stop(
            "Finish or stop the current turn before switching rooms."
        )
        return
    asyncio.run_coroutine_threadsafe(
        window.bus.publish(Event(EventType.USER_MESSAGE, {"text": f"/room {room_id}"})),
        window.loop,
    )


def refresh_history(window) -> None:
    if window.store is None:
        return
    sessions = [
        {
            "id": str(row.get("id") or ""),
            "started_at": str(row.get("started_at") or ""),
            "title": str(row.get("title") or ""),
        }
        for row in window.store.list_sessions(limit=100)
    ]
    window.history.set_sessions(sessions)
    window.history.set_pending_facts(window.store.list_facts(status="pending", limit=50))
    if window.store.session_id:
        window.history.set_active(window.store.session_id)
    window._refresh_idle_face()


def on_fact_decided(window, fact_ids: object, status: str) -> None:
    """Approve/reject pending (History) or forget active (Settings → Memory)."""
    if window.store is None:
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
        if window.store.set_fact_status(fact_id, status):
            changed += 1
    if not changed:
        return
    label = "approved" if status == "active" else "rejected"
    if changed == 1:
        window.thinking.append(f"fact {label}", kind="status")
    else:
        window.thinking.append(f"{changed} facts {label}", kind="status")
    window._refresh_history()


def on_history_selected(window, session_id: str) -> None:
    if window._turn_busy:
        window._toast_finish_or_stop(
            "Finish or stop the current turn before switching conversations."
        )
        seated = ""
        if window.store is not None:
            seated = str(window.store.session_id or "")
        window.history.set_active(seated)
        return
    window._request_session_load(session_id)


def on_history_delete(window, session_id: str) -> None:
    if window.store is None:
        return
    if window._turn_busy:
        window._toast_finish_or_stop(
            "Finish or stop the current turn before deleting a conversation."
        )
        return
    sid = str(session_id or "").strip()
    if not sid:
        return
    was_active = window.store.session_id == sid
    if not window.store.delete_session(sid):
        window.chat.add_system("Could not delete that conversation.")
        return
    window.thinking.append("Conversation deleted.", kind="status")
    window._refresh_history()
    if was_active:
        asyncio.run_coroutine_threadsafe(
            window.bus.publish(Event(EventType.SESSION_LOAD, {"new": True})),
            window.loop,
        )


def on_history_new(window) -> None:
    if window._turn_busy:
        window._toast_finish_or_stop(
            "Finish or stop the current turn before starting a new conversation."
        )
        return
    asyncio.run_coroutine_threadsafe(
        window.bus.publish(Event(EventType.SESSION_LOAD, {"new": True})),
        window.loop,
    )


def toast_finish_or_stop(window, message: str) -> None:
    """Single amber toast per busy episode (debounce L3 spam)."""
    now = time.monotonic()
    last = float(getattr(window, "_finish_stop_toast_at", 0.0) or 0.0)
    if now - last < 1.5:
        return
    window._finish_stop_toast_at = now
    window.chat.add_system(message)


def request_session_load(window, session_id: str) -> None:
    if not session_id:
        return
    asyncio.run_coroutine_threadsafe(
        window.bus.publish(Event(EventType.SESSION_LOAD, {"session_id": session_id})),
        window.loop,
    )


def leave_room(window) -> None:
    """The strip's leave button, routed through the same command as typing.

    Publishing the command rather than reaching for the orchestrator keeps
    the window free of a reference to it, the way session loads already do,
    and means both routes out of a room share one implementation.
    """
    if window._turn_busy:
        window._toast_finish_or_stop(
            "Finish or stop the current turn before leaving the room."
        )
        return
    asyncio.run_coroutine_threadsafe(
        window.bus.publish(Event(EventType.USER_MESSAGE, {"text": "/leave"})),
        window.loop,
    )

