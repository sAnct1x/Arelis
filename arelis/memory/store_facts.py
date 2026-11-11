"""Facts, preferences, decisions, and episodes."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from arelis.memory.store import (
    _FACT_OWNER,
    _facts_loosely_match,
    _inserted_id,
    _normalize_fact_key,
    _utc_now,
)

if TYPE_CHECKING:
    from arelis.memory.store import MemoryStore

def normalize_fact_text(text: str) -> str:
    """Canonical form for matching two wordings of the same fact."""
    raw = (text or "").strip().lower()
    raw = raw.replace("\u2019", "'").replace("\u2018", "'")
    raw = _FACT_OWNER.sub("", raw)
    raw = re.sub(r"[^a-z0-9]+", " ", raw)
    return " ".join(raw.split())


def _facts_are_near_duplicates(left: str, right: str) -> bool:
    """True when two facts should share one row.

    Merge only on normalized equality (owner prefixes already stripped).
    Forget still uses the looser matcher; this one must not, or claims
    that differ in a number, a date, or a negation collapse into one row.
    """
    norm_left = normalize_fact_text(left)
    norm_right = normalize_fact_text(right)
    return bool(norm_left) and norm_left == norm_right


def _fact_rows(
    store: MemoryStore,
    *,
    statuses: tuple[str, ...],
    except_id: int | None = None,
) -> list[Any]:
    placeholders = ", ".join("?" for _ in statuses)
    rows = store._conn.execute(
        f"""
        SELECT id, text, source, status, created_at, updated_at, session_id, key
        FROM facts
        WHERE status IN ({placeholders})
        ORDER BY id ASC
        """,
        statuses,
    ).fetchall()
    if except_id is None:
        return list(rows)
    skip = int(except_id)
    return [row for row in rows if int(row["id"]) != skip]


def _live_fact_rows(store: MemoryStore, *, except_id: int | None = None) -> list[Any]:
    return _fact_rows(store, statuses=("active", "pending"), except_id=except_id)


def _row_key(row: Any) -> str | None:
    if row is None or row["key"] is None:
        return None
    return _normalize_fact_key(str(row["key"]))


def _find_matching_fact(
    store: MemoryStore,
    text: str,
    *,
    statuses: tuple[str, ...],
    key: str | None = None,
    except_id: int | None = None,
) -> Any | None:
    rows = _fact_rows(store, statuses=statuses, except_id=except_id)
    fact_key = _normalize_fact_key(key)
    if fact_key is not None:
        for row in rows:
            if _row_key(row) == fact_key:
                return row
    norm = normalize_fact_text(text)
    if not norm:
        return None
    for row in rows:
        if normalize_fact_text(str(row["text"] or "")) == norm:
            return row
    return None


def _find_matching_live_fact(
    store: MemoryStore,
    text: str,
    *,
    key: str | None = None,
    except_id: int | None = None,
) -> Any | None:
    return _find_matching_fact(
        store, text, statuses=("active", "pending"), key=key, except_id=except_id
    )


def _find_matching_rejected_fact(
    store: MemoryStore,
    text: str,
    *,
    key: str | None = None,
    except_id: int | None = None,
) -> Any | None:
    return _find_matching_fact(
        store, text, statuses=("rejected",), key=key, except_id=except_id
    )


def _reject_other_live_matches(
    store: MemoryStore,
    *,
    fact_id: int,
    text: str,
    key: str | None,
    now: str,
) -> None:
    fact_key = _normalize_fact_key(key)
    for row in _live_fact_rows(store, except_id=fact_id):
        same_key = fact_key is not None and _row_key(row) == fact_key
        if same_key or _facts_are_near_duplicates(text, str(row["text"] or "")):
            store._conn.execute(
                """
                UPDATE facts
                SET status = 'rejected', updated_at = ?
                WHERE id = ?
                """,
                (now, int(row["id"])),
            )


def _refresh_existing_fact(
    store: MemoryStore,
    existing: Any,
    *,
    text: str,
    source: str,
    status: str,
    session_id: str | None,
    key: str | None,
) -> int:
    """Update a live row in place. Never demotes an active fact to pending."""
    fid = int(existing["id"])
    current_status = str(existing["status"])
    if current_status == "active" and status == "pending":
        return fid
    now = _utc_now()
    new_key = key if key is not None else _row_key(existing)
    sid = session_id if session_id is not None else existing["session_id"]
    store._conn.execute(
        """
        UPDATE facts
        SET text = ?, source = ?, status = ?, updated_at = ?, session_id = ?, key = ?
        WHERE id = ?
        """,
        (text, source, status, now, sid, new_key, fid),
    )
    _reject_other_live_matches(store, fact_id=fid, text=text, key=new_key, now=now)
    store._conn.commit()
    return fid


def on_pending_fact(store: MemoryStore, text: str) -> None:
    """Save a proposed fact as durable memory. Near-duplicates update in place."""
    store.add_fact(
        text,
        source="proposed",
        status="active",
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
    """Insert a fact, or update a normalized/near-duplicate row in place.

    Returns its id, or None if the text was empty.
    """
    cleaned = text.strip()
    if not cleaned:
        return None
    if source not in {"explicit", "proposed"}:
        raise ValueError(f"unknown fact source {source!r}")
    if status not in {"active", "pending", "rejected"}:
        raise ValueError(f"unknown fact status {status!r}")
    fact_key = _normalize_fact_key(key)
    existing = _find_matching_live_fact(store, cleaned, key=fact_key)
    if existing is not None:
        return _refresh_existing_fact(
            store,
            existing,
            text=cleaned,
            source=source,
            status=status,
            session_id=session_id,
            key=fact_key,
        )
    rejected = _find_matching_rejected_fact(store, cleaned, key=fact_key)
    if rejected is not None:
        # An explicit remember after an Allow card may bring the claim back.
        # A summarizer proposal must not.
        if source == "explicit" and status == "active":
            return _refresh_existing_fact(
                store,
                rejected,
                text=cleaned,
                source=source,
                status=status,
                session_id=session_id,
                key=fact_key,
            )
        return int(rejected["id"])
    now = _utc_now()
    cur = store._conn.execute(
        """
        INSERT INTO facts
            (text, source, status, created_at, updated_at, session_id, key)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (cleaned, source, status, now, now, session_id, fact_key),
    )
    store._conn.commit()
    return _inserted_id(cur)


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


