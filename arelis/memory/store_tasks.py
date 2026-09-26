"""Tasks and goals."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from arelis.memory.store import _inserted_id, _utc_now

if TYPE_CHECKING:
    from arelis.memory.store import MemoryStore

PRIORITIES = frozenset({"high", "normal", "low"})
CADENCES = frozenset({"daily", "weekly", "weekdays", "monthly"})

# List/get must keep these in lockstep — dropping priority here is the
# "column exists but list never shows it" mutant.
_TASK_COLUMNS = (
    "id, title, status, due, created_at, updated_at, source, goal_id, "
    "priority, recurrence, parent_id"
)
_GOAL_COLUMNS = "id, title, kind, status, horizon, notes, created_at, updated_at, source, priority"

_PRIORITY_ORDER = "CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END"


def resolve_priority(raw: Any) -> str:
    """Closed set. None → normal. Anything else unknown, including '', fails."""
    if raw is None:
        return "normal"
    text = str(raw).strip().lower()
    if text not in PRIORITIES:
        raise ValueError(f"priority must be high, normal, or low, not {raw!r}")
    return text


def resolve_recurrence(raw: Any) -> str | None:
    """Named cadences only. None or blank clears. Unknown fails — no RRULE."""
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None
    if text not in CADENCES:
        raise ValueError(f"recurrence must be daily, weekly, weekdays, or monthly, not {raw!r}")
    return text


def parse_iso_due(due: str | None) -> str:
    """Recurrence advances YYYY-MM-DD only. Free-text dues stay non-recurring."""
    text = (due or "").strip()
    if len(text) != 10:
        raise ValueError(f"recurring tasks need a due date (YYYY-MM-DD), not {due!r}")
    try:
        date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"recurring tasks need a due date (YYYY-MM-DD), not {due!r}") from None
    return text


def next_due_date(due: str | None, recurrence: str) -> str:
    """Exactly one step. No catch-up loop — those hang on a bad clock."""
    cadence = resolve_recurrence(recurrence)
    if cadence is None:
        raise ValueError(f"unknown recurrence {recurrence!r}")
    base = date.fromisoformat(parse_iso_due(due))
    if cadence == "daily":
        nxt = base + timedelta(days=1)
    elif cadence == "weekly":
        nxt = base + timedelta(days=7)
    elif cadence == "weekdays":
        nxt = base + timedelta(days=1)
        # Sat=5, Sun=6. At most two hops; no while.
        if nxt.weekday() == 5:
            nxt += timedelta(days=2)
        elif nxt.weekday() == 6:
            nxt += timedelta(days=1)
    elif cadence == "monthly":
        year = base.year + (1 if base.month == 12 else 0)
        month = 1 if base.month == 12 else base.month + 1
        last = monthrange(year, month)[1]
        nxt = date(year, month, min(base.day, last))
    else:
        raise ValueError(f"unknown recurrence {recurrence!r}")
    return nxt.isoformat()


def resolve_parent_id(
    store: MemoryStore,
    parent_id: Any,
    *,
    child_id: int | None = None,
) -> int:
    """parent_id is another task. Cycles and a missing parent fail."""
    try:
        pid = int(parent_id)
    except (TypeError, ValueError):
        raise ValueError("parent_id must be an integer") from None
    if child_id is not None and pid == int(child_id):
        raise ValueError("a task cannot be its own parent")
    parent = get_task(store, pid)
    if parent is None:
        raise ValueError(f"no task with id {pid}")
    cursor = parent.get("parent_id")
    hops = 0
    seen = {pid}
    while cursor is not None and hops < 8:
        cid = int(cursor)
        if child_id is not None and cid == int(child_id):
            raise ValueError("that parent_id would create a cycle")
        if cid in seen:
            raise ValueError("that parent_id would create a cycle")
        seen.add(cid)
        ancestor = get_task(store, cid)
        if ancestor is None:
            break
        cursor = ancestor.get("parent_id")
        hops += 1
    if hops >= 8:
        raise ValueError("parent chain is too deep")
    return pid


def add_task(
    store: MemoryStore,
    title: str,
    *,
    due: str | None = None,
    goal_id: int | None = None,
    source: str = "explicit",
    priority: str | None = None,
    recurrence: str | None = None,
    parent_id: int | None = None,
) -> int | None:
    """Insert an open task. Returns its id, or None if the title was empty."""
    cleaned = title.strip()
    if not cleaned:
        return None
    due_text = (due or "").strip() or None
    source_text = (source or "explicit").strip() or "explicit"
    priority_text = resolve_priority(priority)
    recurrence_text = resolve_recurrence(recurrence)
    if recurrence_text is not None:
        due_text = parse_iso_due(due_text)
    gid: int | None = None
    if goal_id is not None:
        gid = int(goal_id)
        if store.get_goal(gid) is None:
            raise ValueError(f"no goal with id {gid}")
    pid: int | None = None
    if parent_id is not None:
        pid = resolve_parent_id(store, parent_id)
    now = _utc_now()
    cur = store._conn.execute(
        """
        INSERT INTO tasks
            (title, status, due, created_at, updated_at, source, goal_id,
             priority, recurrence, parent_id)
        VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cleaned,
            due_text,
            now,
            now,
            source_text,
            gid,
            priority_text,
            recurrence_text,
            pid,
        ),
    )
    store._conn.commit()
    return _inserted_id(cur)


