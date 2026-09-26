"""Priority on the existing goals tool. Same closed set as tasks."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.memory import MemoryStore
from arelis.tools.goals import GoalsTool


def _tool(tmp_path: Path) -> tuple[GoalsTool, MemoryStore]:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    return GoalsTool(store), store


@pytest.mark.asyncio
async def test_priority_survives_list_and_update(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        added = await tool.run(action="add", title="ship 0.2.8", priority="high")
        assert added.ok
        goal_id = added.data["id"]

        listed = await tool.run(action="list")
        assert listed.ok
        assert listed.data["goals"]
        row = listed.data["goals"][0]
        assert "priority" in row, "list must select priority"
        assert row["priority"] == "high"
        assert "high" in listed.output

        updated = await tool.run(action="update", id=goal_id, priority="low")
        assert updated.ok
        again = await tool.run(action="list")
        assert again.data["goals"][0]["priority"] == "low"
        assert "low" in again.output
        assert store.get_goal(goal_id)["priority"] == "low"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_invalid_priority_fails_and_does_not_coerce(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        result = await tool.run(action="add", title="ship 0.2.8", priority="urgent")
        assert not result.ok
        assert "priority" in result.output.lower()
        listed = await tool.run(action="list")
        assert listed.data["goals"] == []

        added = await tool.run(action="add", title="ship 0.2.8")
        bad = await tool.run(
            action="update", id=added.data["id"], priority="urgent"
        )
        assert not bad.ok
        assert store.get_goal(added.data["id"])["priority"] == "normal"
    finally:
        store.close()


@pytest.mark.asyncio
async def test_default_priority_is_normal(tmp_path: Path) -> None:
    tool, store = _tool(tmp_path)
    try:
        added = await tool.run(action="add", title="keep the lights on")
        assert added.ok
        row = store.get_goal(added.data["id"])
        assert row["priority"] == "normal"
        listed = await tool.run(action="list")
        assert listed.data["goals"][0]["priority"] == "normal"
        assert "normal" in listed.output
    finally:
        store.close()