def edit_fact(store: MemoryStore, fact_id: int, text: str) -> bool:
    """Rewrite a live fact in place. True when a row changed."""
    cleaned = text.strip()
    if not cleaned:
        return False
    fid = int(fact_id)
    row = store._conn.execute(
        """
        SELECT id, text, status, key
        FROM facts
        WHERE id = ?
        """,
        (fid,),
    ).fetchone()
    if row is None or str(row["status"]) not in {"active", "pending"}:
        return False
    now = _utc_now()
    store._conn.execute(
        """
        UPDATE facts
        SET text = ?, updated_at = ?
        WHERE id = ?
        """,
        (cleaned, now, fid),
    )
    _reject_other_live_matches(
        store, fact_id=fid, text=cleaned, key=_row_key(row), now=now
    )
    store._conn.commit()
    return True


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


def _same_cluster(left: Any, right: Any) -> bool:
    left_key = _row_key(left)
    right_key = _row_key(right)
    if left_key and right_key and left_key == right_key:
        return True
    return _facts_are_near_duplicates(str(left["text"] or ""), str(right["text"] or ""))


def _pick_survivor(cluster: list[Any]) -> Any:
    actives = [row for row in cluster if str(row["status"]) == "active"]
    pool = actives or cluster

    def _created(row: Any) -> tuple[str, int]:
        return (str(row["created_at"] or ""), int(row["id"]))

    return sorted(pool, key=_created)[0]


def _latest_member(cluster: list[Any]) -> Any:
    def _updated(row: Any) -> tuple[str, int]:
        return (str(row["updated_at"] or ""), int(row["id"]))

    return sorted(cluster, key=_updated)[-1]


def _facts_table_exists(store: MemoryStore) -> bool:
    row = store._conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'facts'"
    ).fetchone()
    return row is not None


