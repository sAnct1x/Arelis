"""Live turns keep one tool list and replay the per-turn notes.

The notes stay in the prompt the next turn sends. They stay off the
transcript the person can read.
"""

from __future__ import annotations

import json
from datetime import datetime

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
            "lessons": True,
            "max_rounds": 4,
            "json_fallback": False,
        },
        "llamacpp": {"default_cap": 65536},
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


@pytest.mark.asyncio
async def test_routing_still_steers_in_the_turn_text(frozen_clock) -> None:
    """The forecast note stays in the turn text, and goodbye still drops the expectation."""
    del frozen_clock
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
    assert "weather" in _names(weather.chat_tools)
    loop.memory.add("assistant", "Mild tomorrow.")
    bye = _loop()
    _stamp(33)
    closing = await prepare_turn(bye, "thanks, bye", "fast")
    assert closing is not None
    assert "weather" not in bye._expected_tools
    assert _names(closing.chat_tools) == _names(weather.chat_tools)


