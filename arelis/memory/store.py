"""SQLite archive of conversations, summaries, and facts.

SessionMemory stays the in-process working set. This store is the sink the UI
and CLI attach so a force-quit loses at most the turn in progress. Scheduled
jobs deliberately construct SessionMemory with no sink, so an unattended run
neither reads nor writes here.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np

from arelis.paths import state_dir

log = logging.getLogger(__name__)

_DEFAULT_PATH = state_dir() / "memory.db"

# Bump when the on-disk shape changes, and add a _migrate_to_N step. Opening an
# older file without this is what turns a weekend of chat into a hard error.
SCHEMA_VERSION = 10

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    title TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    ordinal INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session_ordinal
    ON messages(session_id, ordinal);

CREATE TABLE IF NOT EXISTS summaries (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status);

CREATE TABLE IF NOT EXISTS embeddings (
    message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dims INTEGER NOT NULL,
    vector BLOB NOT NULL
);
"""

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_name TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    mtime_ns INTEGER NOT NULL,
    size INTEGER NOT NULL,
    indexed_at TEXT NOT NULL,
    UNIQUE(root_name, rel_path)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    content TEXT NOT NULL,
    UNIQUE(document_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_document
    ON document_chunks(document_id);

CREATE TABLE IF NOT EXISTS document_embeddings (
    chunk_id INTEGER PRIMARY KEY REFERENCES document_chunks(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dims INTEGER NOT NULL,
    vector BLOB NOT NULL
);
"""

_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS mail_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uid TEXT NOT NULL UNIQUE,
    sender TEXT NOT NULL,
    subject TEXT NOT NULL,
    date_text TEXT NOT NULL,
    unread INTEGER NOT NULL DEFAULT 0,
    body TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mail_embeddings (
    mail_id INTEGER PRIMARY KEY REFERENCES mail_messages(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dims INTEGER NOT NULL,
    vector BLOB NOT NULL
);
"""

_SCHEMA_V4 = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    due TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
"""

_SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_project ON decisions(project);
"""

_SCHEMA_V7 = """
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    source TEXT NOT NULL,
    project TEXT
);

CREATE INDEX IF NOT EXISTS idx_episodes_created ON episodes(created_at);
CREATE INDEX IF NOT EXISTS idx_episodes_project ON episodes(project)
    WHERE project IS NOT NULL;
"""

_SCHEMA_V8 = """
CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    horizon TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);
CREATE INDEX IF NOT EXISTS idx_goals_kind ON goals(kind);
"""

# v9: optional link from a chore to a durable goal (no progress %).
_SCHEMA_V9 = """
CREATE INDEX IF NOT EXISTS idx_tasks_goal_id ON tasks(goal_id)
    WHERE goal_id IS NOT NULL;
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    note,
    content='messages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, note)
    VALUES (new.id, new.content, new.note);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, note)
    VALUES ('delete', old.id, old.content, old.note);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content, note)
    VALUES ('delete', old.id, old.content, old.note);
    INSERT INTO messages_fts(rowid, content, note)
    VALUES (new.id, new.content, new.note);
END;
"""

_DOC_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
    content,
    content='document_chunks',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS document_chunks_fts_ai AFTER INSERT ON document_chunks BEGIN
    INSERT INTO document_chunks_fts(rowid, content)
    VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS document_chunks_fts_ad AFTER DELETE ON document_chunks BEGIN
    INSERT INTO document_chunks_fts(document_chunks_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS document_chunks_fts_au AFTER UPDATE ON document_chunks BEGIN
    INSERT INTO document_chunks_fts(document_chunks_fts, rowid, content)
    VALUES ('delete', old.id, old.content);
    INSERT INTO document_chunks_fts(rowid, content)
    VALUES (new.id, new.content);
END;
"""

_MAIL_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS mail_messages_fts USING fts5(
    subject,
    sender,
    body,
    content='mail_messages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS mail_messages_fts_ai AFTER INSERT ON mail_messages BEGIN
    INSERT INTO mail_messages_fts(rowid, subject, sender, body)
    VALUES (new.id, new.subject, new.sender, new.body);
END;

CREATE TRIGGER IF NOT EXISTS mail_messages_fts_ad AFTER DELETE ON mail_messages BEGIN
    INSERT INTO mail_messages_fts(mail_messages_fts, rowid, subject, sender, body)
    VALUES ('delete', old.id, old.subject, old.sender, old.body);
END;

CREATE TRIGGER IF NOT EXISTS mail_messages_fts_au AFTER UPDATE ON mail_messages BEGIN
    INSERT INTO mail_messages_fts(mail_messages_fts, rowid, subject, sender, body)
    VALUES ('delete', old.id, old.subject, old.sender, old.body);
    INSERT INTO mail_messages_fts(rowid, subject, sender, body)
    VALUES (new.id, new.subject, new.sender, new.body);
END;
"""


@dataclass(frozen=True)
class SearchHit:
    message_id: int
    session_id: str
    role: str
    content: str
    created_at: str
    title: str
    # chat (default), doc, or mail. Non-chat hits set path + chunk_id; message_id
    # mirrors the row id so older call sites that key on it still have a stable int.
    source: str = "chat"
    path: str = ""
    chunk_id: int = 0

    @property
    def hit_key(self) -> str:
        if self.source == "doc":
            return f"doc:{self.chunk_id or self.message_id}"
        if self.source == "mail":
            return f"mail:{self.chunk_id or self.message_id}"
        return f"chat:{self.message_id}"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


# Owner prefixes stripped before two facts are compared, so "my favourite fruit"
# and "the user's favourite fruit" are recognised as the same claim. The user's
# own name belongs here too — "Dana's favourite fruit" — but it cannot be a
# literal, because a name baked in here works for exactly one person and
# silently does nothing for everyone else. Reading it from the profile is the
# fix; until then this handles the pronoun forms, which are the common case.
_FACT_OWNER = re.compile(
    # The curly apostrophe is listed on purpose: it is what autocorrect
    # produces, and it has to strip the same as the straight form.
    r"(?i)^(my|the\s+user(?:['’]s)?|your)\s+"  # noqa: RUF001
)


def _facts_loosely_match(query: str, stored: str) -> bool:
    """True when forget-that-X should deactivate stored fact Y."""
    q = _FACT_OWNER.sub("", (query or "").strip().lower())
    s = _FACT_OWNER.sub("", (stored or "").strip().lower())
    if not q or not s:
        return False
    if q == s or q in s or s in q:
        return True
    q_toks = {t for t in re.findall(r"[a-z0-9]+", q) if len(t) > 2}
    s_toks = {t for t in re.findall(r"[a-z0-9]+", s) if len(t) > 2}
    if not q_toks or not s_toks:
        return False
    overlap = q_toks & s_toks
    if not overlap:
        return False
    # Distinctive words all match: "climb on tuesdays" vs "You climb on Tuesdays".
    if overlap == q_toks or overlap == s_toks:
        return True
    return len(overlap) >= 3 and overlap >= (q_toks if len(q_toks) <= 4 else set())


def _normalize_fact_key(key: str | None) -> str | None:
    if key is None:
        return None
    cleaned = str(key).strip().lower()
    return cleaned or None


def _fts_match(query: str) -> str:
    tokens = [t for t in query.split() if t]
    if not tokens:
        return ""
    return " ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)


class MemoryStore:
    """Append-only conversation archive at data/memory.db."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else _DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        # WAL lets the desktop app and a scheduled job open the file at once
        # without one failing on a write lock held by the other.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._fts = self._probe_fts()
        self._migrate()
        self.session_id: str | None = None
        self._ordinal = 0
        self._title_set = False

    @property
    def fts_available(self) -> bool:
        return self._fts

    @property
    def schema_version(self) -> int:
        row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row is not None else 0

    def close(self) -> None:
        self._conn.close()

    def _migrate(self) -> None:
        version = self.schema_version
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"{self.path} is schema version {version}, but this build only "
                f"understands up to {SCHEMA_VERSION}. Upgrade Arelis before opening it."
            )
        while version < SCHEMA_VERSION:
            version += 1
            migrator = getattr(self, f"_migrate_to_{version}", None)
            if migrator is None:
                raise RuntimeError(f"Missing migration to schema version {version}")
            migrator()
            self._conn.execute(f"PRAGMA user_version = {version}")
            self._conn.commit()
            log.info("memory.db migrated to schema version %d", version)

    def _migrate_to_1(self) -> None:
        """Initial archive shape: sessions, messages, FTS, facts, embeddings."""
        self._conn.executescript(_SCHEMA_V1)
        if self._fts:
            self._conn.executescript(_FTS_SCHEMA)

    def _migrate_to_2(self) -> None:
        """Workspace document chunks for recall beyond chat."""
        self._conn.executescript(_SCHEMA_V2)
        if self._fts:
            self._conn.executescript(_DOC_FTS_SCHEMA)

    def _migrate_to_3(self) -> None:
        """Indexed mail peeks for recall (opt-in; never marks messages read)."""
        self._conn.executescript(_SCHEMA_V3)
        if self._fts:
            self._conn.executescript(_MAIL_FTS_SCHEMA)

    def _migrate_to_4(self) -> None:
        """Local task list (open/done) for briefing and the tasks tool."""
        self._conn.executescript(_SCHEMA_V4)

    def _migrate_to_5(self) -> None:
        """Typed memory v1: key/value preferences and project-scoped decisions."""
        self._conn.executescript(_SCHEMA_V5)

    def _migrate_to_6(self) -> None:
        """Optional fact keys so a new active fact can supersede siblings."""
        self._conn.execute("ALTER TABLE facts ADD COLUMN key TEXT")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key) "
            "WHERE key IS NOT NULL"
        )

    def _migrate_to_7(self) -> None:
        """Typed memory episodes: short confirmed summaries of a moment."""
        self._conn.executescript(_SCHEMA_V7)

    def _migrate_to_8(self) -> None:
        """Goals and commitments (durable outcomes beyond checkable tasks)."""
        self._conn.executescript(_SCHEMA_V8)

    def _migrate_to_9(self) -> None:
        """Optional tasks.goal_id → goals.id (SET NULL on goal delete)."""
        # Synthetic older-archive tests may skip v4; ensure tasks exists first.
        self._conn.executescript(_SCHEMA_V4)
        cols = {
            str(row[1])
            for row in self._conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if "goal_id" not in cols:
            self._conn.execute(
                "ALTER TABLE tasks ADD COLUMN goal_id INTEGER "
                "REFERENCES goals(id) ON DELETE SET NULL"
            )
        self._conn.executescript(_SCHEMA_V9)

    def _migrate_to_10(self) -> None:
        """Which room a conversation belongs to. Empty string means general.

        A nullable column would make "general" and "unknown" the same value, and
        every existing archive is general by definition — it predates rooms.
        """
        cols = {
            str(row[1])
            for row in self._conn.execute("PRAGMA table_info(sessions)").fetchall()
        }
        if "room_id" not in cols:
            self._conn.execute(
                "ALTER TABLE sessions ADD COLUMN room_id TEXT NOT NULL DEFAULT ''"
            )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_room ON sessions(room_id)"
        )

    def start_session(self, session_id: str | None = None, *, room_id: str = "") -> str:
        """Begin a new session and make it the sink target for later writes."""
        sid = session_id or uuid4().hex
        self._conn.execute(
            "INSERT INTO sessions (id, started_at, title, room_id) VALUES (?, ?, '', ?)",
            (sid, _utc_now(), room_id or ""),
        )
        self._conn.commit()
        self.session_id = sid
        self._ordinal = 0
        self._title_set = False
        return sid

    def mint_session(self, *, room_id: str = "") -> str:
        """Create a conversation without making it this process's open seat."""
        sid = uuid4().hex
        self._conn.execute(
            "INSERT INTO sessions (id, started_at, title, room_id) VALUES (?, ?, '', ?)",
            (sid, _utc_now(), room_id or ""),
        )
        self._conn.commit()
        return sid

    def start_glass_session(self) -> str:
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
        leftover = self.latest_session_id(require_messages=False, room_id="")
        filled = self.latest_session_id(require_messages=True, room_id="")
        if (
            leftover
            and leftover != filled
            and not self._session_has_messages(leftover)
        ):
            self.delete_session(leftover)
        return self.start_session()

    def _session_has_messages(self, session_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM messages WHERE session_id = ? LIMIT 1",
            (session_id,),
        ).fetchone()
        return row is not None

    def open_session(self, session_id: str) -> bool:
        """Point the sink at an existing session. False if it is not in the archive."""
        session = self.get_session(session_id)
        if session is None:
            return False
        row = self._conn.execute(
            "SELECT COALESCE(MAX(ordinal), 0) AS n FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        self.session_id = session_id
        self._ordinal = int(row["n"] if row is not None else 0)
        self._title_set = bool(str(session.get("title") or "").strip())
        return True

    def on_message(self, role: str, content: str, note: str = "") -> None:
        """Persist one message. Called from SessionMemory.add when a sink is set."""
        if self.session_id is None:
            self.start_session()
        self._ordinal += 1
        self._conn.execute(
            """
            INSERT INTO messages (session_id, role, content, note, created_at, ordinal)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (self.session_id, role, content, note, _utc_now(), self._ordinal),
        )
        if role == "user" and not self._title_set and content.strip():
            from arelis.attachments import session_title_from_turn

            title = session_title_from_turn(content)
            if title:
                self._conn.execute(
                    "UPDATE sessions SET title = ? WHERE id = ?",
                    (title, self.session_id),
                )
                self._title_set = True
        self._conn.commit()

    def append_to_session(
        self, session_id: str, role: str, content: str, note: str = ""
    ) -> bool:
        """Write into another conversation without switching this process's seat."""
        sid = (session_id or "").strip()
        if not sid or self.get_session(sid) is None:
            return False
        row = self._conn.execute(
            "SELECT COALESCE(MAX(ordinal), 0) AS n FROM messages WHERE session_id = ?",
            (sid,),
        ).fetchone()
        ordinal = int(row["n"] if row is not None else 0) + 1
        self._conn.execute(
            """
            INSERT INTO messages (session_id, role, content, note, created_at, ordinal)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sid, role, content, note, _utc_now(), ordinal),
        )
        session = self.get_session(sid) or {}
        if role == "user" and not str(session.get("title") or "").strip() and content.strip():
            from arelis.attachments import session_title_from_turn

            title = session_title_from_turn(content)
            if title:
                self._conn.execute(
                    "UPDATE sessions SET title = ? WHERE id = ?",
                    (title, sid),
                )
        self._conn.commit()
        return True

    def on_summary(self, text: str) -> None:
        if self.session_id is None or not text:
            return
        self._conn.execute(
            """
            INSERT INTO summaries (session_id, text, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                text = excluded.text,
                updated_at = excluded.updated_at
            """,
            (self.session_id, text, _utc_now()),
        )
        self._conn.commit()

    def on_pending_fact(self, text: str) -> None:
        """Record a proposed fact. Nothing becomes active without a later click."""
        self.add_fact(
            text,
            source="proposed",
            status="pending",
            session_id=self.session_id,
        )

    def add_fact(
        self,
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
        existing = self._conn.execute(
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
            self._supersede_active_by_key(fact_key)
        cur = self._conn.execute(
            """
            INSERT INTO facts
                (text, source, status, created_at, updated_at, session_id, key)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (cleaned, source, status, now, now, session_id, fact_key),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_facts(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if status is None:
            rows = self._conn.execute(
                """
                SELECT id, text, source, status, created_at, updated_at, session_id, key
                FROM facts
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = self._conn.execute(
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

    def set_fact_status(self, fact_id: int, status: str) -> bool:
        """Approve or reject a pending fact. True when a row changed."""
        if status not in {"active", "pending", "rejected"}:
            raise ValueError(f"unknown fact status {status!r}")
        fid = int(fact_id)
        if status == "active":
            row = self._conn.execute(
                "SELECT key FROM facts WHERE id = ?",
                (fid,),
            ).fetchone()
            fact_key = str(row["key"]).strip() if row is not None and row["key"] else ""
            if fact_key:
                self._supersede_active_by_key(fact_key, except_id=fid)
        cur = self._conn.execute(
            """
            UPDATE facts
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, _utc_now(), fid),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def archive_stale_pending_facts(self, *, older_than_days: int = 30) -> int:
        """Reject pending facts older than the cutoff. Returns how many rows changed."""
        days = max(0, int(older_than_days))
        cutoff = (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0)
        cutoff_iso = cutoff.isoformat()
        cur = self._conn.execute(
            """
            UPDATE facts
            SET status = 'rejected', updated_at = ?
            WHERE status = 'pending' AND created_at < ?
            """,
            (_utc_now(), cutoff_iso),
        )
        self._conn.commit()
        return int(cur.rowcount)

    def _supersede_active_by_key(
        self, key: str, *, except_id: int | None = None
    ) -> None:
        """Reject other active facts that share this key."""
        now = _utc_now()
        if except_id is None:
            self._conn.execute(
                """
                UPDATE facts
                SET status = 'rejected', updated_at = ?
                WHERE status = 'active' AND key = ?
                """,
                (now, key),
            )
        else:
            self._conn.execute(
                """
                UPDATE facts
                SET status = 'rejected', updated_at = ?
                WHERE status = 'active' AND key = ? AND id != ?
                """,
                (now, key, int(except_id)),
            )

    def active_fact_texts(self, *, limit: int = 24) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT text FROM facts
            WHERE status = 'active'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [str(row["text"]) for row in rows]

    def forget_fact(self, text: str) -> int:
        """Deactivate active facts matching text. Returns how many rows changed."""
        cleaned = text.strip()
        if not cleaned:
            return 0
        cur = self._conn.execute(
            """
            UPDATE facts
            SET status = 'rejected', updated_at = ?
            WHERE status = 'active' AND lower(text) = lower(?)
            """,
            (_utc_now(), cleaned),
        )
        if cur.rowcount:
            self._conn.commit()
            return int(cur.rowcount)
        # "my favorite test fruit is durian" must match
        # "the user's favorite test fruit is durian".
        for stored in self.active_fact_texts(limit=40):
            if _facts_loosely_match(cleaned, stored):
                cur = self._conn.execute(
                    """
                    UPDATE facts
                    SET status = 'rejected', updated_at = ?
                    WHERE status = 'active' AND text = ?
                    """,
                    (_utc_now(), stored),
                )
                self._conn.commit()
                return int(cur.rowcount)
        self._conn.commit()
        return 0

    def add_task(
        self,
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
            if self.get_goal(gid) is None:
                raise ValueError(f"no goal with id {gid}")
        now = _utc_now()
        cur = self._conn.execute(
            """
            INSERT INTO tasks
                (title, status, due, created_at, updated_at, source, goal_id)
            VALUES (?, 'open', ?, ?, ?, ?, ?)
            """,
            (cleaned, due_text, now, now, source_text, gid),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_tasks(
        self,
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
        rows = self._conn.execute(
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

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT id, title, status, due, created_at, updated_at, source, goal_id
            FROM tasks
            WHERE id = ?
            """,
            (int(task_id),),
        ).fetchone()
        return dict(row) if row else None

    def set_task_status(self, task_id: int, status: str) -> bool:
        """Mark a task open or done. True when a row changed."""
        if status not in {"open", "done"}:
            raise ValueError(f"unknown task status {status!r}")
        cur = self._conn.execute(
            """
            UPDATE tasks
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, _utc_now(), int(task_id)),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def set_task_goal(self, task_id: int, goal_id: int | None) -> bool:
        """Attach or detach a task from a goal. True when a row changed."""
        tid = int(task_id)
        if self.get_task(tid) is None:
            return False
        gid: int | None = None
        if goal_id is not None:
            gid = int(goal_id)
            if self.get_goal(gid) is None:
                raise ValueError(f"no goal with id {gid}")
        cur = self._conn.execute(
            """
            UPDATE tasks
            SET goal_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (gid, _utc_now(), tid),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def remove_task(self, task_id: int) -> bool:
        """Delete a task by id. True when a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM tasks WHERE id = ?",
            (int(task_id),),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def add_goal(
        self,
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
        cur = self._conn.execute(
            """
            INSERT INTO goals
                (title, kind, status, horizon, notes, created_at, updated_at, source)
            VALUES (?, ?, 'active', ?, ?, ?, ?, ?)
            """,
            (cleaned, kind_text, horizon_text, notes_text, now, now, source_text),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_goals(
        self,
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
        rows = self._conn.execute(
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

    def get_goal(self, goal_id: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT id, title, kind, status, horizon, notes,
                   created_at, updated_at, source
            FROM goals
            WHERE id = ?
            """,
            (int(goal_id),),
        ).fetchone()
        return dict(row) if row else None

    def set_goal_status(self, goal_id: int, status: str) -> bool:
        """Set goal status. True when a row changed."""
        if status not in {"active", "paused", "done", "dropped"}:
            raise ValueError(f"unknown goal status {status!r}")
        cur = self._conn.execute(
            """
            UPDATE goals
            SET status = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, _utc_now(), int(goal_id)),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_goal(
        self,
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
        existing = self.get_goal(goal_id)
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
        cur = self._conn.execute(
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
        self._conn.commit()
        return cur.rowcount > 0

    def remove_goal(self, goal_id: int) -> bool:
        """Hard-delete a goal by id. True when a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM goals WHERE id = ?",
            (int(goal_id),),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def set_preference(self, key: str, value: str) -> int | None:
        """Upsert a preference by key. Returns its id, or None if empty."""
        cleaned_key = key.strip()
        cleaned_value = value.strip()
        if not cleaned_key or not cleaned_value:
            return None
        now = _utc_now()
        existing = self._conn.execute(
            "SELECT id FROM preferences WHERE key = ?",
            (cleaned_key,),
        ).fetchone()
        if existing is not None:
            pref_id = int(existing["id"])
            self._conn.execute(
                """
                UPDATE preferences
                SET value = ?, updated_at = ?
                WHERE id = ?
                """,
                (cleaned_value, now, pref_id),
            )
            self._conn.commit()
            return pref_id
        cur = self._conn.execute(
            """
            INSERT INTO preferences (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            (cleaned_key, cleaned_value, now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def get_preference(self, key: str) -> str | None:
        cleaned_key = key.strip()
        if not cleaned_key:
            return None
        row = self._conn.execute(
            "SELECT value FROM preferences WHERE key = ?",
            (cleaned_key,),
        ).fetchone()
        return str(row["value"]) if row is not None else None

    def list_preferences(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, key, value, updated_at
            FROM preferences
            ORDER BY key ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_decision(self, project: str, text: str) -> int | None:
        """Record a project-scoped decision. Returns its id, or None if empty."""
        cleaned_project = project.strip()
        cleaned_text = text.strip()
        if not cleaned_project or not cleaned_text:
            return None
        now = _utc_now()
        cur = self._conn.execute(
            """
            INSERT INTO decisions (project, text, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (cleaned_project, cleaned_text, now, now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_decisions(
        self, project: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        cleaned_project = project.strip()
        if not cleaned_project:
            return []
        rows = self._conn.execute(
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
        self,
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
        sid = session_id if session_id is not None else self.session_id
        if sid is not None:
            sid = str(sid).strip() or None
        proj = None if project is None else str(project).strip() or None
        cur = self._conn.execute(
            """
            INSERT INTO episodes (summary, created_at, session_id, source, project)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cleaned, _utc_now(), sid, src, proj),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def list_episodes(
        self, *, limit: int = 20, project: str | None = None
    ) -> list[dict[str, Any]]:
        """Recent episodes, newest first. Optional project filter."""
        cap = max(1, min(int(limit), 200))
        if project is not None and str(project).strip():
            rows = self._conn.execute(
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
            rows = self._conn.execute(
                """
                SELECT id, summary, created_at, session_id, source, project
                FROM episodes
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (cap,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_session_id(
        self, *, require_messages: bool = True, room_id: str | None = None
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
        row = self._conn.execute(
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
        self, *, limit: int = 50, room_id: str | None = None
    ) -> list[dict[str, Any]]:
        where = "WHERE room_id = ?" if room_id is not None else ""
        params: list[Any] = [room_id] if room_id is not None else []
        params.append(limit)
        rows = self._conn.execute(
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

    def delete_session(self, session_id: str) -> bool:
        """Remove a conversation and cascaded messages/summaries. True if deleted."""
        sid = (session_id or "").strip()
        if not sid:
            return False
        cur = self._conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        self._conn.commit()
        removed = cur.rowcount > 0
        if removed and self.session_id == sid:
            self.session_id = None
            self._ordinal = 0
            self._title_set = False
        return removed

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT id, started_at, ended_at, title, room_id
            FROM sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, role, content, note, created_at, ordinal
            FROM messages
            WHERE session_id = ?
            ORDER BY ordinal ASC
            """,
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_summary(self, session_id: str) -> str:
        row = self._conn.execute(
            "SELECT text FROM summaries WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return str(row["text"]) if row else ""

    def search(self, query: str, *, limit: int = 20) -> list[SearchHit]:
        """Keyword search across archived messages.

        Uses FTS5 when the bundled SQLite has it; otherwise LIKE. Callers that
        need to tell the user which path ran can read fts_available.
        """
        cleaned = query.strip()
        if not cleaned:
            return []
        if self._fts:
            return self._search_fts(cleaned, limit=limit)
        return self._search_like(cleaned, limit=limit)

    def search_documents(self, query: str, *, limit: int = 20) -> list[SearchHit]:
        """Keyword search across indexed workspace file chunks."""
        cleaned = query.strip()
        if not cleaned:
            return []
        if self._fts:
            return self._search_documents_fts(cleaned, limit=limit)
        return self._search_documents_like(cleaned, limit=limit)

    def list_documents(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, root_name, rel_path, mtime_ns, size, indexed_at
            FROM documents
            ORDER BY root_name, rel_path
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_document(self, root_name: str, rel_path: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT id, root_name, rel_path, mtime_ns, size, indexed_at
            FROM documents
            WHERE root_name = ? AND rel_path = ?
            """,
            (root_name, rel_path),
        ).fetchone()
        return dict(row) if row else None

    def replace_document_chunks(
        self,
        *,
        root_name: str,
        rel_path: str,
        mtime_ns: int,
        size: int,
        chunks: list[str],
    ) -> int:
        """Upsert a document and replace its chunks. Returns document id."""
        now = _utc_now()
        existing = self.get_document(root_name, rel_path)
        if existing is None:
            cur = self._conn.execute(
                """
                INSERT INTO documents (root_name, rel_path, mtime_ns, size, indexed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (root_name, rel_path, int(mtime_ns), int(size), now),
            )
            doc_id = int(cur.lastrowid)
        else:
            doc_id = int(existing["id"])
            self._conn.execute(
                """
                UPDATE documents
                SET mtime_ns = ?, size = ?, indexed_at = ?
                WHERE id = ?
                """,
                (int(mtime_ns), int(size), now, doc_id),
            )
            self._conn.execute(
                "DELETE FROM document_chunks WHERE document_id = ?", (doc_id,)
            )
        for ordinal, text in enumerate(chunks):
            cleaned = text.strip()
            if not cleaned:
                continue
            self._conn.execute(
                """
                INSERT INTO document_chunks (document_id, ordinal, content)
                VALUES (?, ?, ?)
                """,
                (doc_id, ordinal, cleaned),
            )
        self._conn.commit()
        return doc_id

    def delete_documents_not_in(self, keep: set[tuple[str, str]]) -> int:
        """Drop indexed files that no longer exist on disk. Returns rows removed."""
        rows = self.list_documents()
        removed = 0
        for row in rows:
            key = (str(row["root_name"]), str(row["rel_path"]))
            if key in keep:
                continue
            self._conn.execute("DELETE FROM documents WHERE id = ?", (int(row["id"]),))
            removed += 1
        if removed:
            self._conn.commit()
        return removed

    def unembedded_document_chunks(self, *, limit: int = 32) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT c.id, c.content
            FROM document_chunks c
            LEFT JOIN document_embeddings e ON e.chunk_id = c.id
            WHERE e.chunk_id IS NULL
              AND length(trim(c.content)) > 0
            ORDER BY c.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_document_embedding(
        self,
        chunk_id: int,
        model: str,
        vector: list[float] | np.ndarray,
    ) -> None:
        arr = np.asarray(vector, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return
        self._conn.execute(
            """
            INSERT INTO document_embeddings (chunk_id, model, dims, vector)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chunk_id) DO UPDATE SET
                model = excluded.model,
                dims = excluded.dims,
                vector = excluded.vector
            """,
            (int(chunk_id), model, int(arr.size), arr.tobytes()),
        )
        self._conn.commit()

    def vector_search_documents(
        self,
        query: list[float] | np.ndarray,
        *,
        model: str,
        limit: int = 20,
    ) -> list[SearchHit]:
        q = np.asarray(query, dtype=np.float32).reshape(-1)
        if q.size == 0:
            return []
        q_norm = float(np.linalg.norm(q))
        if q_norm == 0.0:
            return []
        q = q / q_norm
        rows = self._conn.execute(
            """
            SELECT e.chunk_id, e.dims, e.vector,
                   c.content, d.root_name, d.rel_path, d.indexed_at
            FROM document_embeddings e
            JOIN document_chunks c ON c.id = e.chunk_id
            JOIN documents d ON d.id = c.document_id
            WHERE e.model = ?
            """,
            (model,),
        ).fetchall()
        if not rows:
            return []
        meta: list[sqlite3.Row] = []
        vectors: list[np.ndarray] = []
        for row in rows:
            dims = int(row["dims"])
            vec = np.frombuffer(row["vector"], dtype=np.float32)
            if vec.size != dims or vec.size != q.size:
                continue
            meta.append(row)
            vectors.append(vec)
        if not vectors:
            return []
        matrix = np.stack(vectors, axis=0)
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0.0] = 1.0
        scores = (matrix / norms[:, None]) @ q
        order = np.argsort(-scores)[:limit]
        hits: list[SearchHit] = []
        for idx in order:
            row = meta[int(idx)]
            hits.append(self._doc_hit(row))
        return hits

    def search_mail(self, query: str, *, limit: int = 20) -> list[SearchHit]:
        cleaned = query.strip()
        if not cleaned:
            return []
        if self._fts:
            return self._search_mail_fts(cleaned, limit=limit)
        return self._search_mail_like(cleaned, limit=limit)

    def upsert_mail_message(
        self,
        *,
        uid: str,
        sender: str,
        subject: str,
        date_text: str,
        unread: bool,
        body: str,
    ) -> int:
        """Insert or replace one peeked mail message. Returns its row id."""
        now = _utc_now()
        existing = self._conn.execute(
            "SELECT id FROM mail_messages WHERE uid = ?", (uid,)
        ).fetchone()
        if existing is None:
            cur = self._conn.execute(
                """
                INSERT INTO mail_messages
                    (uid, sender, subject, date_text, unread, body, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    sender,
                    subject,
                    date_text,
                    1 if unread else 0,
                    body,
                    now,
                ),
            )
            mail_id = int(cur.lastrowid)
        else:
            mail_id = int(existing["id"])
            self._conn.execute(
                """
                UPDATE mail_messages
                SET sender = ?, subject = ?, date_text = ?, unread = ?,
                    body = ?, indexed_at = ?
                WHERE id = ?
                """,
                (
                    sender,
                    subject,
                    date_text,
                    1 if unread else 0,
                    body,
                    now,
                    mail_id,
                ),
            )
            # Body change invalidates the old vector.
            self._conn.execute(
                "DELETE FROM mail_embeddings WHERE mail_id = ?", (mail_id,)
            )
        self._conn.commit()
        return mail_id

    def delete_mail_not_in(self, keep_uids: set[str]) -> int:
        rows = self._conn.execute("SELECT id, uid FROM mail_messages").fetchall()
        removed = 0
        for row in rows:
            if str(row["uid"]) in keep_uids:
                continue
            self._conn.execute("DELETE FROM mail_messages WHERE id = ?", (int(row["id"]),))
            removed += 1
        if removed:
            self._conn.commit()
        return removed

    def unembedded_mail(self, *, limit: int = 32) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT m.id, m.subject, m.sender, m.body
            FROM mail_messages m
            LEFT JOIN mail_embeddings e ON e.mail_id = m.id
            WHERE e.mail_id IS NULL
            ORDER BY m.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            text = f"{row['subject']}\nFrom: {row['sender']}\n\n{row['body']}"
            out.append({"id": int(row["id"]), "content": text})
        return out

    def upsert_mail_embedding(
        self,
        mail_id: int,
        model: str,
        vector: list[float] | np.ndarray,
    ) -> None:
        arr = np.asarray(vector, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return
        self._conn.execute(
            """
            INSERT INTO mail_embeddings (mail_id, model, dims, vector)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(mail_id) DO UPDATE SET
                model = excluded.model,
                dims = excluded.dims,
                vector = excluded.vector
            """,
            (int(mail_id), model, int(arr.size), arr.tobytes()),
        )
        self._conn.commit()

    def vector_search_mail(
        self,
        query: list[float] | np.ndarray,
        *,
        model: str,
        limit: int = 20,
    ) -> list[SearchHit]:
        q = np.asarray(query, dtype=np.float32).reshape(-1)
        if q.size == 0:
            return []
        q_norm = float(np.linalg.norm(q))
        if q_norm == 0.0:
            return []
        q = q / q_norm
        rows = self._conn.execute(
            """
            SELECT e.mail_id, e.dims, e.vector,
                   m.uid, m.sender, m.subject, m.date_text, m.body, m.indexed_at
            FROM mail_embeddings e
            JOIN mail_messages m ON m.id = e.mail_id
            WHERE e.model = ?
            """,
            (model,),
        ).fetchall()
        if not rows:
            return []
        meta: list[sqlite3.Row] = []
        vectors: list[np.ndarray] = []
        for row in rows:
            dims = int(row["dims"])
            vec = np.frombuffer(row["vector"], dtype=np.float32)
            if vec.size != dims or vec.size != q.size:
                continue
            meta.append(row)
            vectors.append(vec)
        if not vectors:
            return []
        matrix = np.stack(vectors, axis=0)
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0.0] = 1.0
        scores = (matrix / norms[:, None]) @ q
        order = np.argsort(-scores)[:limit]
        return [self._mail_hit(meta[int(idx)]) for idx in order]

    def unembedded_messages(self, *, limit: int = 32) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT m.id, m.content
            FROM messages m
            LEFT JOIN embeddings e ON e.message_id = m.id
            WHERE e.message_id IS NULL
              AND length(trim(m.content)) > 0
            ORDER BY m.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def upsert_embedding(
        self,
        message_id: int,
        model: str,
        vector: list[float] | np.ndarray,
    ) -> None:
        arr = np.asarray(vector, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return
        self._conn.execute(
            """
            INSERT INTO embeddings (message_id, model, dims, vector)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                model = excluded.model,
                dims = excluded.dims,
                vector = excluded.vector
            """,
            (int(message_id), model, int(arr.size), arr.tobytes()),
        )
        self._conn.commit()

    def vector_search(
        self,
        query: list[float] | np.ndarray,
        *,
        model: str,
        limit: int = 20,
    ) -> list[SearchHit]:
        """Nearest messages by cosine similarity for one embedding model."""
        q = np.asarray(query, dtype=np.float32).reshape(-1)
        if q.size == 0:
            return []
        q_norm = float(np.linalg.norm(q))
        if q_norm == 0.0:
            return []
        q = q / q_norm

        rows = self._conn.execute(
            """
            SELECT e.message_id, e.dims, e.vector,
                   m.session_id, m.role, m.content, m.created_at, s.title
            FROM embeddings e
            JOIN messages m ON m.id = e.message_id
            JOIN sessions s ON s.id = m.session_id
            WHERE e.model = ?
              AND m.role != 'notice'
            """,
            (model,),
        ).fetchall()
        if not rows:
            return []

        ids: list[int] = []
        meta: list[sqlite3.Row] = []
        vectors: list[np.ndarray] = []
        for row in rows:
            dims = int(row["dims"])
            raw = row["vector"]
            vec = np.frombuffer(raw, dtype=np.float32)
            if vec.size != dims or vec.size != q.size:
                continue
            ids.append(int(row["message_id"]))
            meta.append(row)
            vectors.append(vec)

        if not vectors:
            return []

        matrix = np.stack(vectors, axis=0)
        norms = np.linalg.norm(matrix, axis=1)
        norms[norms == 0.0] = 1.0
        scores = (matrix / norms[:, None]) @ q
        order = np.argsort(-scores)[:limit]
        hits: list[SearchHit] = []
        for idx in order:
            row = meta[int(idx)]
            hits.append(
                SearchHit(
                    message_id=int(row["message_id"]),
                    session_id=str(row["session_id"]),
                    role=str(row["role"]),
                    content=str(row["content"]),
                    created_at=str(row["created_at"]),
                    title=str(row["title"] or ""),
                    source="chat",
                )
            )
        return hits

    def _search_fts(self, query: str, *, limit: int) -> list[SearchHit]:
        # Quote each token so punctuation in the user's words cannot break
        # the FTS query syntax; MATCH still does prefix-friendly AND of terms.
        match = _fts_match(query)
        if not match:
            return []
        rows = self._conn.execute(
            """
            SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title
            FROM messages_fts
            JOIN messages m ON m.id = messages_fts.rowid
            JOIN sessions s ON s.id = m.session_id
            WHERE messages_fts MATCH ?
              AND m.role != 'notice'
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (match, limit),
        ).fetchall()
        return [
            SearchHit(
                message_id=int(row["id"]),
                session_id=str(row["session_id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
                title=str(row["title"] or ""),
                source="chat",
            )
            for row in rows
        ]

    def _search_like(self, query: str, *, limit: int) -> list[SearchHit]:
        pattern = f"%{query}%"
        rows = self._conn.execute(
            """
            SELECT m.id, m.session_id, m.role, m.content, m.created_at, s.title
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE (m.content LIKE ? OR m.note LIKE ?)
              AND m.role != 'notice'
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        ).fetchall()
        return [
            SearchHit(
                message_id=int(row["id"]),
                session_id=str(row["session_id"]),
                role=str(row["role"]),
                content=str(row["content"]),
                created_at=str(row["created_at"]),
                title=str(row["title"] or ""),
                source="chat",
            )
            for row in rows
        ]

    def _search_documents_fts(self, query: str, *, limit: int) -> list[SearchHit]:
        match = _fts_match(query)
        if not match:
            return []
        rows = self._conn.execute(
            """
            SELECT c.id, c.content, d.root_name, d.rel_path, d.indexed_at
            FROM document_chunks_fts
            JOIN document_chunks c ON c.id = document_chunks_fts.rowid
            JOIN documents d ON d.id = c.document_id
            WHERE document_chunks_fts MATCH ?
            ORDER BY d.indexed_at DESC
            LIMIT ?
            """,
            (match, limit),
        ).fetchall()
        return [self._doc_hit(row) for row in rows]

    def _search_documents_like(self, query: str, *, limit: int) -> list[SearchHit]:
        pattern = f"%{query}%"
        rows = self._conn.execute(
            """
            SELECT c.id, c.content, d.root_name, d.rel_path, d.indexed_at
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.content LIKE ?
            ORDER BY d.indexed_at DESC
            LIMIT ?
            """,
            (pattern, limit),
        ).fetchall()
        return [self._doc_hit(row) for row in rows]

    def _doc_hit(self, row: sqlite3.Row) -> SearchHit:
        root = str(row["root_name"])
        rel = str(row["rel_path"])
        path = f"{root}:{rel}" if rel else f"{root}:"
        chunk_id = int(row["id"] if "id" in row.keys() else row["chunk_id"])
        return SearchHit(
            message_id=chunk_id,
            session_id="",
            role="file",
            content=str(row["content"]),
            created_at=str(row["indexed_at"] or ""),
            title=path,
            source="doc",
            path=path,
            chunk_id=chunk_id,
        )

    def _search_mail_fts(self, query: str, *, limit: int) -> list[SearchHit]:
        match = _fts_match(query)
        if not match:
            return []
        rows = self._conn.execute(
            """
            SELECT m.id, m.uid, m.sender, m.subject, m.date_text, m.body, m.indexed_at
            FROM mail_messages_fts
            JOIN mail_messages m ON m.id = mail_messages_fts.rowid
            WHERE mail_messages_fts MATCH ?
            ORDER BY m.indexed_at DESC
            LIMIT ?
            """,
            (match, limit),
        ).fetchall()
        return [self._mail_hit(row) for row in rows]

    def _search_mail_like(self, query: str, *, limit: int) -> list[SearchHit]:
        pattern = f"%{query}%"
        rows = self._conn.execute(
            """
            SELECT id, uid, sender, subject, date_text, body, indexed_at
            FROM mail_messages
            WHERE subject LIKE ? OR sender LIKE ? OR body LIKE ?
            ORDER BY indexed_at DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        ).fetchall()
        return [self._mail_hit(row) for row in rows]

    def _mail_hit(self, row: sqlite3.Row) -> SearchHit:
        mail_id = int(row["id"] if "id" in row.keys() else row["mail_id"])
        uid = str(row["uid"])
        subject = str(row["subject"] or "(no subject)")
        sender = str(row["sender"] or "")
        body = str(row["body"] or "")
        content = f"From: {sender}\nSubject: {subject}\n\n{body}"
        return SearchHit(
            message_id=mail_id,
            session_id="",
            role="mail",
            content=content,
            created_at=str(row["date_text"] or row["indexed_at"] or ""),
            title=subject,
            source="mail",
            path=f"mail:{uid}",
            chunk_id=mail_id,
        )

    def _probe_fts(self) -> bool:
        try:
            self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _arelis_fts_probe USING fts5(x)")
            self._conn.execute("DROP TABLE _arelis_fts_probe")
            return True
        except sqlite3.OperationalError:
            log.warning("FTS5 unavailable; memory search will use LIKE")
            return False
