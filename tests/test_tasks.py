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
async def test_invalid_priority_fails_and_does_not_coerce(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        result = await tool.run(action="add", title="buy milk", priority="urgent")
        assert not result.ok
        assert "priority" in result.output.lower()
        listed = await tool.run(action="list")
        assert listed.data["tasks"] == []

        added = await tool.run(action="add", title="buy milk")
        bad = await tool.run(
            action="update", id=added.data["id"], priority="urgent"
        )
        assert not bad.ok
        assert store.get_task(added.data["id"])["priority"] == "normal"
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
async def test_unknown_recurrence_fails(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        result = await tool.run(
            action="add",
            title="stretch",
            due="2026-09-18",
            recurrence="FREQ=WEEKLY;BYDAY=MO",
        )
        assert not result.ok
        assert "recurrence" in result.output.lower()
        listed = await tool.run(action="list")
        assert listed.data["tasks"] == []
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


@pytest.mark.asyncio
async def test_parent_done_after_children_are_done(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        parent = await tool.run(action="add", title="ship 0.2.8")
        parent_id = parent.data["id"]
        child = await tool.run(
            action="add", title="write the notes", parent_id=parent_id
        )
        done_child = await tool.run(action="done", id=child.data["id"])
        assert done_child.ok
        result = await tool.run(action="done", id=parent_id)
        assert result.ok, result.output
        assert store.get_task(parent_id)["status"] == "done"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_listing_a_parent_shows_children(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        parent = await tool.run(action="add", title="ship 0.2.8")
        parent_id = parent.data["id"]
        await tool.run(action="add", title="write the notes", parent_id=parent_id)

        listed = await tool.run(action="list")
        assert listed.ok
        assert "ship 0.2.8" in listed.output
        assert "write the notes" in listed.output
        parent_at = listed.output.index("ship 0.2.8")
        child_at = listed.output.index("write the notes")
        assert child_at > parent_at
        kids = [row for row in listed.data["tasks"] if row.get("parent_id") == parent_id]
        assert len(kids) == 1
        assert kids[0]["title"] == "write the notes"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_hostile_title_is_just_a_title(tmp_path: Path) -> None:
    """A path-traversal / SQL payload in title stays a title. Values bind."""
    tool, store = _tool(tmp_path)
    try:
        payloads = (
            "'; DROP TABLE tasks; --",
            "../../etc/passwd",
            '1; DELETE FROM tasks WHERE title != \'',
        )
        ids = []
        for title in payloads:
            added = await tool.run(action="add", title=title)
            assert added.ok, added.output
            ids.append(added.data["id"])

        listed = await tool.run(action="list")
        assert listed.ok
        for title in payloads:
            assert title in listed.output
            matches = [row for row in listed.data["tasks"] if row["title"] == title]
            assert matches, f"title did not survive list: {title!r}"

        still = await tool.run(action="add", title="still here")
        assert still.ok
        assert store.get_task(still.data["id"]) is not None
        assert store.list_tasks(status=None, limit=20)
    finally:
        store.close()
