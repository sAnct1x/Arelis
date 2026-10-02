"""Tests for native_tool_calling argument guidance system.

These tests verify that when native_tool_calling=true:
1. Tool schemas include specific parameter descriptions (hints)
2. Missing required arguments are caught and reported clearly
3. Tasks tool errors get helpful parent_id vs goal_id hints
4. Telemetry includes arg_keys
5. Flag-off behavior is unchanged
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from arelis.core.compact_prompt import skinny_ollama_tool
from arelis.core.native_tool_calling import (
    NATIVE_PARAM_HINTS,
    append_native_task_hint,
    native_arg_problem,
    native_tool_calling,
)
from arelis.core.turn_confirm import confirm_call
from arelis.core.turn_context import TurnContext
from arelis.memory.store import MemoryStore
from arelis.tools.base import ToolRegistry
from arelis.tools.code_workspace import CodeWorkspaceTool
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

    def _tool_message(self, name: str, msg: str) -> dict[str, Any]:
        return {"role": "tool", "name": name, "content": msg}


class MockLoopFull:
    """Full mock for tests that need request_confirm."""

    def __init__(self):
        self._trace = []
        self._expected_tools = set()
        self._look = None
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
def test_flag_on_false():
    """Verify native_tool_calling returns false when flag is off or missing."""
    assert not native_tool_calling(None)
    assert not native_tool_calling({})
    assert not native_tool_calling({"native_tool_calling": False})


@pytest.mark.no_ui
def test_flag_on_true():
    """Verify native_tool_calling returns true when flag is explicitly true."""
    assert native_tool_calling({"native_tool_calling": True})


@pytest.mark.no_ui
def test_flag_off_schema_unchanged():
    """Flag-off: tool schema is byte-identical to committed baseline from main."""
    fixture_path = Path(__file__).parent / "fixtures" / "tool_schema_baseline.json"
    with open(fixture_path) as f:
        baseline = json.load(f)

    registry = ToolRegistry()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Register notes tool
        workspace = WorkspaceRoots.from_paths([tmpdir])
        notes_tool = NotesTool(workspace)
        registry.register(notes_tool)

        # Register workspace tool
        workspace_tool = CodeWorkspaceTool([tmpdir])
        registry.register(workspace_tool)

        # Register tasks tool
        db_path = tmpdir_path / "test.db"
        store = MemoryStore(db_path)
        try:
            tasks_tool = TasksTool(store)
            registry.register(tasks_tool)

            # Get schemas with param_hints=False (flag off)
            schemas = registry.ollama_tools(
                names={"notes", "workspace", "tasks"}, param_hints=False
            )

            # Verify byte-identical to baseline
            assert json.dumps(schemas, sort_keys=True) == json.dumps(
                baseline, sort_keys=True
            ), "Flag-off schema changed from baseline"

            # Verify no descriptions in parameters
            for schema in schemas:
                params = schema.get("function", {}).get("parameters", {})
                props = params.get("properties", {})
                for prop_name, prop_spec in props.items():
                    assert "description" not in prop_spec, (
                        f"Flag-off schema has description for {prop_name}"
                    )
        finally:
            store.close()


@pytest.mark.no_ui
def test_flag_on_param_hints_notes():
    """Flag-on: notes.text has description, aliases removed, structure unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = WorkspaceRoots.from_paths([tmpdir])
        notes_tool = NotesTool(workspace)

        # Use real schema
        notes_off = skinny_ollama_tool(
            notes_tool.name,
            notes_tool.description,
            notes_tool.parameters_schema,
            param_hints=False,
        )
        notes_on = skinny_ollama_tool(
            notes_tool.name,
            notes_tool.description,
            notes_tool.parameters_schema,
            param_hints=True,
        )

        # Verify flag-off has no descriptions
        notes_off_props = notes_off["function"]["parameters"]["properties"]
        for prop in notes_off_props.values():
            assert "description" not in prop

        # Verify flag-on has specific descriptions
        notes_on_props = notes_on["function"]["parameters"]["properties"]

        # Should have text with description
        assert "text" in notes_on_props
        assert (
            notes_on_props["text"].get("description")
            == NATIVE_PARAM_HINTS[("notes", "text")]
        )

        # Should NOT have content/body aliases
        assert "content" not in notes_on_props
        assert "body" not in notes_on_props

        # Other props should not have descriptions
        for prop_name, prop_spec in notes_on_props.items():
            if prop_name == "text":
                continue
            assert "description" not in prop_spec, f"Unexpected description in {prop_name}"

        # Required and tool name unchanged
        assert (
            notes_off["function"]["parameters"]["required"]
            == notes_on["function"]["parameters"]["required"]
        )
        assert notes_off["function"]["name"] == notes_on["function"]["name"]


