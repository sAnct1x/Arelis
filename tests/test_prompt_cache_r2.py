"""Live turns keep one tool list and replay the per-turn notes.

The notes stay in the prompt the next turn sends. They stay off the
transcript the person can read.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from itertools import pairwise

import pytest

import arelis.core.agent_loop as agent_loop_mod
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.core.turn_prepare import prepare_turn
from arelis.tools.base import ToolRegistry, ToolResult

# Ten replayed blocks, estimated at 3.5 characters per token. A chat that
# long should still leave most of a 65k window for the conversation.
REPLAY_BUDGET_10 = 8000


class _Clock(datetime):
    when = datetime(2026, 10, 9, 21, 31)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.when
        return cls.when.replace(tzinfo=tz)


class _Router:
    active_model = None

    def model_for(self, role=None):
        del role
        return "probe-model"


class _Tool:
    description = "probe"
    risk = "read"
    parameters_schema = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, **kwargs):
        del kwargs
        return ToolResult(ok=True, output="Mild and clear.")


class _RecordingRouter:
    def __init__(self, script: list[list[tuple]]) -> None:
        self.script = script
        self.i = 0
        self.sent: list[tuple[list, list | None]] = []
        self.active_model = None

    def model_for(self, role=None):
        del role
        return "probe-model"

    async def stream(self, role, messages, **kwargs):
        del role
        self.sent.append((json.loads(json.dumps(messages)), kwargs.get("tools")))
        steps = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        for item in steps:
            yield item


def _config() -> dict:
    return {
        "agent": {
            "chat_fast_path": True,
            "intent_preflight": True,
            "lessons": True,
            "max_rounds": 4,
            "json_fallback": False,
            "weather_force_call": False,
        },
        "ollama": {"num_ctx": 65536},
        "_persona_path": "does-not-exist.md",
    }


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name in (
        "weather",
        "web_search",
        "scrape",
        "web_fetch",
        "user_location",
        "calculator",
    ):
        registry.register(_Tool(name))  # type: ignore[arg-type]
    return registry


def _loop(*, memory: SessionMemory | None = None, router=None, registry=None) -> AgentLoop:
    return AgentLoop(
        EventBus(),
        router or _Router(),  # type: ignore[arg-type]
        registry or _registry(),
        memory or SessionMemory(),
        "PERSONA",
        _config(),
        request_confirm=lambda *_: False,
        is_cancelled=lambda: False,
    )


def _stamp(minute: int) -> None:
    _Clock.when = datetime(2026, 10, 9, 21, minute)


def _names(tools: list | None) -> list[str]:
    found: list[str] = []
    for item in tools or []:
        fn = item.get("function") or {}
        found.append(str(fn.get("name") or item.get("name") or ""))
    return found


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(agent_loop_mod, "datetime", _Clock)
    _stamp(31)


class _Provider:
    """Every chat, summary, and reseed request lands here."""

    def __init__(self, script: list[list[tuple]]) -> None:
        self.script = script
        self.i = 0
        self.requests: list[dict] = []

    async def stream_chat(self, model, messages, **kwargs):
        del model
        self.requests.append(
            {
                "messages": json.loads(json.dumps(messages)),
                "tools": kwargs.get("tools"),
                "options": dict(kwargs.get("options") or {}),
            }
        )
        steps = self.script[self.i] if self.i < len(self.script) else [("token", "")]
        self.i += 1
        for item in steps:
            yield item


class _ChatRouter:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider
        self.active_model = "probe-model"
        self.default_keep_alive = "30m"
        self.default_role = "fast"

    def model_for(self, role=None):
        del role
        return "probe-model"

    def apply_sticky(self, wanted, reason):
        return wanted, reason

    async def ensure_role(self, role, *, force=False):
        del role, force
        return "probe-model"

    def mark_sticky(self, role) -> None:
        del role

    async def stream(self, role, messages, **kwargs):
        del role
        async for item in self.provider.stream_chat("probe-model", messages, **kwargs):
            yield item


class _Host:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class _Measure:
    name = "measure"
    description = "measure a plant"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"what": {"type": "string"}},
        "required": ["what"],
    }

    def __init__(self, window: _Host) -> None:
        self.window = window
        self.calls = 0

    async def run(self, **kwargs):
        del kwargs
        self.calls += 1
        from arelis.core.tool_surface import _reseed_session_prefix

        _reseed_session_prefix(self.window, self.window.orchestrator.tools)
        return ToolResult(ok=True, output="12 cm")


def _extends(previous: list, nxt: list) -> None:
    """The next request starts with the previous one, tail included.

    A new turn may only add rows after that shared head. A summary or a
    reseed shoved into the middle fails here.
    """
    if nxt[: len(previous)] == previous:
        return
    limit = min(len(previous), len(nxt))
    for index in range(limit):
        if previous[index] != nxt[index]:
            raise AssertionError(
                f"row {index} diverged\nprev={previous[index]!r}\nnext={nxt[index]!r}"
            )
    raise AssertionError(f"next request is shorter ({len(nxt)} < {len(previous)})")


@pytest.mark.asyncio
async def test_stable_prefix_rounds_extend_and_idle_work_stays_off_the_model(
    frozen_clock,
) -> None:
    """Two rounds and a second turn extend one another. Nothing else calls the model."""
    del frozen_clock
    cfg = {
        "agent": {
            "stable_prefix": True,
            "chat_fast_path": False,
            "max_rounds": 4,
            "json_fallback": False,
            "exactness": False,
            "numeric_gate": False,
            "evidence_gate": False,
            "mid_turn_escalate": False,
            "lessons": False,
            "native_tool_calling": False,
            "history_max_messages": 40,
            "history_min_recent": 4,
            "summarize_skip_slash": True,
            "confirm_writes": False,
            "ask_is_grant": True,
        },
        "ollama": {"num_ctx": 65536},
        "_persona_path": "does-not-exist.md",
        "voice": {"enabled": False},
    }
    memory = SessionMemory(max_messages=10_000)
    memory.summary = "They kept the plant heights."
    for index in range(30):
        memory.add("user", f"question {index} about the fern")
        memory.add("assistant", f"answer {index}")
    call = {
        "type": "function",
        "function": {"name": "measure", "arguments": {"what": "fern"}},
    }
    provider = _Provider(
        [
            [("tool_calls", [call])],
            [("token", "The fern is 12 cm tall.")],
            [("token", "The fern is 12 cm wide.")],
        ]
    )
    router = _ChatRouter(provider)
    bus = EventBus()
    registry = ToolRegistry()
    window = _Host(
        loop=asyncio.get_running_loop(),
        router=router,
        bus=bus,
        config=cfg,
        orchestrator=None,
    )
    tool = _Measure(window)
    registry.register(tool)  # type: ignore[arg-type]
    orch = _Host(memory=memory, tools=registry, persona="PERSONA", config=cfg)
    window.orchestrator = orch

    async def _allow(*_args, **_kwargs) -> str:
        return "allow"

    def _make() -> AgentLoop:
        return AgentLoop(
            bus,
            router,  # type: ignore[arg-type]
            registry,
            memory,
            "PERSONA",
            cfg,
            request_confirm=_allow,
            is_cancelled=lambda: False,
        )

    await _make().run("how tall is the fern", "fast")
    assert tool.calls == 1
    memory.summary = "They checked the fern width."
    await _make().run("and how wide is the fern", "fast")

    sent = provider.requests
    assert len(sent) == 3, [len(item["messages"]) for item in sent]
    for item in sent:
        assert item["options"].get("num_predict") != 1
        blob = json.dumps(item["messages"])
        assert "You compress older turns" not in blob
    for earlier, later in pairwise(sent):
        _extends(earlier["messages"], later["messages"])

    first = sent[0]["messages"]
    assert "question 0 about the fern" not in json.dumps(first)
    summary_at = next(
        index
        for index, message in enumerate(first)
        if "plant heights" in str(message.get("content") or "")
    )
    assert any(message.get("role") in {"user", "assistant"} for message in first[:summary_at])
    assert any(
        message.get("content") == agent_loop_mod._TOOL_ROUND_HINT for message in first
    )
    widened = json.dumps(sent[-1]["messages"])
    assert "fern width" in widened
    assert "fern width" not in json.dumps(sent[-2]["messages"])
    assert "plant heights" in widened

    from arelis.core.agent_loop import (
        cancel_idle_prefix,
        full_conversation_messages,
        static_system_prefix,
    )

    full = full_conversation_messages("PERSONA", memory, cfg)
    static = static_system_prefix("PERSONA")
    assert full[: len(static)] == list(static)
    assert len(full) > len(static)
    assert any("how tall is the fern" in str(message.get("content") or "") for message in full)
    # The turn just queued a fold. Drop it before the next await so it cannot
    # reach the provider after the checks above.
    cancel_idle_prefix(memory)
    await _routing_still_steers()


async def _routing_still_steers() -> None:
    """The forecast note stays in the turn text, and goodbye still drops the expectation."""
    loop = _loop()
    _stamp(32)
    weather = await prepare_turn(loop, "what's the weather tomorrow", "fast")
    assert weather is not None
    turn_text = "\n".join(
        str(message.get("content") or "")
        for message in weather.messages
        if message.get("role") == "system"
    )
    assert "A forecast for the place they named." in turn_text
    assert "weather tool" not in turn_text.lower()
    assert "weather" in loop._expected_tools
    assert "weather" in _names(weather.ollama_tools)
    loop.memory.add("assistant", "Mild tomorrow.")
    bye = _loop()
    _stamp(33)
    closing = await prepare_turn(bye, "thanks, bye", "fast")
    assert closing is not None
    assert "weather" not in bye._expected_tools
    assert _names(closing.ollama_tools) == _names(weather.ollama_tools)


