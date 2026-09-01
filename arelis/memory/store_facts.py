"""Facts, preferences, decisions, and episodes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from arelis.memory.store import _facts_loosely_match, _normalize_fact_key, _utc_now

if TYPE_CHECKING:
    from arelis.memory.store import MemoryStore

def on_pending_fact(store: MemoryStore, text: str) -> None:
    """Record a proposed fact. Nothing becomes active without a later click."""
    store.add_fact(
        text,
        source="proposed",
        status="pending",
        session_id=store.session_id,
    )

def add_fact(
    store: MemoryStore,
    text: str,
    *,
    source: str,
    status: str,
    session_id: str | None = None,
    key: str | None = None,
) -> int | None:
    """Insert a fact. Returns its id, or None if it was empty or a duplicate."""
    cleaned = text.strip()
    if not cleaned:
        return None
    if source not in {"explicit", "proposed"}:
        raise ValueError(f"unknown fact source {source!r}")
    if status not in {"active", "pending", "rejected"}:
        raise ValueError(f"unknown fact status {status!r}")
    fact_key = _normalize_fact_key(key)
    # Same wording already live or waiting would only confuse the review queue.
    existing = store._conn.execute(
        """
        SELECT id FROM facts
        WHERE text = ? AND status IN ('active', 'pending')
        LIMIT 1
        """,
        (cleaned,),
    ).fetchone()
    if existing is not None:
        return int(existing["id"])
    now = _utc_now()
    if status == "active" and fact_key is not None:
        store._supersede_active_by_key(fact_key)
    cur = store._conn.execute(
        """
        INSERT INTO facts
            (text, source, status, created_at, updated_at, session_id, key)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (cleaned, source, status, now, now, session_id, fact_key),
    )
    store._conn.commit()
    return int(cur.lastrowid)