@pytest.mark.no_ui
def test_flag_on_param_hints_workspace():
    """Flag-on: workspace.content has description, structure unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_tool = CodeWorkspaceTool([tmpdir])

        # Use real schema
        ws_off = skinny_ollama_tool(
            workspace_tool.name,
            workspace_tool.description,
            workspace_tool.parameters_schema,
            param_hints=False,
        )
        ws_on = skinny_ollama_tool(
            workspace_tool.name,
            workspace_tool.description,
            workspace_tool.parameters_schema,
            param_hints=True,
        )

        ws_off_props = ws_off["function"]["parameters"]["properties"]
        ws_on_props = ws_on["function"]["parameters"]["properties"]

        # Flag-off: no descriptions
        for prop in ws_off_props.values():
            assert "description" not in prop

        # Flag-on: content has description
        assert "content" in ws_on_props
        assert (
            ws_on_props["content"].get("description")
            == NATIVE_PARAM_HINTS[("workspace", "content")]
        )

        # Other props should not have descriptions
        for prop_name, prop_spec in ws_on_props.items():
            if prop_name == "content":
                continue
            assert "description" not in prop_spec

        # Property count, required unchanged
        assert len(ws_off_props) == len(ws_on_props)
        assert (
            ws_off["function"]["parameters"]["required"]
            == ws_on["function"]["parameters"]["required"]
        )


@pytest.mark.no_ui
def test_flag_on_param_hints_tasks():
    """Flag-on: tasks.goal_id and tasks.parent_id have descriptions, structure unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = MemoryStore(db_path)
        try:
            tasks_tool = TasksTool(store)

            # Use real schema
            tasks_off = skinny_ollama_tool(
                tasks_tool.name,
                tasks_tool.description,
                tasks_tool.parameters_schema,
                param_hints=False,
            )
            tasks_on = skinny_ollama_tool(
                tasks_tool.name,
                tasks_tool.description,
                tasks_tool.parameters_schema,
                param_hints=True,
            )

            tasks_off_props = tasks_off["function"]["parameters"]["properties"]
            tasks_on_props = tasks_on["function"]["parameters"]["properties"]

            # Flag-off: no descriptions
            for prop in tasks_off_props.values():
                assert "description" not in prop

            # Flag-on: goal_id and parent_id have descriptions
            assert "goal_id" in tasks_on_props
            assert (
                tasks_on_props["goal_id"].get("description")
                == NATIVE_PARAM_HINTS[("tasks", "goal_id")]
            )

            assert "parent_id" in tasks_on_props
            assert (
                tasks_on_props["parent_id"].get("description")
                == NATIVE_PARAM_HINTS[("tasks", "parent_id")]
            )

            # Other props should not have descriptions
            for prop_name, prop_spec in tasks_on_props.items():
                if prop_name in ("goal_id", "parent_id"):
                    continue
                assert "description" not in prop_spec

            # Property count, required unchanged
            assert len(tasks_off_props) == len(tasks_on_props)
            assert (
                tasks_off["function"]["parameters"]["required"]
                == tasks_on["function"]["parameters"]["required"]
            )
        finally:
            store.close()


