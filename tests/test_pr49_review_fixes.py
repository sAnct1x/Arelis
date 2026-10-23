"""Tests for the PR #49 flag-off restore: empty workspace write blocks.

PR #49 removed the unconditional empty-content check from
confirm_args_blocked. These tests pin flag-off behavior back, and check
that native mode still allows content="" while blocking missing content.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from arelis.core.turn_confirm import RUN, SKIP, confirm_call
from arelis.core.turn_context import TurnContext
from arelis.tools.base import ToolRegistry, confirm_args_blocked
from arelis.tools.code_workspace import CodeWorkspaceTool
from arelis.workspace import RootEntry, WorkspaceRoots


class MockBus:
    async def publish(self, event: Any) -> None:
        pass


class MockLoop:
    def __init__(self, tools: ToolRegistry | None = None) -> None:
        self.bus = MockBus()
        self.tools = tools or ToolRegistry()
        self.memory = None
        self._trace: list[str] = []
        self._expected_tools: set[str] = set()
        self._look = None
        self._timer = None
        self.confirm_writes = True
        self.confirm_image = True
        self.confirm_send = True
        self.confirm_browser = True
        self.confirm_desktop = True
        self.confirm_vision = True
        self.confirm_run = True
        self.ask_is_grant = True
        self.tools_used: set[str] = set()
        self.request_confirm = AsyncMock(return_value="allow")

    def _tool_message(self, name: str, content: str) -> dict[str, Any]:
        return {"role": "tool", "name": name, "content": content}

    async def _confirm_wait_heartbeat(self, name: str, started: float) -> None:
        await asyncio.sleep(3600)


def _workspace_tools(tmpdir: str) -> ToolRegistry:
    roots = WorkspaceRoots(
        [RootEntry(name="proj", path=Path(tmpdir).resolve())]
    )
    tools = ToolRegistry()
    tools.register(CodeWorkspaceTool(roots))
    return tools


def test_confirm_args_blocked_empty_workspace_write() -> None:
    """Real confirm_args_blocked: content='' is blocked.

    A path that merely contains 'todo' is a real file name, not a
    placeholder token. dest/out/title are destination keys too. A bare
    TODO path, TODO.txt, folder\\TODO.md, and <TODO> still are markers.
    An embedded token in a non-path arg is still a placeholder.
    """
    reason = confirm_args_blocked(
        "workspace",
        {"action": "write", "path": "tmp.txt", "content": ""},
    )
    assert reason is not None
    assert "empty" in reason.lower()

    for path in ("todo.txt", "todo-list.md", "todo_list.py", "todos.md"):
        reason = confirm_args_blocked(
            "workspace",
            {"action": "write", "path": path, "content": "buy milk\n"},
        )
        assert reason is None, path

    for dest_name, dest_args in (
        ("pdf", {"dest": "todo.pdf"}),
        ("diagram", {"out": "todo.png"}),
        ("document", {"title": "Todo list", "format": "pdf"}),
    ):
        reason = confirm_args_blocked(dest_name, dest_args)
        assert reason is None, dest_args

    for path in ("TODO", "TODO.txt", "folder\\TODO.md", "<TODO>"):
        reason = confirm_args_blocked(
            "workspace",
            {"action": "write", "path": path, "content": "buy milk\n"},
        )
        assert reason is not None, path
        assert "placeholder" in reason.lower()

    reason = confirm_args_blocked(
        "workspace",
        {"action": "write", "path": "notes.txt", "content": "TODO: fill in"},
    )
    assert reason is not None
    assert "placeholder" in reason.lower()

    for body in ("TODO", "todo", "<TODO>"):
        reason = confirm_args_blocked(
            "workspace",
            {"action": "write", "path": "notes.txt", "content": body},
        )
        assert reason is not None, body
        assert "placeholder" in reason.lower()


@pytest.mark.asyncio
async def test_confirm_call_flag_on_missing_content_native_blocked() -> None:
    """Flag ON: missing content is blocked by native_arg_problem with guidance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        loop = MockLoop(_workspace_tools(tmpdir))
        ctx = TurnContext(
            agent_cfg={"native_tool_calling": True}, text="", role="fast"
        )
        messages: list[dict[str, Any]] = []

        action, _summary, _fp = await confirm_call(
            loop,
            ctx,
            "workspace",
            {"action": "write", "path": "tmp.txt"},
            text="",
            fail_counts={},
            skip_counts={},
            messages=messages,
            drop_wander=lambda _x: None,
        )

        assert action == SKIP
        assert any("native_blocked" in t for t in loop._trace)
        assert any("content=" in t for t in loop._trace)
        assert not loop.request_confirm.called


def _refusal_text(messages: list[dict[str, Any]]) -> str:
    return " ".join(str(m.get("content") or "") for m in messages)


async def _confirm(
    loop: MockLoop,
    ctx: TurnContext,
    args: dict[str, Any],
    fail_counts: dict[str, int],
    messages: list[dict[str, Any]],
) -> tuple[str, str, str]:
    return await confirm_call(
        loop,
        ctx,
        "workspace",
        args,
        text="Write work/sq.py",
        fail_counts=fail_counts,
        skip_counts={},
        messages=messages,
        drop_wander=lambda _name: None,
    )


@pytest.mark.no_ui
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "empty_args",
    [{'action': 'write', 'path': 'work/sq.py', 'content': ''}, {'action': 'write', 'path': 'work/sq.py', 'content': ' \n\t'}],
)
async def test_empty_write_retry_stays_a_refusal_then_real_content_runs(
    empty_args: dict[str, Any],
) -> None:
    """C05: empty or missing content is a hint, not a failed tool call.

    The first refusal tells the model to pass content=. An identical retry
    gets that same refusal. A later call that actually has a body runs.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        loop = MockLoop(_workspace_tools(tmpdir))
        ctx = TurnContext(agent_cfg={}, text="Write work/sq.py", role="fast")
        fail_counts: dict[str, int] = {}
        messages: list[dict[str, Any]] = []

        action, _, fp = await _confirm(loop, ctx, empty_args, fail_counts, messages)
        assert action == SKIP
        first = _refusal_text(messages)
        assert "empty content" in first.lower()
        assert "failed twice" not in first.lower()
        assert not loop.request_confirm.called

        messages.clear()
        action, _, again = await _confirm(loop, ctx, empty_args, fail_counts, messages)
        assert action == SKIP
        assert again == fp
        second = _refusal_text(messages)
        assert "failed twice" not in second.lower()
        assert second == first
        assert fail_counts.get(fp, 0) == 0
        assert not loop.request_confirm.called
        assert "content=" in first

        messages.clear()
        filled = {
            "action": "write",
            "path": "work/sq.py",
            "content": "print(12 * 12)\n",
        }
        action, _, _filled_fp = await _confirm(loop, ctx, filled, fail_counts, messages)
        assert action == RUN
        assert "failed twice" not in _refusal_text(messages).lower()
        assert loop.request_confirm.called


