"""#368: a short ask with no tool round skips thinking; a tool ask keeps it."""

from __future__ import annotations

import pytest

from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from tests.test_prompt_cache_r2 import AgentLoop, _config, _RecordingRouter, _registry


class _ThinkRouter(_RecordingRouter):
    def __init__(self) -> None:
        super().__init__([[("token", "Paris.")]])
        self.think: list[object] = []

    async def stream(self, role, messages, **kwargs):
        self.think.append(kwargs.get("think"))
        async for item in super().stream(role, messages, **kwargs):
            yield item


async def _first_think(text: str) -> object:
    router = _ThinkRouter()
    loop = AgentLoop(
        EventBus(),
        router,  # type: ignore[arg-type]
        _registry(),
        SessionMemory(),
        "PERSONA",
        _config(),
        request_confirm=lambda *_: False,
        is_cancelled=lambda: False,
    )
    await loop.run(text, "fast")
    return router.think[0]


@pytest.mark.asyncio
async def test_a_short_plain_ask_skips_thinking_and_a_tool_ask_does_not() -> None:
    assert await _first_think("what is the capital of France") is False
    assert await _first_think("what's the weather tomorrow") is None


class _SpokenToolRouter(_RecordingRouter):
    def __init__(self) -> None:
        call = {
            "type": "function",
            "function": {"name": "weather", "arguments": {"place": "Boston"}},
        }
        super().__init__(
            [
                [("tool_calls", [call])],
                [("token", "It is 45 F and clear in Boston right now.")],
            ]
        )
        self.think: list[object] = []

    async def stream(self, role, messages, **kwargs):
        self.think.append(kwargs.get("think"))
        async for item in super().stream(role, messages, **kwargs):
            yield item


@pytest.mark.asyncio
async def test_a_spoken_turn_skips_thinking_on_the_tool_round_and_the_write_up() -> None:
    """Conversation voice sends enable_thinking=false on every request.

    Official weather and calculator turns thought before the tool and again
    on the write-up, so the first spoken sentence only existed at DONE.
    """
    router = _SpokenToolRouter()
    cfg = _config()
    cfg["_speak_replies"] = True
    loop = AgentLoop(
        EventBus(),
        router,  # type: ignore[arg-type]
        _registry(),
        SessionMemory(),
        "PERSONA",
        cfg,
        request_confirm=lambda *_: False,
        is_cancelled=lambda: False,
    )
    await loop.run("What's the weather in Boston right now?", "fast")
    assert len(router.think) >= 2, router.think
    assert router.think == [False] * len(router.think)
