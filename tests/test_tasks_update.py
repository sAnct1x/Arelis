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


