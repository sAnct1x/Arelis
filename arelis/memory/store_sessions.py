"""Session archive: conversations, messages, and summaries."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from arelis.memory.store import _fts_match, _inserted_id, _utc_now

if TYPE_CHECKING:
    from arelis.memory.store import MemoryStore


_OPEN_ASSISTANT_FLUSH_S = 0.4


def _like_contains(needle: str) -> str:
    """Substring LIKE pattern that treats backslash, %, and _ as literals."""
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _reset_open_assistant_state(store: MemoryStore, *, forget_row: bool = True) -> None:
    """Stop tracking an in-progress assistant row. The row itself stays unless deleted."""
    if forget_row:
        store._open_assistant_id = None
    store._open_assistant_text = None
    store._open_assistant_written_at = 0.0


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
    _reset_open_assistant_state(store)
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
    """Cold glass launch: sit on the unused general shell, or mint one.

    Last night's real thread stays in History. An unused 'new chat' from
    a short launch is reused, minting another is how three blank rows
    stacked up. Extra unused general shells are pruned. Tray / un-minimize
    never call this.

    Unused means no user turn yet. Assistant-only setup lines still read
    as 'new chat' in History, so they must not count as a filled thread.

    The prune is scoped to general conversations. A room's thread is
    durable by design and is never the leftover shell of a short launch,
    so it must not be reachable by this prune even when it happens to be
    the newest row in the table.
    """
    return start_or_reuse_empty_session(store, room_id="")


def start_or_reuse_empty_session(store: MemoryStore, *, room_id: str) -> str:
    """Open the unused empty shell in this room, or mint one.

    Cold launch used to start a general 'new chat' and then swap to the
    room's last filled thread, History showed both, and the old lecture
    was the one you landed in. Reuse the empty row so two 'new chat'
    titles do not fight. Extra unused shells in this room are deleted.
    """
    unused = _unused_session_ids(store, room_id=room_id)
    if unused:
        keep = unused[0]
        for sid in unused[1:]:
            store.delete_session(sid)
        store.open_session(keep)
        return keep
    return store.start_session(room_id=room_id)

def _session_has_messages(store: MemoryStore, session_id: str) -> bool:
    row = store._conn.execute(
        "SELECT 1 FROM messages WHERE session_id = ? LIMIT 1",
        (session_id,),
    ).fetchone()
    return row is not None


def _session_has_user_messages(store: MemoryStore, session_id: str) -> bool:
    row = store._conn.execute(
        "SELECT 1 FROM messages WHERE session_id = ? AND role = 'user' LIMIT 1",
        (session_id,),
    ).fetchone()
    return row is not None


def _unused_session_ids(store: MemoryStore, *, room_id: str) -> list[str]:
    """Blank shells in this room, newest first. Unused = no user turn yet."""
    rows = store._conn.execute(
        """
        SELECT s.id
        FROM sessions s
        WHERE s.room_id = ?
          AND COALESCE(s.pinned, 0) = 0
          AND NOT EXISTS (
              SELECT 1 FROM messages m
              WHERE m.session_id = s.id AND m.role = 'user'
          )
        ORDER BY s.started_at DESC, s.rowid DESC
        """,
        (room_id,),
    ).fetchall()
    return [str(row["id"]) for row in rows]


def keep_history_row(row: dict[str, Any], *, current_id: str = "") -> bool:
    """Blank unused shells stay out of History except the one you are on.

    A pinned conversation stays even when it has no messages yet. Otherwise
    the next refresh would drop the chat you just asked to keep.
    """
    sid = str(row.get("id") or "")
    if current_id and sid == current_id:
        return True
    if row.get("pinned"):
        return True
    return bool(row.get("has_user"))

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
    _reset_open_assistant_state(store)
    return True

def on_message(store: MemoryStore, role: str, content: str, note: str = "") -> None:
    """Persist one message. Called from SessionMemory.add when a sink is set."""
    if store.session_id is None:
        store.start_session()
    open_id = getattr(store, "_open_assistant_id", None)
    if role == "assistant" and open_id is not None:
        store._conn.execute(
            "UPDATE messages SET content = ?, note = ? WHERE id = ?",
            (content, note, open_id),
        )
        _reset_open_assistant_state(store)
        store._conn.commit()
        return
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
    where = "WHERE s.room_id = ?" if room_id is not None else ""
    params: list[Any] = [room_id] if room_id is not None else []
    params.append(limit)
    rows = store._conn.execute(
        f"""
        SELECT s.id, s.started_at, s.ended_at, s.title, s.room_id, s.pinned,
               EXISTS (
                   SELECT 1 FROM messages m
                   WHERE m.session_id = s.id AND m.role = 'user'
               ) AS has_user
        FROM sessions s
        {where}
        ORDER BY s.pinned DESC, s.started_at DESC, s.rowid DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["has_user"] = bool(item.get("has_user"))
        item["pinned"] = bool(item.get("pinned"))
        out.append(item)
    return out


