"""Shared hardening-test stubs. Not collected (no test_ prefix)."""

from __future__ import annotations

import asyncio
from typing import Any

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.code_workspace import CodeWorkspaceTool


class _ScriptedRouter:
    """Minimal ModelRouter stand-in driven by a list of scripted streams."""

    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        self.script = script
        self.i = 0
        self.default_role = "fast"
        self.active_model = None
        self.active_role = None
        self.models = {"fast": "mock", "research": "mock", "code": "mock"}

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        self.active_role = role
        self.active_model = "mock"
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    def apply_sticky(self, wanted, reason: str):
        return wanted, reason

    async def stream(self, role, messages, **kwargs):
        steps = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        for item in steps:
            yield item


def _config() -> dict[str, Any]:
    return {
        "agent": {"max_rounds": 4, "tool_output_chars": 4000, "json_fallback": True},
        "ollama": {"base_url": "http://127.0.0.1:11434"},
        "voice": {"enabled": False},
        "_persona_path": "does-not-exist.md",
    }


async def _collect(bus: EventBus, coro) -> list[Event]:
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    task = asyncio.create_task(bus.run())
    await coro
    await bus.drain()
    bus.stop()
    task.cancel()
    return events


class _BoomRouter(_ScriptedRouter):
    """First stream() raises; used to prove Ollama-down copy."""

    def __init__(self, exc: BaseException) -> None:
        super().__init__([[]])
        self.exc = exc
        self.calls = 0

    async def stream(self, role, messages, **kwargs):
        self.calls += 1
        raise self.exc
        yield  # unreachable; keeps this an async generator like ModelRouter.stream


class _ToolsRejectThenOk(_ScriptedRouter):
    """HTTP 400 on the tools array, then a normal answer (JSON fallback)."""

    def __init__(self) -> None:
        super().__init__([[("token", "here without native schemas")]])
        self.calls = 0

    async def stream(self, role, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError(
                "Ollama returned HTTP 400 for model `mock`: invalid tools"
            )
        async for item in super().stream(role, messages, **kwargs):
            yield item


def _loop_with_tools(router) -> AgentLoop:
    tools = ToolRegistry()
    tools.register(CodeWorkspaceTool(["."]))
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    return AgentLoop(
        EventBus(),
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )


class _ScrapeStub:
    """Read tool that succeeds; used to prove empty-after-tool skips JSON mode."""

    name = "scrape"
    description = "fetch a page"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(
            ok=True,
            output="NASDAQ:SPCX last $143.34",
        )


class _LongScrapeStub:
    """A page, not a fact — empty-after-tool must not paste it."""

    name = "scrape"
    description = "fetch a page"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(
            ok=True,
            output=(
                "# What is Single Crystal Piezo or PMN-PT?\n"
                "Site: piezo.com\n\n"
                + ("PMN-PT single crystals have a high d33. " * 40)
            ),
        )


def _long_scrape_loop(
    router: _ScriptedRouter,
) -> tuple[EventBus, AgentLoop]:
    bus = EventBus()
    tools = ToolRegistry()
    tools.register(_LongScrapeStub())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 8
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    return bus, loop


def _scrape_then_empty(extra: list[list[tuple[str, Any]]]) -> _ScriptedRouter:
    first: list[tuple[str, Any]] = [
        (
            "tool_calls",
            [
                {
                    "type": "function",
                    "function": {
                        "name": "scrape",
                        "arguments": {
                            "url": "https://blog.piezo.com/pmn-pt",
                        },
                    },
                }
            ],
        )
    ]
    return _ScriptedRouter([first, *extra])


class _AgendaStub:
    """Write tool whose wrap-up round strips schemas (agenda_create_ok)."""

    name = "agenda"
    description = "calendar"
    risk = "write"
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "provider": {"type": "string"},
            "summary": {"type": "string"},
            "start": {"type": "string"},
        },
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(
            ok=True,
            output="Created on google: go to the lab @ 2026-08-20T10:00:00-04:00",
        )


async def _deny(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
    return "skip"
