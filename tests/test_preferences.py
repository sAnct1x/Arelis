"""Typed memory v1: preferences, decisions, and memory-tool actions."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.memory import MemoryStore
from arelis.memory.store import SCHEMA_VERSION
from arelis.tools import build_tool_registry
from arelis.tools.memory_tool import MemoryTool
from arelis.tools.recall import RecallTool
from arelis.workspace import WorkspaceRoots


def test_schema_v5_on_fresh_store(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    assert store.schema_version == SCHEMA_VERSION
    store.close()


def test_preferences_set_get_list_and_upsert(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    first = store.set_preference("units", "metric")
    assert first is not None
    assert store.get_preference("units") == "metric"
    second = store.set_preference("units", "imperial")
    assert second == first
    assert store.get_preference("units") == "imperial"
    store.set_preference("tone", "direct")
    prefs = store.list_preferences()
    keys = {p["key"] for p in prefs}
    assert keys == {"tone", "units"}
    assert store.get_preference("missing") is None
    assert store.set_preference("", "x") is None
    store.close()


def test_decisions_are_project_scoped(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    a = store.add_decision("arelis", "Use local ICS until Google is authorized")
    b = store.add_decision("arelis", "Keep 7B as the hot chat model")
    other = store.add_decision("other", "Unrelated")
    assert a and b and other
    rows = store.list_decisions("arelis", limit=10)
    texts = [r["text"] for r in rows]
    assert "Keep 7B as the hot chat model" in texts
    assert "Use local ICS until Google is authorized" in texts
    assert "Unrelated" not in texts
    assert store.list_decisions("missing") == []
    assert store.add_decision("", "nope") is None
    store.close()


def test_v4_archive_migrates_to_v5(tmp_path: Path) -> None:
    """Opening a schema-4 file adds preferences/decisions without losing tasks."""
    import sqlite3

    path = tmp_path / "memory.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        PRAGMA user_version = 4;
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            title TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            ordinal INTEGER NOT NULL
        );
        CREATE TABLE summaries (
            session_id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            source TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            session_id TEXT
        );
        CREATE TABLE embeddings (
            message_id INTEGER PRIMARY KEY,
            model TEXT NOT NULL,
            dims INTEGER NOT NULL,
            vector BLOB NOT NULL
        );
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            root_name TEXT NOT NULL,
            rel_path TEXT NOT NULL,
            mtime_ns INTEGER NOT NULL,
            size INTEGER NOT NULL,
            indexed_at TEXT NOT NULL,
            UNIQUE(root_name, rel_path)
        );
        CREATE TABLE document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            ordinal INTEGER NOT NULL,
            content TEXT NOT NULL,
            UNIQUE(document_id, ordinal)
        );
        CREATE TABLE document_embeddings (
            chunk_id INTEGER PRIMARY KEY,
            model TEXT NOT NULL,
            dims INTEGER NOT NULL,
            vector BLOB NOT NULL
        );
        CREATE TABLE mail_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL UNIQUE,
            sender TEXT NOT NULL,
            subject TEXT NOT NULL,
            date_text TEXT NOT NULL,
            unread INTEGER NOT NULL DEFAULT 0,
            body TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        );
        CREATE TABLE mail_embeddings (
            mail_id INTEGER PRIMARY KEY,
            model TEXT NOT NULL,
            dims INTEGER NOT NULL,
            vector BLOB NOT NULL
        );
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            due TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            source TEXT NOT NULL
        );
        INSERT INTO tasks (title, status, due, created_at, updated_at, source)
        VALUES ('Keep me', 'open', NULL, '2026-01-01T00:00:00+00:00',
                '2026-01-01T00:00:00+00:00', 'explicit');
        """
    )
    conn.commit()
    conn.close()

    store = MemoryStore(path)
    assert store.schema_version == SCHEMA_VERSION
    assert store.list_tasks(status="open")[0]["title"] == "Keep me"
    assert store.set_preference("units", "metric") is not None
    assert store.add_decision("arelis", "Ship typed memory") is not None
    store.close()


@pytest.mark.asyncio
async def test_memory_tool_prefer_and_decide(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    tool = MemoryTool(store)

    pref = await tool.run(action="prefer", key="units", value="metric")
    assert pref.ok
    assert store.get_preference("units") == "metric"

    via_remember = await tool.run(
        action="remember",
        type="preference",
        key="coffee",
        fact="black",
    )
    assert via_remember.ok
    assert store.get_preference("coffee") == "black"

    decision = await tool.run(
        action="decide",
        project="arelis",
        text="Freeze model tags until scoreboard fails",
    )
    assert decision.ok
    assert store.list_decisions("arelis")[0]["text"].startswith("Freeze model")
    store.close()


def test_prefer_and_decide_need_confirm(tmp_path: Path) -> None:
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    store = MemoryStore(tmp_path / "memory.db")
    registry = build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, memory_store=store
    )
    assert registry.needs_confirm(
        "memory", {"action": "prefer", "key": "units", "value": "metric"}
    )
    assert registry.needs_confirm(
        "memory",
        {"action": "decide", "project": "arelis", "text": "Ship it"},
    )
    store.close()


@pytest.mark.asyncio
async def test_recall_supports_offset_and_page(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    for i in range(5):
        store.on_message("user", f"marker-{i} telescope note")
    tool = RecallTool(store)

    page1 = await tool.run(action="search", query="telescope", limit=2, page=1)
    assert page1.ok
    assert page1.data["offset"] == 0
    assert len(page1.data["hits"]) == 2

    page2 = await tool.run(action="search", query="telescope", limit=2, page=2)
    assert page2.ok
    assert page2.data["offset"] == 2
    assert len(page2.data["hits"]) == 2

    offset = await tool.run(action="search", query="telescope", limit=2, offset=1)
    assert offset.ok
    assert offset.data["offset"] == 1
    assert "offset" in tool.parameters_schema["properties"]
    assert "page" in tool.parameters_schema["properties"]
    store.close()
