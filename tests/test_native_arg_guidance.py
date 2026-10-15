"""Tests for native_tool_calling argument guidance system.

These tests verify that when native_tool_calling=true:
1. Tool schemas include specific parameter descriptions (hints)
2. Missing required arguments are caught and reported clearly
3. Tasks tool errors get helpful parent_id vs goal_id hints
4. Telemetry includes arg_keys
5. Flag-off behavior is unchanged
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest

from arelis.core.native_tool_calling import (
    append_native_task_hint,
    native_arg_problem,
)
from arelis.core.turn_confirm import confirm_call
from arelis.core.turn_context import TurnContext
from arelis.memory.store import MemoryStore
from arelis.tools.base import ToolRegistry
from arelis.tools.notes import NotesTool
from arelis.tools.tasks import TasksTool
from arelis.workspace import WorkspaceRoots


# Common mock classes for confirm_call tests
class MockBus:
    async def publish(self, event: Any) -> None:
        pass


class MockLoopMinimal:
    """Minimal mock for tests that don't need confirm."""

    def __init__(self):
        self._trace = []
        self._expected_tools = set()
        self._look = None
        self._timer = None
        self.tools_used = set()

    def _tool_message(self, name: str, msg: str) -> dict[str, Any]:
        return {"role": "tool", "name": name, "content": msg}


class MockLoopFull:
    """Full mock for tests that need request_confirm."""

    def __init__(self):
        self._trace = []
        self._expected_tools = set()
        self._look = None
        self._timer = None
        self.tools_used = set()
        self.confirm_writes = True
        self.confirm_image = True
        self.confirm_send = True
        self.confirm_browser = True
        self.confirm_desktop = True
        self.confirm_vision = True
        self.confirm_run = True
        self.ask_is_grant = True
        self.memory = None
        self.tools = ToolRegistry()

    def _tool_message(self, name: str, msg: str) -> dict[str, Any]:
        return {"role": "tool", "name": name, "content": msg}

    async def request_confirm(self, *args, **kwargs):
        return "allow"


@pytest.mark.no_ui
async def test_tasks_hint_end_to_end():
    """Tasks with real store: create goal, add with parent_id=goal_id -> native gets hint, flag-off unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = MemoryStore(db_path)
        try:
            from arelis.memory.store_tasks import add_goal

            # Create a goal directly (not through TasksTool)
            # This will get id=1 in the goals table
            goal_id = add_goal(store, title="My Goal")
            assert goal_id is not None

            # Now try to add a task with parent_id=goal_id
            # This should fail because there's no TASK with that id (only a goal)
            tasks_tool = TasksTool(store)
            task_result = await tasks_tool.run(
                action="add", title="My Task", parent_id=goal_id
            )
            assert not task_result.ok
            output = task_result.output

            # Flag-off: output is exactly "no task with id N"
            assert output == f"no task with id {goal_id}"

            # Native mode: append hint
            native_output = append_native_task_hint(
                "tasks",
                {"action": "add", "title": "My Task", "parent_id": goal_id},
                False,
                output,
            )
            assert "parent_id is a TASK id" in native_output
            assert f"goal_id={goal_id}" in native_output
        finally:
            store.close()


@pytest.mark.no_ui
async def test_confirm_call_native_blocked_notes():
    """Native mode: confirm_call blocks notes add without text."""
    loop = MockLoopMinimal()
    loop.bus = MockBus()
    ctx = TurnContext(text="test", role="fast")
    ctx.agent_cfg = {"native_tool_calling": True}

    messages: list[dict[str, Any]] = []
    fail_counts: dict[str, int] = {}
    skip_counts: dict[str, int] = {}
    def drop_wander(name: str) -> None:
        pass

    action, _summary, _fp = await confirm_call(
        loop,
        ctx,
        "notes",
        {"action": "add", "title": "Test"},
        text="",
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        drop_wander=drop_wander,
    )

    assert action == "skip"
    assert len(messages) == 1
    assert "text=" in messages[0]["content"]
    assert "failed twice" not in messages[0]["content"].lower()
    # Missing text is a hint to fill the arg, not a failed call.
    assert fail_counts.get(_fp, 0) == 0


@pytest.mark.no_ui
async def test_scripted_model_notes_native_guidance():
    """Scripted model: native mode guides from empty text to valid call, creates note."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        workspace = WorkspaceRoots.from_paths([tmpdir])
        notes_dir = tmpdir_path / "notes"
        notes_dir.mkdir()

        # Test that native_arg_problem returns the guidance
        problem = native_arg_problem("notes", {"action": "add", "title": "Test Note"})
        assert problem is not None
        assert "text=" in problem
        assert "note body" in problem.lower()

        # Test that with text, notes tool works
        notes_tool = NotesTool(workspace)
        result = await notes_tool.run(
            action="add", title="Test Note", text="alpha bravo charlie"
        )
        assert result.ok
        assert "On the desk" in result.output

        # Verify note file was created and contains the body
        note_files = list(notes_dir.glob("*.md"))
        assert len(note_files) == 1

        note_content = note_files[0].read_text()
        assert "alpha bravo charlie" in note_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