def set_session_pinned(store: MemoryStore, session_id: str, on: bool) -> bool:
    """Pin or unpin one conversation. False if that chat is not stored."""
    sid = (session_id or "").strip()
    if not sid or get_session(store, sid) is None:
        return False
    store._conn.execute(
        "UPDATE sessions SET pinned = ? WHERE id = ?",
        (1 if on else 0, sid),
    )
    store._conn.commit()
    return True

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
        _reset_open_assistant_state(store)
    return removed

def get_session(store: MemoryStore, session_id: str) -> dict[str, Any] | None:
    row = store._conn.execute(
        """
        SELECT id, started_at, ended_at, title, room_id, pinned
        FROM sessions
        WHERE id = ?
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["pinned"] = bool(item.get("pinned"))
    return item

def get_messages(store: MemoryStore, session_id: str) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        """
        SELECT id, role, content, note, created_at, ordinal
        FROM messages
        WHERE session_id = ?
        ORDER BY ordinal ASC, id ASC
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


def insert_compaction_marker(store: MemoryStore, kept: list[Any]) -> bool:
    """Record a transcript marker just before the kept working-set rows.

    Uses the same ordinal as the last dropped message so the row sorts after
    it and before the first kept message (ORDER BY ordinal, id). Original
    messages are not rewritten. Returns True when a new marker was written.
    """
    from arelis.core.compaction import (
        COMPACTION_MARKER,
        COMPACTION_MARKER_NOTE,
        is_compaction_marker,
    )

    session_id = str(getattr(store, "session_id", "") or "")
    if not session_id:
        return False
    rows = get_messages(store, session_id)
    if not rows:
        return False

    def _pair(item: Any) -> tuple[str, str, str]:
        if isinstance(item, dict):
            return (
                str(item.get("role") or ""),
                str(item.get("content") or ""),
                str(item.get("note") or ""),
            )
        return (
            str(getattr(item, "role", "") or ""),
            str(getattr(item, "content", "") or ""),
            str(getattr(item, "note", "") or ""),
        )

    def _visible_pair(role: str, content: str, note: str) -> tuple[str, str] | None:
        if is_compaction_marker(role, content, note) or role == "notice":
            return None
        return (role, content)

    normalized: list[tuple[str, str]] = []
    for item in kept:
        pair = _visible_pair(*_pair(item))
        if pair is not None:
            normalized.append(pair)
    if not normalized:
        return False

    visible_rows: list[dict[str, Any]] = []
    for row in rows:
        pair = _visible_pair(
            str(row.get("role") or ""),
            str(row.get("content") or ""),
            str(row.get("note") or ""),
        )
        if pair is not None:
            visible_rows.append(row)
    if len(visible_rows) < len(normalized):
        return False

    def _row_pair(row: dict[str, Any]) -> tuple[str, str]:
        return (str(row.get("role") or ""), str(row.get("content") or ""))

    offset = len(visible_rows) - len(normalized)
    if [_row_pair(row) for row in visible_rows[offset:]] != normalized:
        offset = -1
        first = normalized[0]
        for index, row in enumerate(visible_rows):
            if _row_pair(row) != first:
                continue
            tail = [_row_pair(item) for item in visible_rows[index : index + len(normalized)]]
            if tail == normalized:
                offset = index
                break
        if offset < 0:
            return False
    if offset <= 0:
        return False

    last_dropped = visible_rows[offset - 1]
    first_kept = visible_rows[offset]

    def _sort_key(row: dict[str, Any]) -> tuple[int, int]:
        return (int(row["ordinal"]), int(row["id"]))

    last_key = _sort_key(last_dropped)
    first_key = _sort_key(first_kept)
    for row in rows:
        if last_key < _sort_key(row) < first_key and is_compaction_marker(
            str(row.get("role") or ""),
            str(row.get("content") or ""),
            str(row.get("note") or ""),
        ):
            return False

    store._conn.execute(
        """
        INSERT INTO messages (session_id, role, content, note, created_at, ordinal)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            "notice",
            COMPACTION_MARKER,
            COMPACTION_MARKER_NOTE,
            _utc_now(),
            int(last_dropped["ordinal"]),
        ),
    )
    store._conn.commit()
    return True


def on_open_assistant(store: MemoryStore, content: str, *, flush_now: bool = False) -> None:
    """Write the in-progress assistant reply so a crash keeps the text so far.

    The first chunk is committed at once. Later chunks are stashed and flushed
    on a short interval, on demand, or when ``store.flush`` runs at quit.
    """
    text = content or ""
    if not text:
        return
    if store.session_id is None:
        store.start_session()
    store._open_assistant_text = text
    last = float(getattr(store, "_open_assistant_written_at", 0.0) or 0.0)
    due = flush_now or getattr(store, "_open_assistant_id", None) is None
    due = due or (time.monotonic() - last) >= _OPEN_ASSISTANT_FLUSH_S
    if due:
        write_open_assistant(store)


def write_open_assistant(store: MemoryStore) -> None:
    """Commit the stashed in-progress assistant text, if any."""
    text = getattr(store, "_open_assistant_text", None)
    if not text or store.session_id is None:
        return
    open_id = getattr(store, "_open_assistant_id", None)
    if open_id is None:
        store._ordinal += 1
        cur = store._conn.execute(
            """
            INSERT INTO messages (session_id, role, content, note, created_at, ordinal)
            VALUES (?, 'assistant', ?, '', ?, ?)
            """,
            (store.session_id, text, _utc_now(), store._ordinal),
        )
        store._open_assistant_id = _inserted_id(cur)
    else:
        store._conn.execute(
            "UPDATE messages SET content = ? WHERE id = ?",
            (text, open_id),
        )
    store._open_assistant_written_at = time.monotonic()
    store._conn.commit()


def clear_open_assistant(store: MemoryStore) -> None:
    """Drop a retracted in-progress assistant row so it does not linger."""
    open_id = getattr(store, "_open_assistant_id", None)
    if open_id is not None:
        store._conn.execute("DELETE FROM messages WHERE id = ?", (open_id,))
        store._conn.commit()
    _reset_open_assistant_state(store)


def seal_open_assistant(store: MemoryStore, content: str) -> None:
    """Commit the in-progress reply as a finished row (cancel / stop)."""
    text = (content or "").strip()
    if not text:
        clear_open_assistant(store)
        return
    store._open_assistant_text = text
    write_open_assistant(store)
    _reset_open_assistant_state(store)


def flush_open_assistant(store: MemoryStore) -> None:
    """Write any stashed in-progress text. Called from MemoryStore.flush."""
    if getattr(store, "_open_assistant_text", None):
        write_open_assistant(store)


def search_sessions(
    store: MemoryStore, query: str, *, limit: int = 200
) -> list[dict[str, Any]]:
    """Sessions whose title or message body matches ``query``.

    Uses FTS5 when it is available so a History search stays fast across
    thousands of chats. Falls back to LIKE otherwise. Unlike
    ``filter``ing a pre-loaded list, this looks at the whole archive.
    """
    needle = (query or "").strip()
    if not needle or limit <= 0:
        return []
    pattern = _like_contains(needle)
    params: list[Any]
    if store.fts_available:
        match = _fts_match(needle)
        if not match:
            return []
        where = """
            s.title LIKE ? ESCAPE '\\'
            OR s.id IN (
                SELECT m.session_id
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                WHERE messages_fts MATCH ?
                  AND m.role != 'notice'
            )
        """
        params = [pattern, match, limit]
    else:
        where = """
            s.title LIKE ? ESCAPE '\\'
            OR EXISTS (
                SELECT 1 FROM messages m
                WHERE m.session_id = s.id
                  AND m.role != 'notice'
                  AND (m.content LIKE ? ESCAPE '\\' OR m.note LIKE ? ESCAPE '\\')
            )
        """
        params = [pattern, pattern, pattern, limit]
    rows = store._conn.execute(
        f"""
        SELECT s.id, s.started_at, s.ended_at, s.title, s.room_id, s.pinned,
               EXISTS (
                   SELECT 1 FROM messages m
                   WHERE m.session_id = s.id AND m.role = 'user'
               ) AS has_user
        FROM sessions s
        WHERE {where}
        ORDER BY s.pinned DESC, s.started_at DESC, s.rowid DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["has_user"] = bool(item.get("has_user"))
        item["pinned"] = bool(item.get("pinned"))
        out.append(item)
    return out

