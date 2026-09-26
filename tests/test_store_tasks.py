"""v9-era archives must gain the 4.10 columns without losing old rows."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from arelis.memory import MemoryStore
from arelis.memory.store import SCHEMA_VERSION
from arelis.tools.tasks import TasksTool


def _write_v9_fixture(path: Path) -> None:
    """A memory.db that stopped at goal_id. No priority/recurrence/parent_id."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                title TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                due TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                source TEXT NOT NULL,
                goal_id INTEGER
            );
            CREATE TABLE goals (
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
            INSERT INTO goals
                (title, kind, status, created_at, updated_at, source)
            VALUES
                ('old goal', 'goal', 'active',
                 '2026-01-01T00:00:00', '2026-01-01T00:00:00', 'explicit');
            INSERT INTO tasks
                (title, status, due, created_at, updated_at, source, goal_id)
            VALUES
                ('old chore', 'open', '2026-06-01',
                 '2026-01-01T00:00:00', '2026-01-01T00:00:00', 'explicit', 1);
            PRAGMA user_version = 9;
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_v9_db_gains_columns_and_existing_rows_default(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    _write_v9_fixture(path)

    probe = sqlite3.connect(path)
    try:
        assert int(probe.execute("PRAGMA user_version").fetchone()[0]) == 9
        task_cols = {
            str(row[1]) for row in probe.execute("PRAGMA table_info(tasks)")
        }
        assert "priority" not in task_cols
        assert "recurrence" not in task_cols
        assert "parent_id" not in task_cols
    finally:
        probe.close()

    store = MemoryStore(path)
    try:
        assert store.schema_version == SCHEMA_VERSION
        task_cols = {
            str(row[1])
            for row in store._conn.execute("PRAGMA table_info(tasks)")
        }
        goal_cols = {
            str(row[1])
            for row in store._conn.execute("PRAGMA table_info(goals)")
        }
        assert "priority" in task_cols
        assert "recurrence" in task_cols
        assert "parent_id" in task_cols
        assert "priority" in goal_cols

        row = store.get_task(1)
        assert row is not None
        assert row["title"] == "old chore"
        assert row["goal_id"] == 1
        assert row["priority"] == "normal"
        assert row["recurrence"] is None
        assert row["parent_id"] is None

        goal = store.get_goal(1)
        assert goal is not None
        assert goal["title"] == "old goal"
        assert goal["priority"] == "normal"

        listed = store.list_tasks(status="open")
        assert listed[0]["priority"] == "normal"
        assert "priority" in listed[0]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_migrated_row_is_usable_from_the_tool(tmp_path: Path) -> None:
    path = tmp_path / "memory.db"
    _write_v9_fixture(path)
    store = MemoryStore(path)
    tool = TasksTool(store)
    try:
        listed = await tool.run(action="list")
        assert listed.ok
        assert listed.data["tasks"][0]["priority"] == "normal"
        assert "old chore" in listed.output
        bumped = await tool.run(
            action="update", id=1, priority="high", recurrence="weekly",
            due="2026-09-18",
        )
        assert bumped.ok, bumped.output
        done = await tool.run(action="done", id=1)
        assert done.ok, done.output
        row = store.get_task(1)
        assert row["status"] == "open"
        assert row["due"] == "2026-09-25"
        assert row["goal_id"] == 1
    finally:
        store.close()
