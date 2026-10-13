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
    """Real confirm_args_blocked: content='' is blocked."""
    reason = confirm_args_blocked(
        "workspace",
        {"action": "write", "path": "tmp.txt", "content": ""},
    )
    assert reason is not None
    assert "empty" in reason.lower()


def test_confirm_args_blocked_missing_workspace_write() -> None:
    """Real confirm_args_blocked: missing content is blocked."""
    reason = confirm_args_blocked(
        "workspace",
        {"action": "write", "path": "tmp.txt"},
    )
    assert reason is not None
    assert "empty" in reason.lower()


def test_confirm_args_blocked_whitespace_workspace_write() -> None:
    """Real confirm_args_blocked: whitespace-only content is blocked."""
    reason = confirm_args_blocked(
        "workspace",
        {"action": "write", "path": "tmp.txt", "content": "   \n\t"},
    )
    assert reason is not None
    assert "empty" in reason.lower()


def test_confirm_args_blocked_nonempty_workspace_write() -> None:
    """Real confirm_args_blocked: real content is not blocked."""
    reason = confirm_args_blocked(
        "workspace",
        {"action": "write", "path": "tmp.txt", "content": "hello"},
    )
    assert reason is None


@pytest.mark.asyncio
async def test_confirm_call_flag_off_empty_content_blocked() -> None:
    """Flag OFF: empty workspace write is skipped at confirm, no Allow card."""
    with tempfile.TemporaryDirectory() as tmpdir:
        loop = MockLoop(_workspace_tools(tmpdir))
        ctx = TurnContext(agent_cfg={}, text="", role="fast")
        messages: list[dict[str, Any]] = []

        action, _summary, _fp = await confirm_call(
            loop,
            ctx,
            "workspace",
            {"action": "write", "path": "tmp.txt", "content": ""},
            text="",
            fail_counts={},
            skip_counts={},
            messages=messages,
            tool_names={"workspace"},
            drop_wander=lambda _x: None,
        )

        assert action == SKIP
        assert any("blocked" in t for t in loop._trace)
        assert not loop.request_confirm.called


@pytest.mark.asyncio
async def test_confirm_call_flag_off_missing_content_blocked() -> None:
    """Flag OFF: workspace write without content is skipped at confirm."""
    with tempfile.TemporaryDirectory() as tmpdir:
        loop = MockLoop(_workspace_tools(tmpdir))
        ctx = TurnContext(agent_cfg={}, text="", role="fast")
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
            tool_names={"workspace"},
            drop_wander=lambda _x: None,
        )

        assert action == SKIP
        assert any("blocked" in t for t in loop._trace)
        assert not loop.request_confirm.called


@pytest.mark.asyncio
async def test_confirm_call_flag_on_empty_string_allowed() -> None:
    """Flag ON: content='' reaches Allow (empty file is valid in native mode)."""
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
            {"action": "write", "path": "tmp.txt", "content": ""},
            text="",
            fail_counts={},
            skip_counts={},
            messages=messages,
            tool_names={"workspace"},
            drop_wander=lambda _x: None,
        )

        assert action == RUN
        assert loop.request_confirm.called


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
            tool_names={"workspace"},
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
        tool_names={"workspace"},
        drop_wander=lambda _name: None,
    )


@pytest.mark.no_ui
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "empty_args",
    [
        {"action": "write", "path": "work/sq.py", "content": ""},
        {"action": "write", "path": "work/sq.py", "content": " \n\t"},
        {"action": "write", "path": "work/sq.py"},
    ],
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


@pytest.mark.no_ui
@pytest.mark.asyncio
async def test_native_missing_required_args_do_not_become_failed_twice() -> None:
    """Native mode: missing content or note text is the same hint every retry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        loop = MockLoop(_workspace_tools(tmpdir))
        ctx = TurnContext(
            agent_cfg={"native_tool_calling": True},
            text="Write work/sq.py",
            role="fast",
        )
        fail_counts: dict[str, int] = {}
        missing = {"action": "write", "path": "work/sq.py"}
        messages: list[dict[str, Any]] = []

        action, _, fp = await _confirm(loop, ctx, missing, fail_counts, messages)
        assert action == SKIP
        first = _refusal_text(messages)
        assert "content=" in first
        assert "failed twice" not in first.lower()

        messages.clear()
        action, _, _ = await _confirm(loop, ctx, missing, fail_counts, messages)
        assert action == SKIP
        second = _refusal_text(messages)
        assert "failed twice" not in second.lower()
        assert second == first
        assert fail_counts.get(fp, 0) == 0

        messages.clear()
        notes_fail: dict[str, int] = {}
        notes_messages: list[dict[str, Any]] = []
        for _ in range(3):
            notes_messages.clear()
            action, _, notes_fp = await confirm_call(
                loop,
                ctx,
                "notes",
                {"action": "add", "title": "Test"},
                text="remember this",
                fail_counts=notes_fail,
                skip_counts={},
                messages=notes_messages,
                tool_names={"notes"},
                drop_wander=lambda _name: None,
            )
            assert action == SKIP
            assert "text=" in _refusal_text(notes_messages)
            assert "failed twice" not in _refusal_text(notes_messages).lower()
            assert notes_fail.get(notes_fp, 0) == 0


@pytest.mark.no_ui
@pytest.mark.asyncio
async def test_real_repeated_failure_is_still_blocked() -> None:
    """A call that actually failed twice is still refused. One failure is not."""
    with tempfile.TemporaryDirectory() as tmpdir:
        loop = MockLoop(_workspace_tools(tmpdir))
        ctx = TurnContext(agent_cfg={}, text="Write work/sq.py", role="fast")
        args = {
            "action": "write",
            "path": "work/sq.py",
            "content": "print(12 * 12)\n",
        }
        fail_counts: dict[str, int] = {}
        messages: list[dict[str, Any]] = []

        action, _, fp = await _confirm(loop, ctx, args, fail_counts, messages)
        assert action == RUN

        fail_counts[fp] = 1
        messages.clear()
        loop.request_confirm.reset_mock()
        action, _, _ = await _confirm(loop, ctx, args, fail_counts, messages)
        assert action == RUN
        assert "failed twice" not in _refusal_text(messages).lower()

        fail_counts[fp] = 2
        messages.clear()
        loop.request_confirm.reset_mock()
        action, _, _ = await _confirm(loop, ctx, args, fail_counts, messages)
        assert action == SKIP
        assert "already failed twice" in _refusal_text(messages).lower()
        assert not loop.request_confirm.called
