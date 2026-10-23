"""History dock, session load, and the rooms menu. Window methods stay as delegates."""

from __future__ import annotations

import asyncio
import time

from PySide6.QtCore import QPoint
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from arelis.core.events import Event, EventType
from arelis.memory.store_sessions import keep_history_row


def show_rooms_menu(window, anchor) -> None:
    """Leftover from the rooms product. Empty menu so filament chips do not crash."""
    menu = build_rooms_menu(window)
    menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))


def build_rooms_menu(window) -> QMenu:
    """Leftover from the rooms product. Reality is not a room."""
    menu = QMenu(window)
    menu.setObjectName("RoomsMenu")
    empty = QAction("no rooms", window)
    empty.setEnabled(False)
    menu.addAction(empty)
    return menu


def enter_room_from_menu(window, room_id: str) -> None:
    """Leftover from the rooms product. /room is gone."""
    del window, room_id
    return


def refresh_history(window) -> None:
    bind_history_pins(window)
    if window.store is None:
        return
    window.history.set_store(window.store)
    current = str(window.store.session_id or "")
    sessions = [
        {
            "id": str(row.get("id") or ""),
            "started_at": str(row.get("started_at") or ""),
            "title": str(row.get("title") or ""),
            "pinned": bool(row.get("pinned")),
        }
        for row in window.store.list_sessions(limit=100)
        if keep_history_row(row, current_id=current)
    ]
    window.history.set_sessions(sessions)
    window.history.set_pending_facts(window.store.list_facts(status="pending", limit=50))
    if window.store.session_id:
        window.history.set_active(window.store.session_id)
    from arelis.ui.idle_host import refresh_idle_face

    refresh_idle_face(window)


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
    refresh_history(window)


def on_history_selected(window, session_id: str) -> None:
    if window._turn_busy:
        toast_finish_or_stop(
            window,
            "Finish or stop the current turn before switching conversations.",
        )
        seated = ""
        if window.store is not None:
            seated = str(window.store.session_id or "")
        window.history.set_active(seated)
        return
    request_session_load(window, session_id)


def on_history_delete(window, session_id: str) -> None:
    if window.store is None:
        return
    if window._turn_busy:
        toast_finish_or_stop(
            window,
            "Finish or stop the current turn before deleting a conversation.",
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
    refresh_history(window)
    if was_active:
        asyncio.run_coroutine_threadsafe(
            window.bus.publish(Event(EventType.SESSION_LOAD, {"new": True})),
            window.loop,
        )


def on_history_pin(window, session_id: str, on: bool) -> None:
    if window.store is None:
        return
    if window._turn_busy:
        toast_finish_or_stop(
            window,
            "Finish or stop the current turn before pinning a conversation.",
        )
        return
    sid = str(session_id or "").strip()
    if not sid:
        return
    if not window.store.set_session_pinned(sid, bool(on)):
        window.chat.add_system("Could not update that conversation.")
        return
    refresh_history(window)


def focus_history_search(window) -> None:
    """Open past conversations and put the cursor in the search box."""
    from arelis.ui.window_docks import toggle_history

    toggle_history(window, True)
    act = getattr(window, "act_history", None)
    if act is not None:
        act.setChecked(True)
    search = window.history.search
    search.setFocus()
    search.selectAll()


def on_history_new(window) -> None:
    if window._turn_busy:
        toast_finish_or_stop(
            window,
            "Finish or stop the current turn before starting a new conversation.",
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
    """Leftover from the rooms product. /leave is gone."""
    del window
    return


def bind_history_pins(window) -> None:
    """Listen for pin and unpin. Once per window.

    The list is filled from refresh_history, so that is where the listener
    is attached. A second call does not add another one.
    """
    if getattr(window, "_history_pin_bound", False):
        return
    history = getattr(window, "history", None)
    signal = getattr(history, "session_pin_requested", None)
    if signal is None:
        return
    signal.connect(lambda session_id, on: on_history_pin(window, session_id, on))
    window._history_pin_bound = True


def bind_history(window) -> None:
    bind_history_pins(window)
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
    window.conversation.new_requested.connect(lambda: on_history_new(window))
    window.conversation.session_clicked.connect(
        lambda session_id: on_history_selected(window, session_id)
    )
    window.conversation.leave_room_requested.connect(lambda: leave_room(window))
    window.title_bar.rooms_menu_requested.connect(
        lambda anchor: show_rooms_menu(window, anchor)
    )