def list_tasks(
    store: MemoryStore,
    *,
    status: str | None = "open",
    goal_id: int | None = None,
    parent_id: int | None = None,
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
    if parent_id is not None:
        clauses.append("parent_id = ?")
        params.append(int(parent_id))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = (
        f"""
        ORDER BY
            CASE status WHEN 'open' THEN 0 ELSE 1 END,
            {_PRIORITY_ORDER},
            COALESCE(due, '9999-99-99') ASC,
            created_at ASC
        """
        if status is None
        else (f"ORDER BY {_PRIORITY_ORDER}, COALESCE(due, '9999-99-99') ASC, created_at ASC")
    )
    params.append(limit)
    rows = store._conn.execute(
        f"""
        SELECT {_TASK_COLUMNS}
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
        f"""
        SELECT {_TASK_COLUMNS}
        FROM tasks
        WHERE id = ?
        """,
        (int(task_id),),
    ).fetchone()
    return dict(row) if row else None


def set_task_status(store: MemoryStore, task_id: int, status: str) -> bool:
    """Mark a task open or done. True when a row changed.

    ``done`` on a parent with open children fails. ``done`` on a recurring
    task keeps the same row, advances due one step, and leaves it open —
    remove+add would mint a new id and drop the goal link.
    """
    if status not in {"open", "done"}:
        raise ValueError(f"unknown task status {status!r}")
    tid = int(task_id)
    existing = get_task(store, tid)
    if existing is None:
        return False
    if status == "done":
        open_kids = list_tasks(store, status="open", parent_id=tid, limit=200)
        if open_kids:
            n = len(open_kids)
            noun = "subtask" if n == 1 else "subtasks"
            raise ValueError(f"task #{tid} still has {n} open {noun}; finish those first")
        rec = existing.get("recurrence")
        if rec:
            nxt = next_due_date(existing.get("due"), str(rec))
            cur = store._conn.execute(
                """
                UPDATE tasks
                SET due = ?, status = 'open', updated_at = ?
                WHERE id = ?
                """,
                (nxt, _utc_now(), tid),
            )
            store._conn.commit()
            return cur.rowcount > 0
    cur = store._conn.execute(
        """
        UPDATE tasks
        SET status = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, _utc_now(), tid),
    )
    store._conn.commit()
    return cur.rowcount > 0


def update_task(
    store: MemoryStore,
    task_id: int,
    *,
    title: str | None = None,
    due: str | None = None,
    priority: str | None = None,
    recurrence: str | None = None,
    parent_id: int | None = None,
    clear_parent: bool = False,
) -> bool:
    """Edit a task in place. True when a row changed.

    None means leave the column alone; an empty ``due`` or ``recurrence``
    clears it. Keeping the row is the point — remove + add would issue a
    new id and drop the goal link, which is what callers were doing before
    this existed.
    """
    tid = int(task_id)
    existing = store.get_task(tid)
    if existing is None:
        return False
    sets: list[str] = []
    values: list[Any] = []
    if title is not None:
        cleaned = title.strip()
        if not cleaned:
            raise ValueError("task title cannot be blank")
        sets.append("title = ?")
        values.append(cleaned)
    new_due = existing.get("due")
    if due is not None:
        new_due = due.strip() or None
        sets.append("due = ?")
        values.append(new_due)
    if priority is not None:
        sets.append("priority = ?")
        values.append(resolve_priority(priority))
    new_recurrence = existing.get("recurrence")
    if recurrence is not None:
        new_recurrence = resolve_recurrence(recurrence)
        sets.append("recurrence = ?")
        values.append(new_recurrence)
    if new_recurrence:
        parse_iso_due(None if new_due is None else str(new_due))
    if clear_parent:
        sets.append("parent_id = ?")
        values.append(None)
    elif parent_id is not None:
        sets.append("parent_id = ?")
        values.append(resolve_parent_id(store, parent_id, child_id=tid))
    if not sets:
        return False
    sets.append("updated_at = ?")
    values.append(_utc_now())
    values.append(tid)
    cur = store._conn.execute(
        # Column names are built here, never from caller input; values bind.
        f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?",
        tuple(values),
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
    priority: str | None = None,
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
    priority_text = resolve_priority(priority)
    now = _utc_now()
    cur = store._conn.execute(
        """
        INSERT INTO goals
            (title, kind, status, horizon, notes, created_at, updated_at,
             source, priority)
        VALUES (?, ?, 'active', ?, ?, ?, ?, ?, ?)
        """,
        (
            cleaned,
            kind_text,
            horizon_text,
            notes_text,
            now,
            now,
            source_text,
            priority_text,
        ),
    )
    store._conn.commit()
    return _inserted_id(cur)


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
        SELECT {_GOAL_COLUMNS}
        FROM goals
        {where}
        ORDER BY
            CASE status
                WHEN 'active' THEN 0
                WHEN 'paused' THEN 1
                WHEN 'done' THEN 2
                ELSE 3
            END,
            {_PRIORITY_ORDER},
            created_at ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def get_goal(store: MemoryStore, goal_id: int) -> dict[str, Any] | None:
    row = store._conn.execute(
        f"""
        SELECT {_GOAL_COLUMNS}
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
    priority: str | None = None,
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
    new_priority = existing.get("priority") or "normal"
    if priority is not None:
        new_priority = resolve_priority(priority)
    cur = store._conn.execute(
        """
        UPDATE goals
        SET title = ?, kind = ?, horizon = ?, notes = ?, priority = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            new_title,
            new_kind,
            new_horizon,
            new_notes,
            new_priority,
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