def list_facts(
    store: MemoryStore, *, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    if status is None:
        rows = store._conn.execute(
            """
            SELECT id, text, source, status, created_at, updated_at, session_id, key
            FROM facts
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    else:
        rows = store._conn.execute(
            """
            SELECT id, text, source, status, created_at, updated_at, session_id, key
            FROM facts
            WHERE status = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (status, limit),
        ).fetchall()
    return [dict(row) for row in rows]

def set_fact_status(store: MemoryStore, fact_id: int, status: str) -> bool:
    """Approve or reject a pending fact. True when a row changed."""
    if status not in {"active", "pending", "rejected"}:
        raise ValueError(f"unknown fact status {status!r}")
    fid = int(fact_id)
    if status == "active":
        row = store._conn.execute(
            "SELECT key FROM facts WHERE id = ?",
            (fid,),
        ).fetchone()
        fact_key = str(row["key"]).strip() if row is not None and row["key"] else ""
        if fact_key:
            store._supersede_active_by_key(fact_key, except_id=fid)
    cur = store._conn.execute(
        """
        UPDATE facts
        SET status = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, _utc_now(), fid),
    )
    store._conn.commit()
    return cur.rowcount > 0

def archive_stale_pending_facts(store: MemoryStore, *, older_than_days: int = 30) -> int:
    """Reject pending facts older than the cutoff. Returns how many rows changed."""
    days = max(0, int(older_than_days))
    cutoff = (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0)
    cutoff_iso = cutoff.isoformat()
    cur = store._conn.execute(
        """
        UPDATE facts
        SET status = 'rejected', updated_at = ?
        WHERE status = 'pending' AND created_at < ?
        """,
        (_utc_now(), cutoff_iso),
    )
    store._conn.commit()
    return int(cur.rowcount)

def _supersede_active_by_key(
    store: MemoryStore, key: str, *, except_id: int | None = None
) -> None:
    """Reject other active facts that share this key."""
    now = _utc_now()
    if except_id is None:
        store._conn.execute(
            """
            UPDATE facts
            SET status = 'rejected', updated_at = ?
            WHERE status = 'active' AND key = ?
            """,
            (now, key),
        )
    else:
        store._conn.execute(
            """
            UPDATE facts
            SET status = 'rejected', updated_at = ?
            WHERE status = 'active' AND key = ? AND id != ?
            """,
            (now, key, int(except_id)),
        )

def active_fact_texts(store: MemoryStore, *, limit: int = 24) -> list[str]:
    rows = store._conn.execute(
        """
        SELECT text FROM facts
        WHERE status = 'active'
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [str(row["text"]) for row in rows]

def forget_fact(store: MemoryStore, text: str) -> int:
    """Deactivate active facts matching text. Returns how many rows changed."""
    cleaned = text.strip()
    if not cleaned:
        return 0
    cur = store._conn.execute(
        """
        UPDATE facts
        SET status = 'rejected', updated_at = ?
        WHERE status = 'active' AND lower(text) = lower(?)
        """,
        (_utc_now(), cleaned),
    )
    if cur.rowcount:
        store._conn.commit()
        return int(cur.rowcount)
    # "my favorite test fruit is durian" must match
    # "the user's favorite test fruit is durian".
    for stored in store.active_fact_texts(limit=40):
        if _facts_loosely_match(cleaned, stored):
            cur = store._conn.execute(
                """
                UPDATE facts
                SET status = 'rejected', updated_at = ?
                WHERE status = 'active' AND text = ?
                """,
                (_utc_now(), stored),
            )
            store._conn.commit()
            return int(cur.rowcount)
    store._conn.commit()
    return 0

def set_preference(store: MemoryStore, key: str, value: str) -> int | None:
    """Upsert a preference by key. Returns its id, or None if empty."""
    cleaned_key = key.strip()
    cleaned_value = value.strip()
    if not cleaned_key or not cleaned_value:
        return None
    now = _utc_now()
    existing = store._conn.execute(
        "SELECT id FROM preferences WHERE key = ?",
        (cleaned_key,),
    ).fetchone()
    if existing is not None:
        pref_id = int(existing["id"])
        store._conn.execute(
            """
            UPDATE preferences
            SET value = ?, updated_at = ?
            WHERE id = ?
            """,
            (cleaned_value, now, pref_id),
        )
        store._conn.commit()
        return pref_id
    cur = store._conn.execute(
        """
        INSERT INTO preferences (key, value, updated_at)
        VALUES (?, ?, ?)
        """,
        (cleaned_key, cleaned_value, now),
    )
    store._conn.commit()
    return int(cur.lastrowid)

def get_preference(store: MemoryStore, key: str) -> str | None:
    cleaned_key = key.strip()
    if not cleaned_key:
        return None
    row = store._conn.execute(
        "SELECT value FROM preferences WHERE key = ?",
        (cleaned_key,),
    ).fetchone()
    return str(row["value"]) if row is not None else None

def list_preferences(store: MemoryStore, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = store._conn.execute(
        """
        SELECT id, key, value, updated_at
        FROM preferences
        ORDER BY key ASC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]

def add_decision(store: MemoryStore, project: str, text: str) -> int | None:
    """Record a project-scoped decision. Returns its id, or None if empty."""
    cleaned_project = project.strip()
    cleaned_text = text.strip()
    if not cleaned_project or not cleaned_text:
        return None
    now = _utc_now()
    cur = store._conn.execute(
        """
        INSERT INTO decisions (project, text, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        """,
        (cleaned_project, cleaned_text, now, now),
    )
    store._conn.commit()
    return int(cur.lastrowid)

def list_decisions(
    store: MemoryStore, project: str, limit: int = 50
) -> list[dict[str, Any]]:
    cleaned_project = project.strip()
    if not cleaned_project:
        return []
    rows = store._conn.execute(
        """
        SELECT id, project, text, created_at, updated_at
        FROM decisions
        WHERE project = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (cleaned_project, limit),
    ).fetchall()
    return [dict(row) for row in rows]

def add_episode(
    store: MemoryStore,
    summary: str,
    *,
    source: str = "manual",
    session_id: str | None = None,
    project: str | None = None,
) -> int | None:
    """Store a typed episode summary. Returns id, or None if empty/invalid.

    source must be ``manual`` (explicit memory tool) or ``confirm`` (user
    confirmed a proposed episode). Never call this from every turn.
    """
    cleaned = " ".join(str(summary or "").split())
    if not cleaned:
        return None
    src = str(source or "manual").strip().lower()
    if src not in {"manual", "confirm"}:
        return None
    sid = session_id if session_id is not None else store.session_id
    if sid is not None:
        sid = str(sid).strip() or None
    proj = None if project is None else str(project).strip() or None
    cur = store._conn.execute(
        """
        INSERT INTO episodes (summary, created_at, session_id, source, project)
        VALUES (?, ?, ?, ?, ?)
        """,
        (cleaned, _utc_now(), sid, src, proj),
    )
    store._conn.commit()
    return int(cur.lastrowid)

def list_episodes(
    store: MemoryStore, *, limit: int = 20, project: str | None = None
) -> list[dict[str, Any]]:
    """Recent episodes, newest first. Optional project filter."""
    cap = max(1, min(int(limit), 200))
    if project is not None and str(project).strip():
        rows = store._conn.execute(
            """
            SELECT id, summary, created_at, session_id, source, project
            FROM episodes
            WHERE project = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (str(project).strip(), cap),
        ).fetchall()
    else:
        rows = store._conn.execute(
            """
            SELECT id, summary, created_at, session_id, source, project
            FROM episodes
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (cap,),
        ).fetchall()
    return [dict(row) for row in rows]