@pytest.mark.no_ui
def test_native_arg_problem_notes_missing_text():
    """Native mode: notes add without text returns blocking message."""
    # Missing text
    problem = native_arg_problem("notes", {"action": "add", "title": "Test"})
    assert problem is not None
    assert "text=" in problem
    assert "note body" in problem.lower()

    # Empty text
    problem = native_arg_problem("notes", {"action": "add", "text": ""})
    assert problem is not None

    # Whitespace-only text
    problem = native_arg_problem("notes", {"action": "add", "text": "   "})
    assert problem is not None

    # Valid text
    problem = native_arg_problem("notes", {"action": "add", "text": "Valid content"})
    assert problem is None

    # Valid content alias
    problem = native_arg_problem("notes", {"action": "add", "content": "Valid"})
    assert problem is None

    # Valid fact alias
    problem = native_arg_problem("notes", {"action": "add", "fact": "Valid"})
    assert problem is None

    # Not add action
    problem = native_arg_problem("notes", {"action": "list"})
    assert problem is None


@pytest.mark.no_ui
def test_native_arg_problem_workspace_missing_content():
    """Native mode: workspace write without content (None) returns blocking message."""
    # Missing content (None)
    problem = native_arg_problem("workspace", {"action": "write", "path": "test.txt"})
    assert problem is not None
    assert "content=" in problem
    assert "file text" in problem.lower()

    # Empty string content is VALID (empty file)
    problem = native_arg_problem(
        "workspace", {"action": "write", "path": "test.txt", "content": ""}
    )
    assert problem is None, "Empty string content should be allowed for empty files"

    # Valid content
    problem = native_arg_problem(
        "workspace", {"action": "write", "path": "test.txt", "content": "Hello"}
    )
    assert problem is None

    # Not write action
    problem = native_arg_problem("workspace", {"action": "read", "path": "test.txt"})
    assert problem is None


@pytest.mark.no_ui
def test_native_arg_problem_other_tools():
    """Native mode: other tools return None (no special handling)."""
    assert native_arg_problem("weather", {"place": "NYC"}) is None
    assert native_arg_problem("calculator", {"expression": "2+2"}) is None
    assert native_arg_problem("unknown_tool", {"foo": "bar"}) is None


@pytest.mark.no_ui
def test_append_native_task_hint_parent_id_error():
    """Native mode: tasks add with parent_id error gets hint."""
    args = {"action": "add", "title": "Subtask", "parent_id": 42}
    output = "no task with id 42"

    result = append_native_task_hint("tasks", args, False, output)

    assert "parent_id is a TASK id" in result
    assert "goal_id=42" in result


@pytest.mark.no_ui
def test_append_native_task_hint_no_hint_when_ok():
    """Native mode: no hint appended when task call succeeds."""
    args = {"action": "add", "title": "Task", "parent_id": 42}
    output = "Task created"

    result = append_native_task_hint("tasks", args, True, output)

    assert result == output
    assert "parent_id" not in result


@pytest.mark.no_ui
def test_append_native_task_hint_no_hint_wrong_action():
    """Native mode: no hint for non-add actions."""
    args = {"action": "list", "parent_id": 42}
    output = "no task with id 42"

    result = append_native_task_hint("tasks", args, False, output)

    assert result == output
    assert "goal_id" not in result


@pytest.mark.no_ui
def test_append_native_task_hint_no_hint_when_goal_id_present():
    """Native mode: no hint when goal_id was already provided."""
    args = {"action": "add", "title": "Task", "parent_id": 42, "goal_id": 1}
    output = "no task with id 42"

    result = append_native_task_hint("tasks", args, False, output)

    assert result == output
    assert "parent_id is a TASK id" not in result


@pytest.mark.no_ui
def test_append_native_task_hint_no_hint_different_error():
    """Native mode: no hint for different error messages."""
    args = {"action": "add", "title": "Task", "parent_id": 42}
    output = "Database error"

    result = append_native_task_hint("tasks", args, False, output)

    assert result == output


