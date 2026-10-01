"""Regression tests for browser shortcut bug (2026-10-01).

Bug 1 (browser): browser_open_done_reply shortcut was ending turns too early
when the user asked to both open AND read/screenshot a page. Items S55, S56,
P01, P02, C25, P11 all failed because the loop ended with "The page is open."
after the first browser tool call, before executing a second call to read or
screenshot.
"""

from __future__ import annotations

import asyncio

from arelis.config import shipped_num_ctx
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.eval.harness import _ScriptedRouter
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.document import DocumentTool


class _StubBrowserTool:
    """Stub browser that returns ok for open, read, and screenshot."""

    def __init__(self) -> None:
        self.name = "browser"
        self.description = "Stub browser for testing."
        self.risk = "read"
        self.calls: list[dict] = []
        self.parameters_schema = {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "url": {"type": "string"},
            },
        }

    async def run(self, **kwargs) -> ToolResult:
        self.calls.append(dict(kwargs))
        action = str(kwargs.get("action", "open")).lower()
        url = str(kwargs.get("url", ""))

        if action == "open":
            return ToolResult(
                ok=True,
                output=f"Opened {url} title: Example Domain",
                data={"action": "open", "url": url, "title": "Example Domain"},
            )
        elif action == "read":
            return ToolResult(
                ok=True,
                output="Example Domain\nThis domain is for use in illustrative examples.",
                data={"action": "read", "text": "Example Domain heading"},
            )
        elif action == "screenshot":
            return ToolResult(
                ok=True,
                output="Screenshot saved to outputs/images/screenshot_001.png",
                data={"action": "screenshot", "path": "outputs/images/screenshot_001.png"},
            )
        return ToolResult(ok=False, output="Unknown action")


def _tools_registry() -> ToolRegistry:
    """Registry with stub browser and real document tool."""
    reg = ToolRegistry()
    reg.register(_StubBrowserTool())
    reg.register(DocumentTool())
    return reg


async def _allow(*_args, **_kwargs) -> str:
    """request_confirm is awaited by the loop, so it must be a coroutine."""
    return "allow"


async def _run_agent_with_script(
    text: str,
    script: list[list[tuple[str, any]]],
    agent_cfg: dict | None = None,
) -> tuple[str, list[tuple[str, bool]], list[str]]:
    """Run agent loop with script and return final answer, tool results, and tool names."""
    router = _ScriptedRouter(script)
    tools = _tools_registry()
    bus = EventBus()
    memory = SessionMemory()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    for et in (EventType.TOOL_START, EventType.TOOL_RESULT, EventType.ASSISTANT_DONE):
        bus.subscribe(et, capture)

    if agent_cfg is None:
        agent_cfg = {
            "max_rounds": 6,
            "exactness": True,
            "numeric_gate": True,
            "evidence_gate": True,
        }

    loop = AgentLoop(
        bus,
        router,
        tools,
        memory,
        persona="You are Arelis under eval.",
        config={
            "agent": agent_cfg,
            "ollama": {"num_ctx": shipped_num_ctx()},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )

    bus_task = asyncio.create_task(bus.run())
    try:
        await loop.run(text, "fast", source="eval")
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass

    tool_results = [
        (e.payload.get("tool", "?"), e.payload.get("ok", False))
        for e in events
        if e.type == EventType.TOOL_RESULT
    ]
    tool_names = [t[0] for t in tool_results]
    done = next((e for e in events if e.type == EventType.ASSISTANT_DONE), None)
    final_text = str((done.payload.get("text") if done else "") or "")

    return final_text, tool_results, tool_names


def test_browser_open_and_read_runs_both() -> None:
    """Browser open then read should run both calls (S55 bug).

    Matrix item S55 failed: browser open succeeded, but the shortcut
    ended the turn with "The page is open." before the read action.
    """
    script = [
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "browser",
                            "arguments": {"action": "open", "url": "https://example.com"},
                        },
                    }
                ],
            )
        ],
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "browser",
                            "arguments": {"action": "read"},
                        },
                    }
                ],
            )
        ],
        [("token", "The page heading is Example Domain.")],
    ]

    final_text, tool_results, tool_names = asyncio.run(
        _run_agent_with_script(
            "Use the browser to open https://example.com and tell me the heading on the page.",
            script,
        )
    )

    assert len(tool_results) >= 2, f"Expected at least 2 tool calls, got {len(tool_results)}: {tool_results}"
    assert "browser" in tool_names, f"Expected browser tool, got {tool_names}"
    assert tool_names.count("browser") >= 2, f"Expected 2+ browser calls, got {tool_names}"

    assert "the page is open" not in final_text.lower(), f"Got shortcut reply: {final_text}"
    assert "example domain" in final_text.lower(), f"Missing page content in: {final_text}"


