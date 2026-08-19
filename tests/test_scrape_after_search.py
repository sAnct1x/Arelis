"""Loop nudges scrape when the model tries to answer news from snippets."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult


class _Stub:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name
        self.risk = "read"
        self.parameters_schema = {"type": "object", "properties": {}}
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        if self.name == "web_search":
            return ToolResult(
                ok=True,
                output=(
                    "1. Example\n"
                    "Title: Example story\n"
                    "URL: https://news.example/story\n"
                    "   preview\n"
                ),
            )
        return ToolResult(ok=True, output="article body about the event", data={"url": kwargs.get("url")})


class _Router:
    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        self.script = script
        self.i = 0
        self.active_model = "mock"
        self.default_role = "fast"

    def model_for(self, role=None) -> str:
        return "mock"

    async def ensure_role(self, role, *, force: bool = False) -> str:
        del force
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    async def stream(self, role, messages, **kwargs):
        steps = self.script[self.i]
        self.i += 1
        for item in steps:
            yield item


def _tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "arguments": args}}


async def _allow(*_a: Any, **_k: Any) -> str:
    return "allow"


@pytest.mark.asyncio
async def test_answers_from_search_alone_get_one_scrape_nudge() -> None:
    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    tools = ToolRegistry()
    search = _Stub("web_search")
    scrape = _Stub("scrape")
    tools.register(search)
    tools.register(scrape)

    # 1) search  2) try to finalize  3) after nudge, scrape  4) final answer
    router = _Router(
        [
            [("tool_calls", [_tool("web_search", {"query": "WSJ AI genomes"})])],
            [("token", "Based on the snippets, here is what happened.")],
            [
                (
                    "tool_calls",
                    [_tool("scrape", {"url": "https://news.example/story"})],
                )
            ],
            [("token", "After reading the page: the lab published genomes.")],
        ]
    )
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 8,
                "tool_output_chars": 4000,
                "json_fallback": True,
                "skill_cards": True,
                "intent_preflight": True,
                "lessons": True,
                "scrape_after_search": True,
                "turn_telemetry": False,
            },
            "ollama": {"num_ctx": 8192},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )

    task = asyncio.create_task(bus.run())
    try:
        await loop.run(
            "What did the latest news say about AI virus genomes?",
            "fast",
        )
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    starts = [e.payload.get("tool") for e in events if e.type == EventType.TOOL_START]
    assert starts == ["web_search", "scrape"]
    assert scrape.calls
    assert scrape.calls[0].get("url", "").startswith("http")
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "search without scrape" in thinking


class _JsShellScrape:
    def __init__(self) -> None:
        self.name = "scrape"
        self.description = "scrape"
        self.risk = "read"
        self.parameters_schema = {"type": "object", "properties": {}}
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        url = str(kwargs.get("url") or "")
        return ToolResult(
            ok=False,
            output="[fail:js_shell] Almost no readable HTML text — likely a JavaScript app shell.",
            data={"url": url, "fail_class": "fail:js_shell"},
        )


@pytest.mark.asyncio
async def test_js_shell_scrape_gets_one_browser_nudge() -> None:
    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    tools = ToolRegistry()
    scrape = _JsShellScrape()
    browser = _Stub("browser")
    tools.register(scrape)
    tools.register(browser)

    router = _Router(
        [
            [
                (
                    "tool_calls",
                    [_tool("scrape", {"url": "https://spa.example/app"})],
                )
            ],
            [("token", "The app says hello.")],
            [
                (
                    "tool_calls",
                    [_tool("browser", {"action": "open", "url": "https://spa.example/app"})],
                )
            ],
            [("token", "Opened in her window.")],
        ]
    )
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 8,
                "tool_output_chars": 4000,
                "json_fallback": True,
                "skill_cards": True,
                "intent_preflight": False,
                "lessons": False,
                "scrape_after_search": True,
                "browser_after_js_shell": True,
                "turn_telemetry": False,
            },
            "ollama": {"num_ctx": 8192},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )

    task = asyncio.create_task(bus.run())
    try:
        await loop.run(
            "Summarize the article at https://spa.example/app",
            "fast",
        )
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    starts = [e.payload.get("tool") for e in events if e.type == EventType.TOOL_START]
    assert starts == ["scrape", "browser"]
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "js shell" in thinking
    assert browser.calls
    assert browser.calls[0].get("action") == "open"
