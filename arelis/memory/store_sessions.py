"""Session archive: conversations, messages, and summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

from arelis.memory.store import _utc_now

if TYPE_CHECKING:
    from arelis.memory.store import MemoryStore

def start_session(store: MemoryStore, session_id: str | None = None, *, room_id: str = "") -> str:
    """Begin a new session and make it the sink target for later writes."""
    sid = session_id or uuid4().hex
    store._conn.execute(
        "INSERT INTO sessions (id, started_at, title, room_id) VALUES (?, ?, '', ?)",
        (sid, _utc_now(), room_id or ""),
    )
    store._conn.commit()
    store.session_id = sid
    store._ordinal = 0
    store._title_set = False
    return sid

def mint_session(store: MemoryStore, *, room_id: str = "") -> str:
    """Create a conversation without making it this process's open seat."""
    sid = uuid4().hex
    store._conn.execute(
        "INSERT INTO sessions (id, started_at, title, room_id) VALUES (?, ?, '', ?)",
        (sid, _utc_now(), room_id or ""),
    )
    store._conn.commit()
    return sid

def start_glass_session(store: MemoryStore) -> str:
    """Cold glass launch: new conversation. Last real thread stays in history.

    An unused empty shell from a short launch is pruned so History does
    not fill with blank 'new' rows. Tray / un-minimize never call this.

    The shell is re-checked for messages before it is deleted. started_at
    has one-second resolution, so two sessions opened inside the same
    second are ordered arbitrarily, and these two queries can break that
    tie differently — which would cascade-delete a real conversation.

    Both lookups are scoped to general conversations. A room's thread is
    durable by design and is never the leftover shell of a short launch,
    so it must not be reachable by this prune even when it happens to be
    the newest row in the table.
    """
    leftover = store.latest_session_id(require_messages=False, room_id="")
    filled = store.latest_session_id(require_messages=True, room_id="")
    if (
        leftover
        and leftover != filled
        and not store._session_has_messages(leftover)
    ):
        store.delete_session(leftover)
    return store.start_session()

def _session_has_messages(store: MemoryStore, session_id: str) -> bool:
    row = store._conn.execute(
        "SELECT 1 FROM messages WHERE session_id = ? LIMIT 1",
        (session_id,),
    ).fetchone()
    return row is not None

def open_session(store: MemoryStore, session_id: str) -> bool:
    """Point the sink at an existing session. False if it is not in the archive."""
    session = store.get_session(session_id)
    if session is None:
        return False
    row = store._conn.execute(
        "SELECT COALESCE(MAX(ordinal), 0) AS n FROM messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    store.session_id = session_id
    store._ordinal = int(row["n"] if row is not None else 0)
    store._title_set = bool(str(session.get("title") or "").strip())
    return True

def on_message(store: MemoryStore, role: str, content: str, note: str = "") -> None:
    """Persist one message. Called from SessionMemory.add when a sink is set."""
    if store.session_id is None:
        store.start_session()
    store._ordinal += 1
    store._conn.execute(
        """
        INSERT INTO messages (session_id, role, content, note, created_at, ordinal)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (store.session_id, role, content, note, _utc_now(), store._ordinal),
    )
    if role == "user" and not store._title_set and content.strip():
        from arelis.attachments import session_title_from_turn

        title = session_title_from_turn(content)
        if title:
            store._conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, store.session_id),
            )
            store._title_set = True
    store._conn.commit()

def append_to_session(
    store: MemoryStore, session_id: str, role: str, content: str, note: str = ""
) -> bool:
    """Write into another conversation without switching this process's seat."""
    sid = (session_id or "").strip()
    if not sid or store.get_session(sid) is None:
        return False
    row = store._conn.execute(
        "SELECT COALESCE(MAX(ordinal), 0) AS n FROM messages WHERE session_id = ?",
        (sid,),
    ).fetchone()
    ordinal = int(row["n"] if row is not None else 0) + 1
    store._conn.execute(
        """
        INSERT INTO messages (session_id, role, content, note, created_at, ordinal)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (sid, role, content, note, _utc_now(), ordinal),
    )
    session = store.get_session(sid) or {}
    if role == "user" and not str(session.get("title") or "").strip() and content.strip():
        from arelis.attachments import session_title_from_turn

        title = session_title_from_turn(content)
        if title:
            store._conn.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, sid),
            )
    store._conn.commit()
    return True

def on_summary(store: MemoryStore, text: str) -> None:
    if store.session_id is None or not text:
        return
    store._conn.execute(
        """
        INSERT INTO summaries (session_id, text, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            text = excluded.text,
            updated_at = excluded.updated_at
        """,
        (store.session_id, text, _utc_now()),
    )
    store._conn.commit()

def latest_session_id(
    store: MemoryStore, *, require_messages: bool = True, room_id: str | None = None
) -> str | None:
    """Most recent session, optionally skipping empty shells from short launches.

    rowid breaks the tie because started_at is only second-resolution, and
    without it two sessions opened in the same second come back in whatever
    order the query plan happens to produce.

    room_id=None searches every conversation; room_id="" searches only the
    general ones. The distinction matters to the glass-launch prune, which
    must not reach into a room's thread.
    """
    where = ["1=1"]
    params: list[Any] = []
    if require_messages:
        where.append("EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)")
    if room_id is not None:
        where.append("s.room_id = ?")
        params.append(room_id)
    row = store._conn.execute(
        f"""
        SELECT s.id
        FROM sessions s
        WHERE {" AND ".join(where)}
        ORDER BY s.started_at DESC, s.rowid DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return str(row["id"]) if row is not None else None

def list_sessions(
    store: MemoryStore, *, limit: int = 50, room_id: str | None = None
) -> list[dict[str, Any]]:
    where = "WHERE room_id = ?" if room_id is not None else ""
    params: list[Any] = [room_id] if room_id is not None else []
    params.append(limit)
    rows = store._conn.execute(
        f"""
        SELECT id, started_at, ended_at, title, room_id
        FROM sessions
        {where}
        ORDER BY started_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]

def delete_session(store: MemoryStore, session_id: str) -> bool:
    """Remove a conversation and cascaded messages/summaries. True if deleted."""
    sid = (session_id or "").strip()
    if not sid:
        return False
    cur = store._conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
    store._conn.commit()
    removed = cur.rowcount > 0
    if removed and store.session_id == sid:
        store.session_id = None
        store._ordinal = 0
        store._title_set = False
    return removed

def get_session(store: MemoryStore, session_id: str) -> dict[str, Any] | None:
    row = store._conn.execute(
        """
        SELECT id, started_at, ended_at, title, room_id
        FROM sessions
        WHERE id = ?
        """,
        (session_id,),
    ).fetchone()
    return dict(row) if row else None

def get_messages(store: MemoryStore, session_id: str) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        """
        SELECT id, role, content, note, created_at, ordinal
        FROM messages
        WHERE session_id = ?
        ORDER BY ordinal ASC
        """,
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]

def get_summary(store: MemoryStore, session_id: str) -> str:
    row = store._conn.execute(
        "SELECT text FROM summaries WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return str(row["text"]) if row else ""