@pytest.mark.no_ui
async def test_tasks_hint_end_to_end():
    """Tasks with real store: create goal, add with parent_id -> native gets hint, flag-off unchanged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = MemoryStore(db_path)
        try:
            tasks_tool = TasksTool(store)

            # Create a goal
            goal_result = await tasks_tool.run(action="add", title="My Goal")
            assert goal_result.ok
            goal_id = goal_result.data["id"]

            # Try to add task with parent_id=goal_id (wrong, should be goal_id=goal_id)
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
def test_telemetry_arg_keys():
    """Telemetry: arg_keys present with native on, absent with off."""
    from arelis.core.turn_telemetry import TurnTimer

    # Flag-on: arg_keys should be added
    timer_on = TurnTimer(
        source="test", role="fast", speak=False, user_chars=10, enabled=True
    )
    timer_on.mark(
        "tool",
        name="notes",
        ms=100,
        ok=True,
        action="add",
        arg_keys=["action", "text", "title"],
    )

    assert len(timer_on.tool_records) == 1
    record = timer_on.tool_records[0]
    assert "arg_keys" in record
    assert record["arg_keys"] == ["action", "text", "title"]

    # Flag-off: arg_keys not passed, should not be in record
    timer_off = TurnTimer(
        source="test", role="fast", speak=False, user_chars=10, enabled=True
    )
    timer_off.mark("tool", name="notes", ms=100, ok=True, action="add")

    assert len(timer_off.tool_records) == 1
    record_off = timer_off.tool_records[0]
    assert "arg_keys" not in record_off


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
    tool_names = {"notes"}

    def drop_wander(name: str) -> None:
        pass

    action, _summary, fp = await confirm_call(
        loop,
        ctx,
        "notes",
        {"action": "add", "title": "Test"},
        text="",
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        tool_names=tool_names,
        drop_wander=drop_wander,
    )

    assert action == "skip"
    assert len(messages) == 1
    assert "text=" in messages[0]["content"]
    assert fail_counts[fp] == 1


@pytest.mark.no_ui
async def test_confirm_call_native_blocked_workspace():
    """Native mode: confirm_call blocks workspace write without content."""
    loop = MockLoopMinimal()
    loop.bus = MockBus()
    ctx = TurnContext(text="test", role="fast")
    ctx.agent_cfg = {"native_tool_calling": True}

    messages: list[dict[str, Any]] = []
    fail_counts: dict[str, int] = {}
    skip_counts: dict[str, int] = {}
    tool_names = {"workspace"}

    def drop_wander(name: str) -> None:
        pass

    action, _summary, _fp = await confirm_call(
        loop,
        ctx,
        "workspace",
        {"action": "write", "path": "test.txt"},
        text="",
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        tool_names=tool_names,
        drop_wander=drop_wander,
    )

    assert action == "skip"
    assert len(messages) == 1
    assert "content=" in messages[0]["content"]


@pytest.mark.no_ui
async def test_confirm_call_flag_off_notes_reaches_confirm():
    """Flag-off: notes add without text reaches request_confirm (not blocked at native level)."""
    confirm_called = False

    loop = MockLoopFull()

    # Override request_confirm to track if it's called
    original_request_confirm = loop.request_confirm

    async def tracking_request_confirm(*args, **kwargs):
        nonlocal confirm_called
        confirm_called = True
        return await original_request_confirm(*args, **kwargs)

    loop.request_confirm = tracking_request_confirm
    loop.bus = MockBus()
    ctx = TurnContext(text="test", role="fast")
    ctx.agent_cfg = {}  # Flag off
    ctx.allow_writes_this_turn = False

    messages: list[dict[str, Any]] = []
    fail_counts: dict[str, int] = {}
    skip_counts: dict[str, int] = {}
    tool_names = {"notes"}

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
        tool_names=tool_names,
        drop_wander=drop_wander,
    )

    # Should reach request_confirm
    assert confirm_called, "Flag-off should reach request_confirm"
    assert action == "run"


@pytest.mark.no_ui
async def test_confirm_call_flag_off_workspace_reaches_confirm():
    """Flag-off: workspace write reaches request_confirm."""
    confirm_called = False

    loop = MockLoopFull()

    # Override request_confirm to track if it's called
    original_request_confirm = loop.request_confirm

    async def tracking_request_confirm(*args, **kwargs):
        nonlocal confirm_called
        confirm_called = True
        return await original_request_confirm(*args, **kwargs)

    loop.request_confirm = tracking_request_confirm
    loop.bus = MockBus()
    ctx = TurnContext(text="test", role="fast")
    ctx.agent_cfg = {}
    ctx.allow_writes_this_turn = False

    messages: list[dict[str, Any]] = []
    fail_counts: dict[str, int] = {}
    skip_counts: dict[str, int] = {}
    tool_names = {"workspace"}

    def drop_wander(name: str) -> None:
        pass

    action, _summary, _fp = await confirm_call(
        loop,
        ctx,
        "workspace",
        {"action": "write", "path": "test.txt", "content": "hello"},
        text="",
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        tool_names=tool_names,
        drop_wander=drop_wander,
    )

    assert confirm_called
    assert action == "run"


@pytest.mark.no_ui
async def test_confirm_call_repeat_fail():
    """Native mode: repeat failures (fail_counts >= 2) trigger skip_repeat_fail."""
    loop = MockLoopMinimal()
    loop.bus = MockBus()
    ctx = TurnContext(text="test", role="fast")
    ctx.agent_cfg = {"native_tool_calling": True}

    messages: list[dict[str, Any]] = []
    fail_counts: dict[str, int] = {}
    skip_counts: dict[str, int] = {}
    tool_names = {"notes"}

    def drop_wander(name: str) -> None:
        pass

    # First call
    action1, _, fp = await confirm_call(
        loop,
        ctx,
        "notes",
        {"action": "add", "title": "Test"},
        text="",
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        tool_names=tool_names,
        drop_wander=drop_wander,
    )
    assert action1 == "skip"
    assert fail_counts[fp] == 1

    # Second call with same args
    messages.clear()
    action2, _, _ = await confirm_call(
        loop,
        ctx,
        "notes",
        {"action": "add", "title": "Test"},
        text="",
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        tool_names=tool_names,
        drop_wander=drop_wander,
    )
    assert action2 == "skip"
    assert fail_counts[fp] == 2

    # Third call should trigger skip_repeat_fail
    messages.clear()
    action3, _, _ = await confirm_call(
        loop,
        ctx,
        "notes",
        {"action": "add", "title": "Test"},
        text="",
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        tool_names=tool_names,
        drop_wander=drop_wander,
    )
    assert action3 == "skip"
    # Message should mention "already failed twice"
    assert any("already failed twice" in str(m.get("content", "")) for m in messages)


@pytest.mark.no_ui
async def test_confirm_call_unrelated_tools_unchanged():
    """Native mode: unrelated tools (weather, calculator) are not affected."""
    loop = MockLoopFull()
    loop.bus = MockBus()
    ctx = TurnContext(text="test", role="fast")
    ctx.agent_cfg = {"native_tool_calling": True}

    messages: list[dict[str, Any]] = []
    fail_counts: dict[str, int] = {}
    skip_counts: dict[str, int] = {}

    def drop_wander(name: str) -> None:
        pass

    # Weather tool should not be blocked
    action, _, _ = await confirm_call(
        loop,
        ctx,
        "weather",
        {"place": "NYC"},
        text="",
        fail_counts=fail_counts,
        skip_counts=skip_counts,
        messages=messages,
        tool_names={"weather"},
        drop_wander=drop_wander,
    )
    assert action == "run"
    assert len(messages) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
