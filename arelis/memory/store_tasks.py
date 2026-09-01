"""Tasks and goals."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from arelis.memory.store import _utc_now

if TYPE_CHECKING:
    from arelis.memory.store import MemoryStore

def add_task(
    store: MemoryStore,
    title: str,
    *,
    due: str | None = None,
    goal_id: int | None = None,
    source: str = "explicit",
) -> int | None:
    """Insert an open task. Returns its id, or None if the title was empty."""
    cleaned = title.strip()
    if not cleaned:
        return None
    due_text = (due or "").strip() or None
    source_text = (source or "explicit").strip() or "explicit"
    gid: int | None = None
    if goal_id is not None:
        gid = int(goal_id)
        if store.get_goal(gid) is None:
            raise ValueError(f"no goal with id {gid}")
    now = _utc_now()
    cur = store._conn.execute(
        """
        INSERT INTO tasks
            (title, status, due, created_at, updated_at, source, goal_id)
        VALUES (?, 'open', ?, ?, ?, ?, ?)
        """,
        (cleaned, due_text, now, now, source_text, gid),
    )
    store._conn.commit()
    return int(cur.lastrowid)

def list_tasks(
    store: MemoryStore,
    *,
    status: str | None = "open",
    goal_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List tasks. Default status is open; pass status=None for all."""
    if status is not None and status not in {"open", "done"}:
        raise ValueError(f"unknown task status {status!r}")
    clauses: list[str] = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if goal_id is not None:
        clauses.append("goal_id = ?")
        params.append(int(goal_id))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = (
        """
        ORDER BY
            CASE status WHEN 'open' THEN 0 ELSE 1 END,
            COALESCE(due, '9999-99-99') ASC,
            created_at ASC
        """
        if status is None
        else "ORDER BY COALESCE(due, '9999-99-99') ASC, created_at ASC"
    )
    params.append(limit)
    rows = store._conn.execute(
        f"""
        SELECT id, title, status, due, created_at, updated_at, source, goal_id
        FROM tasks
        {where}
        {order}
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]

def get_task(store: MemoryStore, task_id: int) -> dict[str, Any] | None:
    row = store._conn.execute(
        """
        SELECT id, title, status, due, created_at, updated_at, source, goal_id
        FROM tasks
        WHERE id = ?
        """,
        (int(task_id),),
    ).fetchone()
    return dict(row) if row else None

def set_task_status(store: MemoryStore, task_id: int, status: str) -> bool:
    """Mark a task open or done. True when a row changed."""
    if status not in {"open", "done"}:
        raise ValueError(f"unknown task status {status!r}")
    cur = store._conn.execute(
        """
        UPDATE tasks
        SET status = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, _utc_now(), int(task_id)),
    )
    store._conn.commit()
    return cur.rowcount > 0

