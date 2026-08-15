"""Typed memory episodes (schema v7) and memory-tool episode actions."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.episodes import episodes_prompt_line
from arelis.memory import MemoryStore
from arelis.memory.store import SCHEMA_VERSION
from arelis.tools import build_tool_registry
from arelis.tools.memory_tool import MemoryTool
from arelis.workspace import WorkspaceRoots


def test_schema_v7_on_fresh_store(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    assert store.schema_version == SCHEMA_VERSION
    store.close()


def test_add_and_list_episodes(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    a = store.add_episode("Shipped typed memory", source="manual", project="arelis")
    b = store.add_episode("Confirmed week plan", source="confirm")
    assert a and b
    rows = store.list_episodes(limit=10)
    assert len(rows) == 2
    assert rows[0]["summary"] == "Confirmed week plan"
    assert rows[0]["source"] == "confirm"
    arelis_only = store.list_episodes(project="arelis")
    assert len(arelis_only) == 1
    assert arelis_only[0]["summary"] == "Shipped typed memory"
    assert store.add_episode("") is None
    assert store.add_episode("x", source="auto") is None
    store.close()


def test_episodes_prompt_line(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    assert episodes_prompt_line(store) == ""
    store.add_episode("First episode")
    store.add_episode("Second episode")
    line = episodes_prompt_line(store, limit=3)
    assert "Recent episodes" in line
    assert "First episode" in line
    assert "Second episode" in line
    store.close()


def test_v6_archive_migrates_to_v7(tmp_path: Path) -> None:
    import sqlite3

    path = tmp_path / "memory.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        PRAGMA user_version = 6;
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
            session_id TEXT,
            key TEXT
        );
        CREATE TABLE embeddings (
            message_id INTEGER PRIMARY KEY,
            model TEXT NOT NULL,
            dims INTEGER NOT NULL,
            vector BLOB NOT NULL
        );
        CREATE TABLE preferences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL UNIQUE,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO preferences (key, value, updated_at)
        VALUES ('units', 'metric', '2026-01-01T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    store = MemoryStore(path)
    assert store.schema_version == SCHEMA_VERSION
    assert store.get_preference("units") == "metric"
    assert store.add_episode("Migrated episode") is not None
    assert store.list_episodes()[0]["summary"] == "Migrated episode"
    store.close()


@pytest.mark.asyncio
async def test_memory_tool_episode_actions(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    tool = MemoryTool(store)

    via_action = await tool.run(
        action="episode",
        summary="Packed the week around Friday demo",
        project="arelis",
    )
    assert via_action.ok
    assert via_action.data["kind"] == "episode"
    assert store.list_episodes()[0]["summary"].startswith("Packed the week")

    via_remember = await tool.run(
        action="remember",
        type="episode",
        fact="Closed the interferometer loop",
    )
    assert via_remember.ok
    summaries = {r["summary"] for r in store.list_episodes()}
    assert "Closed the interferometer loop" in summaries
    store.close()


def test_episode_needs_confirm(tmp_path: Path) -> None:
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    store = MemoryStore(tmp_path / "memory.db")
    registry = build_tool_registry(
        {"tools": {}, "agent": {}}, workspace, memory_store=store
    )
    assert registry.needs_confirm(
        "memory",
        {"action": "episode", "summary": "Ship it"},
    )
    assert registry.needs_confirm(
        "memory",
        {"action": "remember", "type": "episode", "fact": "Ship it"},
    )
    store.close()
