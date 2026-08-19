"""Same-round independent READ calls may run together; writes stay serial."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.read_fanout import should_fanout_reads
from arelis.tools.base import ToolRegistry, ToolResult

_READS = {"weather", "inbox", "web_search", "scrape", "git_info", "calculator"}
_ALL = _READS | {"send_sms", "send_email", "workspace", "image"}


def _ok(
    calls: list[tuple[str, dict]],
    *,
    expected: set[str] | None = None,
    used: set[str] | None = None,
    search_ok: set[str] | None = None,
    names: set[str] | None = None,
) -> bool:
    return should_fanout_reads(
        calls,
        tool_names=names or _ALL,
        expected_tools=expected or set(),
        tools=ToolRegistry(),
        tools_used=used,
        web_search_ok=search_ok,
    )


def test_two_independent_reads_fanout() -> None:
    assert _ok(
        [
            ("weather", {"place": "home"}),
            ("inbox", {"action": "list"}),
        ]
    )


def test_single_call_stays_serial() -> None:
    assert not _ok([("weather", {"place": "home"})])


def test_send_stays_serial() -> None:
    assert not _ok(
        [
            ("weather", {}),
            ("send_sms", {"to": "Brian", "body": "late"}),
        ]
    )


def test_workspace_write_stays_serial() -> None:
    assert not _ok(
        [
            ("weather", {}),
            ("workspace", {"action": "write", "path": "note.txt", "content": "hi"}),
        ]
    )


def test_web_search_on_weather_turn_stays_serial() -> None:
    assert not _ok(
        [
            ("web_search", {"query": "forecast"}),
            ("inbox", {"action": "list"}),
        ],
        expected={"weather"},
    )


def test_search_and_scrape_fanout_when_urls_already_present() -> None:
    assert _ok(
        [
            ("web_search", {"query": "fusion"}),
            ("scrape", {"url": "https://example.com/a"}),
        ]
    )


def test_duplicate_weather_same_place_stays_serial() -> None:
    assert not _ok(
        [
            ("weather", {"place": "springfield"}),
            ("weather", {"place": "springfield"}),
        ]
    )


def test_two_weather_places_may_fanout() -> None:
    assert _ok(
        [
            ("weather", {"place": "Springfield, Illinois"}),
            ("weather", {"place": "Metropolis, Illinois"}),
        ]
    )


def test_already_fetched_weather_does_not_fanout() -> None:
    assert not _ok(
        [
            ("weather", {}),
            ("inbox", {"action": "list"}),
        ],
        used={"weather"},
    )


def test_duplicate_search_query_does_not_fanout() -> None:
    assert not _ok(
        [
            ("web_search", {"query": "fusion"}),
            ("scrape", {"url": "https://example.com/a"}),
        ],
        search_ok={"fusion"},
    )


class _SlowRead:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = name
        self.risk = "read"
        self.parameters_schema: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }
        self.t0: float | None = None
        self.t1: float | None = None

    async def run(self, **kwargs: object) -> ToolResult:
        del kwargs
        self.t0 = time.perf_counter()
        await asyncio.sleep(0.2)
        self.t1 = time.perf_counter()
        return ToolResult(ok=True, output=f"{self.name} ok")


class _MockProvider:
    def __init__(self, script: list[list[tuple[str, object]]]) -> None:
        self.script = script
        self.i = 0

    async def stream_chat(self, model, messages, **kwargs):
        del model, messages, kwargs
        steps = self.script[self.i]
        self.i += 1
        for item in steps:
            yield item

    async def list_models(self):
        return []

    async def unload(self, model):
        del model
        return None

    async def close(self):
        return None


class _MockRouter:
    def __init__(self, provider: _MockProvider) -> None:
        self.provider = provider
        self.default_role = "fast"
        self.active_model = None
        self.active_role = None
        self.models = {"fast": "mock", "research": "mock", "code": "mock"}

    def model_for(self, role=None):
        del role
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        self.active_role = role
        self.active_model = "mock"
        return "mock"

    def mark_sticky(self, role) -> None:
        del role
        return None

    async def stream(self, role, messages, **kwargs):
        async for item in self.provider.stream_chat("mock", messages, **kwargs):
            yield item


def _native(name: str, args: dict) -> dict:
    return {"type": "function", "function": {"name": name, "arguments": args}}


@pytest.mark.asyncio
async def test_agent_loop_fans_out_two_slow_reads() -> None:
    weather = _SlowRead("weather")
    inbox = _SlowRead("inbox")
    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    provider = _MockProvider(
        [
            [
                (
                    "tool_calls",
                    [
                        _native("weather", {"days": 3}),
                        _native("inbox", {"action": "list"}),
                    ],
                )
            ],
            [("token", "Overcast, inbox is quiet.")],
        ]
    )
    tools = ToolRegistry()
    tools.register(weather)
    tools.register(inbox)
    async def _allow(*_a: object, **_k: object) -> str:
        return "allow"

    loop = AgentLoop(
        bus,
        _MockRouter(provider),  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 6,
                "tool_output_chars": 4000,
                "json_fallback": True,
                "read_fanout": True,
                "chat_fast_path": False,
                "skill_tool_subset": False,
                "intent_preflight": False,
                "exactness": False,
                "confirm_writes": True,
                "confirm_send": True,
            },
            "ollama": {"base_url": "http://127.0.0.1:11434"},
            "voice": {"enabled": False},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    bus_task = asyncio.create_task(bus.run())
    try:
        await loop.run(
            "What's the weather today, and anything new in my inbox?",
            "fast",
        )
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bus_task

    assert weather.t0 is not None and inbox.t0 is not None
    assert weather.t1 is not None and inbox.t1 is not None
    assert weather.t0 < inbox.t1 and inbox.t0 < weather.t1
    thinking = [
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    ]
    assert any("phase=fanout" in line for line in thinking)
    names = [
        str(e.payload.get("tool") or "")
        for e in events
        if e.type == EventType.TOOL_START
    ]
    assert names == ["weather", "inbox"]


@pytest.mark.asyncio
async def test_agent_loop_verify_refuse_is_named() -> None:
    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    provider = _MockProvider(
        [
            [("token", "The WSJ said the genomes were engineered in a lab.")],
            [
                (
                    "token",
                    "I don't know the headline id, but the story is that "
                    "genomes were engineered in a lab.",
                )
            ],
        ]
    )
    tools = ToolRegistry()
    tools.register(_SlowRead("web_search"))
    tools.register(_SlowRead("scrape"))

    async def _allow(*_a: object, **_k: object) -> str:
        return "allow"

    loop = AgentLoop(
        bus,
        _MockRouter(provider),  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 6,
                "tool_output_chars": 4000,
                "json_fallback": True,
                "chat_fast_path": False,
                "skill_tool_subset": False,
                "intent_preflight": False,
                "exactness": True,
                "numeric_gate": True,
                "evidence_gate": True,
                "research_dual_hit": False,
                "confirm_writes": True,
            },
            "ollama": {"base_url": "http://127.0.0.1:11434"},
            "voice": {"enabled": False},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    bus_task = asyncio.create_task(bus.run())
    try:
        await loop.run("What did the WSJ say about AI virus genomes?", "fast")
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bus_task

    thinking = [
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    ]
    assert any(line.startswith("phase=verify") for line in thinking)
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "don't know" in (done.payload.get("text") or "").lower()
    assert "engineered" not in (done.payload.get("text") or "").lower()
