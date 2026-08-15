"""Clipboard read tool — Always Allow; injectable reader for unit tests."""

from __future__ import annotations

import pytest

from arelis.tools import build_tool_registry
from arelis.tools.clipboard import ClipboardTool
from arelis.workspace import WorkspaceRoots


@pytest.mark.asyncio
async def test_clipboard_reads_injected_text() -> None:
    tool = ClipboardTool(reader=lambda: "hello from paste")
    result = await tool.run()
    assert result.ok
    assert "hello from paste" in result.output
    assert result.data.get("chars") == len("hello from paste")


@pytest.mark.asyncio
async def test_clipboard_empty_is_clear() -> None:
    tool = ClipboardTool(reader=lambda: "   ")
    result = await tool.run()
    assert result.ok
    assert "empty" in result.output.lower()
    assert result.data.get("empty") is True


@pytest.mark.asyncio
async def test_clipboard_redacts_secretish_lines() -> None:
    tool = ClipboardTool(reader=lambda: "password=hunter2\nsafe line")
    result = await tool.run()
    assert result.ok
    assert "hunter2" not in result.output
    assert "safe line" in result.output


@pytest.mark.asyncio
async def test_clipboard_truncates() -> None:
    tool = ClipboardTool(reader=lambda: "x" * 5000, max_chars=100)
    result = await tool.run(max_chars=100)
    assert result.ok
    assert result.data.get("truncated") is True
    assert "truncated" in result.output.lower()


def test_clipboard_needs_allow_and_attended_only(tmp_path) -> None:
    workspace = WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "t", "path": str(tmp_path)}]}}
    )
    attended = build_tool_registry(
        {"tools": {"clipboard": {"enabled": True}}, "agent": {}},
        workspace,
        allow_send=True,
        memory_store=None,
    )
    assert "clipboard" in attended.names()
    assert attended.needs_confirm("clipboard", {}, confirm_writes=True)
    assert not attended.needs_confirm("clipboard", {}, confirm_writes=False)
    assert "clipboard" in attended.describe_call("clipboard", {}).lower()

    jobs = build_tool_registry(
        {"tools": {"clipboard": {"enabled": True}}, "agent": {}},
        workspace,
        allow_send=False,
        memory_store=None,
    )
    assert "clipboard" not in jobs.names()


def test_clipboard_capability_is_side_effect() -> None:
    from arelis.tools.base import capability_class

    assert capability_class("clipboard") == "SIDE_EFFECT_LOCAL"