def set_task_goal(store: MemoryStore, task_id: int, goal_id: int | None) -> bool:
    """Attach or detach a task from a goal. True when a row changed."""
    tid = int(task_id)
    if store.get_task(tid) is None:
        return False
    gid: int | None = None
    if goal_id is not None:
        gid = int(goal_id)
        if store.get_goal(gid) is None:
            raise ValueError(f"no goal with id {gid}")
    cur = store._conn.execute(
        """
        UPDATE tasks
        SET goal_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (gid, _utc_now(), tid),
    )
    store._conn.commit()
    return cur.rowcount > 0

def remove_task(store: MemoryStore, task_id: int) -> bool:
    """Delete a task by id. True when a row was removed."""
    cur = store._conn.execute(
        "DELETE FROM tasks WHERE id = ?",
        (int(task_id),),
    )
    store._conn.commit()
    return cur.rowcount > 0

def add_goal(
    store: MemoryStore,
    title: str,
    *,
    kind: str = "goal",
    horizon: str | None = None,
    notes: str | None = None,
    source: str = "explicit",
) -> int | None:
    """Insert an active goal/commitment. Returns id, or None if empty."""
    cleaned = title.strip()
    if not cleaned:
        return None
    kind_text = (kind or "goal").strip().lower() or "goal"
    if kind_text not in {"goal", "commitment"}:
        raise ValueError(f"unknown goal kind {kind!r}")
    horizon_text = (horizon or "").strip() or None
    notes_text = (notes or "").strip() or None
    source_text = (source or "explicit").strip() or "explicit"
    now = _utc_now()
    cur = store._conn.execute(
        """
        INSERT INTO goals
            (title, kind, status, horizon, notes, created_at, updated_at, source)
        VALUES (?, ?, 'active', ?, ?, ?, ?, ?)
        """,
        (cleaned, kind_text, horizon_text, notes_text, now, now, source_text),
    )
    store._conn.commit()
    return int(cur.lastrowid)

def list_goals(
    store: MemoryStore,
    *,
    status: str | None = "active",
    kind: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List goals. Default status is active; pass status=None for all."""
    allowed_status = {"active", "paused", "done", "dropped"}
    if status is not None and status not in allowed_status:
        raise ValueError(f"unknown goal status {status!r}")
    if kind is not None and kind not in {"goal", "commitment"}:
        raise ValueError(f"unknown goal kind {kind!r}")
    clauses: list[str] = []
    params: list[Any] = []
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(int(limit))
    rows = store._conn.execute(
        f"""
        SELECT id, title, kind, status, horizon, notes,
               created_at, updated_at, source
        FROM goals
        {where}
        ORDER BY
            CASE status
                WHEN 'active' THEN 0
                WHEN 'paused' THEN 1
                WHEN 'done' THEN 2
                ELSE 3
            END,
            created_at ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]

def get_goal(store: MemoryStore, goal_id: int) -> dict[str, Any] | None:
    row = store._conn.execute(
        """
        SELECT id, title, kind, status, horizon, notes,
               created_at, updated_at, source
        FROM goals
        WHERE id = ?
        """,
        (int(goal_id),),
    ).fetchone()
    return dict(row) if row else None

def set_goal_status(store: MemoryStore, goal_id: int, status: str) -> bool:
    """Set goal status. True when a row changed."""
    if status not in {"active", "paused", "done", "dropped"}:
        raise ValueError(f"unknown goal status {status!r}")
    cur = store._conn.execute(
        """
        UPDATE goals
        SET status = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, _utc_now(), int(goal_id)),
    )
    store._conn.commit()
    return cur.rowcount > 0

def update_goal(
    store: MemoryStore,
    goal_id: int,
    *,
    title: str | None = None,
    kind: str | None = None,
    horizon: str | None = None,
    notes: str | None = None,
    clear_horizon: bool = False,
    clear_notes: bool = False,
) -> bool:
    """Patch goal fields. True when a row changed."""
    existing = store.get_goal(goal_id)
    if existing is None:
        return False
    new_title = existing["title"]
    if title is not None:
        cleaned = title.strip()
        if not cleaned:
            raise ValueError("goal title cannot be empty")
        new_title = cleaned
    new_kind = existing["kind"]
    if kind is not None:
        kind_text = kind.strip().lower()
        if kind_text not in {"goal", "commitment"}:
            raise ValueError(f"unknown goal kind {kind!r}")
        new_kind = kind_text
    new_horizon = existing.get("horizon")
    if clear_horizon:
        new_horizon = None
    elif horizon is not None:
        new_horizon = horizon.strip() or None
    new_notes = existing.get("notes")
    if clear_notes:
        new_notes = None
    elif notes is not None:
        new_notes = notes.strip() or None
    cur = store._conn.execute(
        """
        UPDATE goals
        SET title = ?, kind = ?, horizon = ?, notes = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            new_title,
            new_kind,
            new_horizon,
            new_notes,
            _utc_now(),
            int(goal_id),
        ),
    )
    store._conn.commit()
    return cur.rowcount > 0

def remove_goal(store: MemoryStore, goal_id: int) -> bool:
    """Hard-delete a goal by id. True when a row was removed."""
    cur = store._conn.execute(
        "DELETE FROM goals WHERE id = ?",
        (int(goal_id),),
    )
    store._conn.commit()
    return cur.rowcount > 0
