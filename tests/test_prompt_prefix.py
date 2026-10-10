"""The cached front of a turn stays put when the clock and the ask change."""

from __future__ import annotations

import json
from datetime import datetime

import pytest

import arelis.core.agent_loop as agent_loop_mod
import arelis.core.turn_prepare as subject
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.core.turn_prepare import prepare_turn
from arelis.tools.base import ToolRegistry


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
    description = "probe tool"
    risk = "read"
    parameters_schema = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name


def _loop() -> AgentLoop:
    config = {
        "agent": {
            "chat_fast_path": True,
            "intent_preflight": True,
            "lessons": True,
            "max_rounds": 4,
        },
        # 65k is the normal window. The replayed notes do not fit in 4096
        # beside the persona, so that smaller window trims and the front moves.
        "ollama": {"num_ctx": 65536},
    }
    registry = ToolRegistry()
    for name in ("weather", "web_search", "calculator"):
        registry.register(_Tool(name))  # type: ignore[arg-type]
    return AgentLoop(
        EventBus(),
        _Router(),  # type: ignore[arg-type]
        registry,
        SessionMemory(),
        "PERSONA",
        config,
        request_confirm=lambda *_: False,
        is_cancelled=lambda: False,
    )


def _stamp(hour: int, minute: int) -> None:
    _Clock.when = datetime(2026, 10, 9, hour, minute)


def _before_first_user(messages: list[dict]) -> list[dict]:
    for index, message in enumerate(messages):
        if message.get("role") == "user":
            return messages[:index]
    return list(messages)


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(agent_loop_mod, "datetime", _Clock)
    _stamp(21, 31)


@pytest.mark.asyncio
async def test_turn_prefix_before_history_is_identical_across_different_asks(
    frozen_clock,
) -> None:
    """Two asks, one minute apart, share every byte before the first history line.

    A previous exchange is already in memory, so that first line is history
    rather than the new ask. The per-turn block has to sit after it.
    """
    del frozen_clock
    left = _loop()
    right = _loop()
    for loop in (left, right):
        loop.memory.add("user", "earlier")
        loop.memory.add("assistant", "Noted.")
    _stamp(21, 31)
    first = await prepare_turn(left, "hello", "fast")
    _stamp(21, 32)
    second = await prepare_turn(right, "what's the weather tomorrow", "fast")
    assert first is not None and second is not None
    front_a = _before_first_user(first.messages)
    front_b = _before_first_user(second.messages)
    assert json.dumps(front_a) == json.dumps(front_b)
    # Tool menus can still differ. That is routing, and this test does not
    # paper over it by requiring the menus to match.
    _ = json.dumps(first.ollama_tools) == json.dumps(second.ollama_tools)


@pytest.mark.asyncio
async def test_second_turn_extends_first_turn(frozen_clock) -> None:
    del frozen_clock
    loop = _loop()
    _stamp(21, 31)
    first = await prepare_turn(loop, "hello", "fast")
    assert first is not None
    loop.memory.add("assistant", "Hi.")
    _stamp(21, 32)
    second = await prepare_turn(loop, "hello again", "fast")
    assert second is not None
    # The first turn's notes stay in the next prompt, so the next request
    # starts with the previous one. Round 1 dropped those notes on purpose.
    assert json.dumps(second.messages[: len(first.messages)]) == json.dumps(first.messages)
    history_end = len(first.messages) + 1
    assert second.messages[len(first.messages)]["role"] == "assistant"
    assert second.messages[len(first.messages)]["content"] == "Hi."
    assert json.dumps(second.messages[:history_end]) == json.dumps(
        [*first.messages, second.messages[len(first.messages)]]
    )
    clock = "9:32 PM"
    hits = [
        index
        for index, message in enumerate(second.messages)
        if clock in str(message.get("content") or "")
    ]
    assert hits == [hits[0]]
    assert len(first.messages) < hits[0] < len(second.messages) - 1
    assert second.messages[hits[0]]["role"] == "system"
    assert second.messages[-1]["role"] == "user"
    assert second.messages[-1]["content"] == "hello again"
    assert "9:31 PM" in json.dumps(second.messages)


def _record(real, bucket):
    def wrapped(messages, *args, **kwargs):
        start = len(messages)
        result = real(messages, *args, **kwargs)
        bucket.extend(messages[start:])
        return result

    return wrapped


@pytest.mark.asyncio
async def test_turn_tail_content_stays_byte_identical(frozen_clock, monkeypatch) -> None:
    """Same section strings, same order, sitting just before the new ask."""
    del frozen_clock
    bucket: list[dict] = []
    for name in (
        "append_stopped_turn_note",
        "append_preflight_guidance",
        "append_turn_goal",
        "append_plan_and_lessons",
        "append_operating_context",
        "append_delivery_context",
    ):
        monkeypatch.setattr(subject, name, _record(getattr(subject, name), bucket))
    loop = _loop()
    loop.memory.add("user", "earlier")
    loop.memory.add("assistant", "Noted.")
    _stamp(21, 31)
    ctx = await prepare_turn(loop, "hello", "fast")
    assert ctx is not None
    assert bucket
    last_user = max(
        index
        for index, message in enumerate(ctx.messages)
        if message.get("role") == "user"
    )
    block = ctx.messages[last_user - len(bucket) : last_user]
    assert block == bucket
    assert ctx.messages[last_user]["content"] == "hello"
    joined = json.dumps(block)
    assert "9:31 PM" in joined
    theme_at = next(
        index for index, message in enumerate(block) if "theme" in message["content"].lower()
    )
    clock_at = next(index for index, message in enumerate(block) if "9:31 PM" in message["content"])
    assert theme_at < clock_at
