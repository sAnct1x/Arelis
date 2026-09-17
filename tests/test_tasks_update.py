"""Fixing a typo on a to-do should not mean deleting it and typing it again.

`tasks` shipped with add / done / reopen / remove / attach / detach and no
update. Correcting a title or moving a due date meant `remove` then `add`,
which loses the id, the created_at, and any goal link, and reads to the user
like she deleted their task.

`remove` is also the one destructive verb in this tool, so the workaround
routed a routine correction through the most dangerous action available.

update is a write: it goes in TASKS_WRITE_ACTIONS and raises the confirm card
like add and remove do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.memory import MemoryStore
from arelis.tools.policy import TASKS_WRITE_ACTIONS, action_is_write
from arelis.tools.tasks import TasksTool


def _tool(tmp_path: Path) -> tuple[TasksTool, MemoryStore]:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    return TasksTool(store), store


def test_update_is_gated_like_every_other_task_write() -> None:
    assert "update" in TASKS_WRITE_ACTIONS
    assert action_is_write("tasks", {"action": "update"}) is True
    assert action_is_write("tasks", {"action": "list"}) is False


@pytest.mark.asyncio
async def test_a_typo_can_be_fixed_in_place(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        added = await tool.run(action="add", title="by milk")
        task_id = added.data["id"]

        result = await tool.run(action="update", id=task_id, title="buy milk")
        assert result.ok

        listed = await tool.run(action="list")
        assert "buy milk" in listed.output
        assert "by milk" not in listed.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_the_task_keeps_its_identity_through_an_edit(tmp_path: Path) -> None:
    """The reason update exists instead of remove+add."""
    tool, store = _tool(tmp_path)
    try:
        goal_id = store.add_goal("ship 0.2.8")
        added = await tool.run(action="add", title="by milk", goal_id=goal_id)
        task_id = added.data["id"]

        await tool.run(action="update", id=task_id, title="buy milk")

        row = store.get_task(task_id)
        assert row is not None, "the id must survive an edit"
        assert row["title"] == "buy milk"
        assert row["goal_id"] == goal_id, "the goal link must survive an edit"
        assert row["status"] == "open"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_a_due_date_can_be_moved(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        added = await tool.run(action="add", title="file taxes", due="2026-04-15")
        task_id = added.data["id"]

        await tool.run(action="update", id=task_id, due="2026-10-15")

        row = store.get_task(task_id)
        assert row is not None
        assert row["due"] == "2026-10-15"
        assert row["title"] == "file taxes", "moving a date must not touch the title"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_a_due_date_can_be_cleared(tmp_path: Path) -> None:
    """Empty string means drop it. Omitting the field means leave it alone."""
    tool, store = _tool(tmp_path)
    try:
        added = await tool.run(action="add", title="file taxes", due="2026-04-15")
        task_id = added.data["id"]

        await tool.run(action="update", id=task_id, due="")

        row = store.get_task(task_id)
        assert row is not None
        assert not row["due"]
    finally:
        store.close()


@pytest.mark.asyncio
async def test_updating_nothing_is_refused_rather_than_silently_passing(
    tmp_path: Path,
) -> None:
    """An ok=True that changed nothing is how she ends up claiming a fix she never made."""
    tool, store = _tool(tmp_path)
    try:
        added = await tool.run(action="add", title="buy milk")
        result = await tool.run(action="update", id=added.data["id"])
        assert not result.ok
        assert "title" in result.output.lower() or "due" in result.output.lower()
    finally:
        store.close()


@pytest.mark.asyncio
async def test_updating_a_task_that_is_not_there_says_so(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        result = await tool.run(action="update", id=9999, title="buy milk")
        assert not result.ok
        assert "9999" in result.output
    finally:
        store.close()


@pytest.mark.asyncio
async def test_update_needs_an_id(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        result = await tool.run(action="update", title="buy milk")
        assert not result.ok
        assert "id" in result.output.lower()
    finally:
        store.close()