def test_browser_open_and_screenshot_runs_both() -> None:
    """Browser open then screenshot should run both calls (S56 bug).

    Matrix item S56 failed: browser open succeeded, but the shortcut
    ended the turn before taking the screenshot. PR #37 fixed the
    turn_dispatch shortcut but missed the turn_execute errand check.
    """
    script = [
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "browser",
                            "arguments": {"action": "open", "url": "https://example.com"},
                        },
                    }
                ],
            )
        ],
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "browser",
                            "arguments": {"action": "screenshot"},
                        },
                    }
                ],
            )
        ],
        [("token", "Screenshot saved.")],
    ]

    final_text, tool_results, tool_names = asyncio.run(
        _run_agent_with_script(
            "Use the browser to open https://example.com and take a screenshot of the page.",
            script,
        )
    )

    assert len(tool_results) >= 2, f"Expected at least 2 tool calls, got {len(tool_results)}: {tool_results}"
    assert tool_names.count("browser") >= 2, f"Expected 2+ browser calls, got {tool_names}"

    assert "the page is open" not in final_text.lower(), f"Got shortcut reply: {final_text}"
    assert "screenshot" in final_text.lower(), f"Missing screenshot mention in: {final_text}"


def test_browser_screenshot_explicit_runs_both() -> None:
    """Browser open then explicit screenshot should run both (P02 bug).

    Matrix item P02 uses explicit action names. The errand-done check
    should respect named_tools_owed like image_edit does.
    """
    script = [
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "browser",
                            "arguments": {"action": "open", "url": "https://example.com"},
                        },
                    }
                ],
            )
        ],
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "browser",
                            "arguments": {"action": "screenshot"},
                        },
                    }
                ],
            )
        ],
        [("token", "Screenshot saved.")],
    ]

    final_text, tool_results, tool_names = asyncio.run(
        _run_agent_with_script(
            "Use the browser tool to open https://example.com, then call the browser tool with action=screenshot.",
            script,
        )
    )

    assert len(tool_results) >= 2, f"Expected at least 2 tool calls, got {len(tool_results)}"
    assert tool_names.count("browser") >= 2, f"Expected 2+ browser calls, got {tool_names}"
    assert "the page is open" not in final_text.lower(), f"Got shortcut reply: {final_text}"
    assert "screenshot" in final_text.lower(), f"Missing screenshot mention in: {final_text}"


def test_browser_open_read_then_document_chain() -> None:
    """Browser open+read then document should run all three (C25/P11 bug).

    Matrix items C25 and P11 failed: browser open succeeded but ended the
    turn before reading the page and saving to document.
    """
    script = [
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "browser",
                            "arguments": {"action": "open", "url": "https://example.com"},
                        },
                    }
                ],
            )
        ],
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "browser",
                            "arguments": {"action": "read"},
                        },
                    }
                ],
            )
        ],
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "document",
                            "arguments": {
                                "format": "txt",
                                "title": "Browser Capture",
                                "body": "Example Domain - This domain is for illustrative examples.",
                            },
                        },
                    }
                ],
            )
        ],
        [("token", "Saved the page heading to Browser Capture.txt")],
    ]

    final_text, tool_results, tool_names = asyncio.run(
        _run_agent_with_script(
            "Open https://example.com in the browser, read the page, then save its "
            "heading into a text document titled Browser Capture.",
            script,
        )
    )

    assert len(tool_results) >= 3, f"Expected at least 3 tool calls, got {len(tool_results)}: {tool_results}"
    assert tool_names.count("browser") >= 2, f"Expected 2+ browser calls, got {tool_names}"
    assert "document" in tool_names, f"Expected document call, got {tool_names}"

    assert "the page is open" not in final_text.lower(), f"Got shortcut reply: {final_text}"
    assert "browser capture" in final_text.lower() or "saved" in final_text.lower(), (
        f"Missing document mention in: {final_text}"
    )
