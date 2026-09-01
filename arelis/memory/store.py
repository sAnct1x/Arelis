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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    r"(?i)^(my|the\s+user(?:['’]s)?|your)\s+"
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
        return sessions.start_session(self, session_id, room_id=room_id)

    def mint_session(self, *, room_id: str = "") -> str:
        """Create a conversation without making it this process's open seat."""
        return sessions.mint_session(self, room_id=room_id)

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
        return sessions.start_glass_session(self)

    def _session_has_messages(self, session_id: str) -> bool:
        return sessions._session_has_messages(self, session_id)

    def open_session(self, session_id: str) -> bool:
        """Point the sink at an existing session. False if it is not in the archive."""
        return sessions.open_session(self, session_id)

    def on_message(self, role: str, content: str, note: str = "") -> None:
        """Persist one message. Called from SessionMemory.add when a sink is set."""
        return sessions.on_message(self, role, content, note)

    def append_to_session(
        self, session_id: str, role: str, content: str, note: str = ""
    ) -> bool:
        """Write into another conversation without switching this process's seat."""
        return sessions.append_to_session(self, session_id, role, content, note)

    def on_summary(self, text: str) -> None:
        return sessions.on_summary(self, text)

    def on_pending_fact(self, text: str) -> None:
        """Record a proposed fact. Nothing becomes active without a later click."""
        return facts.on_pending_fact(self, text)

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
        return facts.add_fact(
            self, text, source=source, status=status, session_id=session_id, key=key
        )

    def list_facts(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return facts.list_facts(self, status=status, limit=limit)

    def set_fact_status(self, fact_id: int, status: str) -> bool:
        """Approve or reject a pending fact. True when a row changed."""
        return facts.set_fact_status(self, fact_id, status)

    def archive_stale_pending_facts(self, *, older_than_days: int = 30) -> int:
        """Reject pending facts older than the cutoff. Returns how many rows changed."""
        return facts.archive_stale_pending_facts(self, older_than_days=older_than_days)

    def _supersede_active_by_key(
        self, key: str, *, except_id: int | None = None
    ) -> None:
        """Reject other active facts that share this key."""
        return facts._supersede_active_by_key(self, key, except_id=except_id)

    def active_fact_texts(self, *, limit: int = 24) -> list[str]:
        return facts.active_fact_texts(self, limit=limit)

    def forget_fact(self, text: str) -> int:
        """Deactivate active facts matching text. Returns how many rows changed."""
        return facts.forget_fact(self, text)

    def add_task(
        self,
        title: str,
        *,
        due: str | None = None,
        goal_id: int | None = None,
        source: str = "explicit",
    ) -> int | None:
        """Insert an open task. Returns its id, or None if the title was empty."""
        return tasks.add_task(self, title, due=due, goal_id=goal_id, source=source)

    def list_tasks(
        self,
        *,
        status: str | None = "open",
        goal_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List tasks. Default status is open; pass status=None for all."""
        return tasks.list_tasks(self, status=status, goal_id=goal_id, limit=limit)

    def get_task(self, task_id: int) -> dict[str, Any] | None:
        return tasks.get_task(self, task_id)

    def set_task_status(self, task_id: int, status: str) -> bool:
        """Mark a task open or done. True when a row changed."""
        return tasks.set_task_status(self, task_id, status)

    def set_task_goal(self, task_id: int, goal_id: int | None) -> bool:
        """Attach or detach a task from a goal. True when a row changed."""
        return tasks.set_task_goal(self, task_id, goal_id)

    def remove_task(self, task_id: int) -> bool:
        """Delete a task by id. True when a row was removed."""
        return tasks.remove_task(self, task_id)

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
        return tasks.add_goal(self, title, kind=kind, horizon=horizon, notes=notes, source=source)

    def list_goals(
        self,
        *,
        status: str | None = "active",
        kind: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List goals. Default status is active; pass status=None for all."""
        return tasks.list_goals(self, status=status, kind=kind, limit=limit)

    def get_goal(self, goal_id: int) -> dict[str, Any] | None:
        return tasks.get_goal(self, goal_id)

    def set_goal_status(self, goal_id: int, status: str) -> bool:
        """Set goal status. True when a row changed."""
        return tasks.set_goal_status(self, goal_id, status)

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
        return tasks.update_goal(
            self,
            goal_id,
            title=title,
            kind=kind,
            horizon=horizon,
            notes=notes,
            clear_horizon=clear_horizon,
            clear_notes=clear_notes,
        )

    def remove_goal(self, goal_id: int) -> bool:
        """Hard-delete a goal by id. True when a row was removed."""
        return tasks.remove_goal(self, goal_id)

    def set_preference(self, key: str, value: str) -> int | None:
        """Upsert a preference by key. Returns its id, or None if empty."""
        return facts.set_preference(self, key, value)

    def get_preference(self, key: str) -> str | None:
        return facts.get_preference(self, key)

    def list_preferences(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return facts.list_preferences(self, limit=limit)

    def add_decision(self, project: str, text: str) -> int | None:
        """Record a project-scoped decision. Returns its id, or None if empty."""
        return facts.add_decision(self, project, text)

    def list_decisions(
        self, project: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        return facts.list_decisions(self, project, limit)

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
        return facts.add_episode(
            self, summary, source=source, session_id=session_id, project=project
        )

    def list_episodes(
        self, *, limit: int = 20, project: str | None = None
    ) -> list[dict[str, Any]]:
        """Recent episodes, newest first. Optional project filter."""
        return facts.list_episodes(self, limit=limit, project=project)

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
        return sessions.latest_session_id(self, require_messages=require_messages, room_id=room_id)

    def list_sessions(
        self, *, limit: int = 50, room_id: str | None = None
    ) -> list[dict[str, Any]]:
        return sessions.list_sessions(self, limit=limit, room_id=room_id)

    def delete_session(self, session_id: str) -> bool:
        """Remove a conversation and cascaded messages/summaries. True if deleted."""
        return sessions.delete_session(self, session_id)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return sessions.get_session(self, session_id)

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return sessions.get_messages(self, session_id)

    def get_summary(self, session_id: str) -> str:
        return sessions.get_summary(self, session_id)

    def search(self, query: str, *, limit: int = 20) -> list[SearchHit]:
        """Keyword search across archived messages.

        Uses FTS5 when the bundled SQLite has it; otherwise LIKE. Callers that
        need to tell the user which path ran can read fts_available.
        """
        return search.search(self, query, limit=limit)

    def search_documents(self, query: str, *, limit: int = 20) -> list[SearchHit]:
        """Keyword search across indexed workspace file chunks."""
        return search.search_documents(self, query, limit=limit)

    def list_documents(self) -> list[dict[str, Any]]:
        return search.list_documents(self)

    def get_document(self, root_name: str, rel_path: str) -> dict[str, Any] | None:
        return search.get_document(self, root_name, rel_path)

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
        return search.replace_document_chunks(
            self,
            root_name=root_name,
            rel_path=rel_path,
            mtime_ns=mtime_ns,
            size=size,
            chunks=chunks,
        )

    def delete_documents_not_in(self, keep: set[tuple[str, str]]) -> int:
        """Drop indexed files that no longer exist on disk. Returns rows removed."""
        return search.delete_documents_not_in(self, keep)

    def unembedded_document_chunks(self, *, limit: int = 32) -> list[dict[str, Any]]:
        return search.unembedded_document_chunks(self, limit=limit)

    def upsert_document_embedding(
        self,
        chunk_id: int,
        model: str,
        vector: list[float] | np.ndarray,
    ) -> None:
        return search.upsert_document_embedding(self, chunk_id, model, vector)

    def vector_search_documents(
        self,
        query: list[float] | np.ndarray,
        *,
        model: str,
        limit: int = 20,
    ) -> list[SearchHit]:
        return search.vector_search_documents(self, query, model=model, limit=limit)

    def search_mail(self, query: str, *, limit: int = 20) -> list[SearchHit]:
        return search.search_mail(self, query, limit=limit)

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
        return search.upsert_mail_message(
            self,
            uid=uid,
            sender=sender,
            subject=subject,
            date_text=date_text,
            unread=unread,
            body=body,
        )

    def delete_mail_not_in(self, keep_uids: set[str]) -> int:
        return search.delete_mail_not_in(self, keep_uids)

    def unembedded_mail(self, *, limit: int = 32) -> list[dict[str, Any]]:
        return search.unembedded_mail(self, limit=limit)

    def upsert_mail_embedding(
        self,
        mail_id: int,
        model: str,
        vector: list[float] | np.ndarray,
    ) -> None:
        return search.upsert_mail_embedding(self, mail_id, model, vector)

    def vector_search_mail(
        self,
        query: list[float] | np.ndarray,
        *,
        model: str,
        limit: int = 20,
    ) -> list[SearchHit]:
        return search.vector_search_mail(self, query, model=model, limit=limit)

    def unembedded_messages(self, *, limit: int = 32) -> list[dict[str, Any]]:
        return search.unembedded_messages(self, limit=limit)

    def upsert_embedding(
        self,
        message_id: int,
        model: str,
        vector: list[float] | np.ndarray,
    ) -> None:
        return search.upsert_embedding(self, message_id, model, vector)

    def vector_search(
        self,
        query: list[float] | np.ndarray,
        *,
        model: str,
        limit: int = 20,
    ) -> list[SearchHit]:
        """Nearest messages by cosine similarity for one embedding model."""
        return search.vector_search(self, query, model=model, limit=limit)

    def _search_fts(self, query: str, *, limit: int) -> list[SearchHit]:
        # Quote each token so punctuation in the user's words cannot break
        # the FTS query syntax; MATCH still does prefix-friendly AND of terms.
        return search._search_fts(self, query, limit=limit)

    def _search_like(self, query: str, *, limit: int) -> list[SearchHit]:
        return search._search_like(self, query, limit=limit)

    def _search_documents_fts(self, query: str, *, limit: int) -> list[SearchHit]:
        return search._search_documents_fts(self, query, limit=limit)

    def _search_documents_like(self, query: str, *, limit: int) -> list[SearchHit]:
        return search._search_documents_like(self, query, limit=limit)

    def _doc_hit(self, row: sqlite3.Row) -> SearchHit:
        return search._doc_hit(self, row)

    def _search_mail_fts(self, query: str, *, limit: int) -> list[SearchHit]:
        return search._search_mail_fts(self, query, limit=limit)

    def _search_mail_like(self, query: str, *, limit: int) -> list[SearchHit]:
        return search._search_mail_like(self, query, limit=limit)

    def _mail_hit(self, row: sqlite3.Row) -> SearchHit:
        return search._mail_hit(self, row)

    def _probe_fts(self) -> bool:
        return search._probe_fts(self)


# After MemoryStore helpers exist — the parts import those names at load.
from arelis.memory import store_facts as facts  # noqa: E402
from arelis.memory import store_search as search  # noqa: E402
from arelis.memory import store_sessions as sessions  # noqa: E402
from arelis.memory import store_tasks as tasks  # noqa: E402