def dedupe_and_promote_existing(store: MemoryStore) -> int:
    """Merge live near-duplicates and promote leftover pending facts to active.

    Existing archives only matched exact text, so near-duplicates piled up as
    new rows, and proposed facts stayed pending until a History click (then
    aged out). One pass keeps a single dated row per claim and makes leftover
    proposals durable so they are not lost. A leftover pending wording of a
    claim that was already rejected or forgotten stays rejected. Returns how
    many rows changed.
    """
    # Synthetic older-archive fixtures may not have a facts table yet.
    if not _facts_table_exists(store):
        return 0
    rows = _live_fact_rows(store)
    now = _utc_now()
    changed = 0
    for row in rows:
        created = str(row["created_at"] or "").strip()
        updated = str(row["updated_at"] or "").strip()
        if created and updated:
            continue
        filled_created = created or updated or now
        filled_updated = updated or filled_created
        store._conn.execute(
            """
            UPDATE facts
            SET created_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (filled_created, filled_updated, int(row["id"])),
        )
        changed += 1

    rows = _live_fact_rows(store)
    rejected_rows = _fact_rows(store, statuses=("rejected",))
    clusters: list[list[Any]] = []
    for row in rows:
        placed = False
        for cluster in clusters:
            if any(_same_cluster(row, member) for member in cluster):
                cluster.append(row)
                placed = True
                break
        if not placed:
            clusters.append([row])

    def _blocked_by_rejected(cluster: list[Any]) -> bool:
        if any(str(member["status"]) == "active" for member in cluster):
            return False
        return any(
            _same_cluster(member, rejected)
            for member in cluster
            for rejected in rejected_rows
        )

    for cluster in clusters:
        if _blocked_by_rejected(cluster):
            for row in cluster:
                cur = store._conn.execute(
                    """
                    UPDATE facts
                    SET status = 'rejected', updated_at = ?
                    WHERE id = ? AND status != 'rejected'
                    """,
                    (now, int(row["id"])),
                )
                if cur.rowcount:
                    changed += 1
            continue
        survivor = _pick_survivor(cluster)
        latest = _latest_member(cluster)
        created_dates = [str(row["created_at"] or "") for row in cluster if row["created_at"]]
        updated_dates = [str(row["updated_at"] or "") for row in cluster if row["updated_at"]]
        created_at = min(created_dates) if created_dates else now
        updated_at = max(updated_dates) if updated_dates else created_at
        key = next((k for k in (_row_key(row) for row in cluster) if k), None)
        source = str(latest["source"])
        for row in cluster:
            if str(row["source"]) == "explicit":
                source = "explicit"
                break
        sid = survivor["session_id"]
        for row in cluster:
            if row["session_id"]:
                sid = row["session_id"]
                break
        cur = store._conn.execute(
            """
            UPDATE facts
            SET text = ?, source = ?, status = 'active',
                created_at = ?, updated_at = ?, session_id = ?, key = ?
            WHERE id = ?
            """,
            (
                str(latest["text"]),
                source,
                created_at,
                updated_at,
                sid,
                key,
                int(survivor["id"]),
            ),
        )
        if cur.rowcount:
            changed += 1
        for row in cluster:
            if int(row["id"]) == int(survivor["id"]):
                continue
            store._conn.execute(
                """
                UPDATE facts
                SET status = 'rejected', updated_at = ?
                WHERE id = ?
                """,
                (now, int(row["id"])),
            )
            changed += 1
    store._conn.commit()
    return changed


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
    return _inserted_id(cur)

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
    return _inserted_id(cur)

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
    return _inserted_id(cur)

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


_EPISODE_STAMP = re.compile(r"\b\d{8}-\d{6}(?:-[0-9a-fA-F]+)?\b")


def forget_episode(store: MemoryStore, text: str) -> int:
    """Delete episodes matching the quoted summary, stamp, or pasted list."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return 0
    needles = [cleaned]
    stamps = [s.lower() for s in _EPISODE_STAMP.findall(text or "")]
    rows = list_episodes(store, limit=200)
    ids: list[int] = []
    for row in rows:
        summary = str(row.get("summary") or "").strip()
        if not summary:
            continue
        sl = summary.lower()
        hit = False
        for needle in needles:
            nl = needle.lower()
            if sl == nl:
                hit = True
                break
            # Pasted lists contain the summary as a line. Short summaries
            # like "ok" must not match because they sit inside longer text.
            if len(sl) >= 12 and sl in nl:
                hit = True
                break
            if len(nl) >= 12 and nl in sl:
                hit = True
                break
            if _facts_loosely_match(needle, summary):
                hit = True
                break
        if not hit and stamps and any(st in sl for st in stamps):
            hit = True
        if hit:
            ids.append(int(row["id"]))
    if not ids:
        return 0
    qmarks = ",".join("?" * len(ids))
    cur = store._conn.execute(
        f"DELETE FROM episodes WHERE id IN ({qmarks})",
        ids,
    )
    store._conn.commit()
    return int(cur.rowcount)
