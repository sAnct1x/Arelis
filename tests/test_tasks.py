"""Priority, recurrence, and subtasks on the existing tasks tool.

4.10 is not a second to-do system. The update/goal_id path already
existed; these fields hang off that row. Drive TasksTool.run — a store
helper that looks right while list drops the column is the bug.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from arelis.memory import MemoryStore
from arelis.tools.tasks import TasksTool


def _tool(tmp_path: Path) -> tuple[TasksTool, MemoryStore]:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    return TasksTool(store), store


@pytest.mark.asyncio
async def test_priority_survives_list_and_update(tmp_path: Path) -> None:
    """Mutant: list SELECT omits priority — data and formatter both miss it."""
    tool, store = _tool(tmp_path)
    try:
        added = await tool.run(action="add", title="buy milk", priority="high")
        assert added.ok
        task_id = added.data["id"]

        listed = await tool.run(action="list")
        assert listed.ok
        assert listed.data["tasks"], "list returned no rows"
        row = listed.data["tasks"][0]
        assert "priority" in row, "list must select priority"
        assert row["priority"] == "high"
        assert "high" in listed.output

        updated = await tool.run(action="update", id=task_id, priority="low")
        assert updated.ok
        again = await tool.run(action="list")
        assert again.data["tasks"][0]["priority"] == "low"
        assert "low" in again.output
        assert store.get_task(task_id)["priority"] == "low"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_weekly_done_advances_due_and_keeps_id_and_goal(
    tmp_path: Path,
) -> None:
    """Mutant: done only flips status and leaves due alone.

    remove+add is how 4.0 lost the id and the goal link. Recurrence has
    to keep the same row.
    """
    tool, store = _tool(tmp_path)
    try:
        today = date(2026, 9, 18)
        goal_id = store.add_goal("keep the kitchen")
        added = await tool.run(
            action="add",
            title="take out trash",
            due=today.isoformat(),
            recurrence="weekly",
            goal_id=goal_id,
            priority="high",
        )
        assert added.ok
        task_id = added.data["id"]

        result = await tool.run(action="done", id=task_id)
        assert result.ok, result.output

        row = store.get_task(task_id)
        assert row is not None, "the id must survive a recurring done"
        assert row["id"] == task_id
        assert row["goal_id"] == goal_id
        assert row["status"] == "open"
        assert row["due"] == (today + timedelta(days=7)).isoformat()
        assert row["recurrence"] == "weekly"
        assert row["priority"] == "high"
        assert row["title"] == "take out trash"
        assert result.data["id"] == task_id
        assert result.data["goal_id"] == goal_id
        assert "2026-09-25" in result.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_parent_done_fails_while_a_child_is_open(tmp_path: Path) -> None:
    """Mutant: parent done ignores open children."""
    tool, store = _tool(tmp_path)
    try:
        parent = await tool.run(action="add", title="ship 0.2.8")
        parent_id = parent.data["id"]
        child = await tool.run(
            action="add", title="write the notes", parent_id=parent_id
        )
        assert child.ok
        assert child.data["parent_id"] == parent_id

        result = await tool.run(action="done", id=parent_id)
        assert not result.ok
        assert "subtask" in result.output.lower()
        assert store.get_task(parent_id)["status"] == "open"
        assert store.get_task(child.data["id"])["status"] == "open"
    finally:
        store.close()


