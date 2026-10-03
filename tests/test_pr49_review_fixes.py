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
