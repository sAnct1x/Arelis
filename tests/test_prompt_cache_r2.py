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
from arelis.core.context import estimate_tokens
from arelis.core.memory import SessionMemory
from arelis.core.turn_prepare import prepare_turn
from arelis.llm.startup import prefix_warmup_for
from arelis.memory.store import MemoryStore
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


@pytest.mark.asyncio
async def test_same_tools_every_turn_and_on_the_warmup(frozen_clock) -> None:
    """Hello, a forecast, and goodbye send one list, and the warmup sends it too."""
    del frozen_clock
    registry = _registry()
    loop = _loop(registry=registry)
    sent = []
    for minute, ask in (
        (31, "hello"),
        (32, "what's the weather tomorrow"),
        (33, "thanks, bye"),
    ):
        _stamp(minute)
        ctx = await prepare_turn(loop, ask, "fast")
        assert ctx is not None
        sent.append(json.dumps(ctx.ollama_tools))
        loop.memory.add("assistant", "Noted.")
    assert sent[0] == sent[1] == sent[2]
    assert _names(json.loads(sent[0]))
    warm = prefix_warmup_for(_config(), registry)
    assert warm is not None
    assert json.dumps(warm.tools) == sent[0]


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
    assert "A weather-tool forecast" in turn_text
    assert "weather" in loop._expected_tools
    assert "weather" in _names(weather.ollama_tools)
    loop.memory.add("assistant", "Mild tomorrow.")
    bye = _loop()
    _stamp(33)
    closing = await prepare_turn(bye, "thanks, bye", "fast")
    assert closing is not None
    assert "weather" not in bye._expected_tools
    assert _names(closing.ollama_tools) == _names(weather.ollama_tools)


@pytest.mark.asyncio
async def test_next_turn_extends_the_previous_request(frozen_clock) -> None:
    """Turn 2's first request starts with turn 1's last, including the old notes."""
    del frozen_clock
    call = {
        "type": "function",
        "function": {"name": "weather", "arguments": {"when": "tomorrow"}},
    }
    router = _RecordingRouter(
        [
            [("token", "Hi.")],
            [("tool_calls", [call])],
            [("token", "Mild tomorrow.")],
            [("token", "Anytime.")],
        ]
    )
    loop = _loop(router=router)
    _stamp(31)
    await loop.run("hello", "fast")
    _stamp(32)
    await loop.run("what's the weather tomorrow", "fast")
    _stamp(33)
    await loop.run("thanks, bye", "fast")
    assert len(router.sent) >= 3
    first = router.sent[0][0]
    # The forecast turn's first model request, then goodbye's first.
    forecast_at = next(
        index
        for index, (messages, _tools) in enumerate(router.sent)
        if any(
            message.get("role") == "user" and message.get("content") == "what's the weather tomorrow"
            for message in messages
        )
    )
    bye_at = next(
        index
        for index, (messages, _tools) in enumerate(router.sent)
        if any(
            message.get("role") == "user" and message.get("content") == "thanks, bye"
            for message in messages
        )
    )
    forecast = router.sent[forecast_at][0]
    forecast_last = router.sent[bye_at - 1][0]
    bye = router.sent[bye_at][0]
    assert json.dumps(forecast[: len(first)]) == json.dumps(first)
    assert json.dumps(bye[: len(forecast_last)]) == json.dumps(forecast_last)
    assert "9:31 PM" in json.dumps(first)
    assert "9:31 PM" in json.dumps(bye)


@pytest.mark.asyncio
async def test_transcript_hides_turn_notes(frozen_clock, tmp_path) -> None:
    """The clock line is in the next prompt and not in the transcript rows."""
    del frozen_clock
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    loop = _loop(memory=memory)
    _stamp(31)
    first = await prepare_turn(loop, "hello", "fast")
    assert first is not None
    loop.memory.add("assistant", "Hi.")
    _stamp(32)
    second = await prepare_turn(loop, "hello again", "fast")
    assert second is not None
    replayed = json.dumps(second.messages)
    assert "9:31 PM" in replayed
    visible = []
    for message in memory.messages:
        visible.append(message.content)
        visible.append(message.note)
    for row in store.get_messages(store.session_id or ""):
        visible.append(str(row.get("content") or ""))
        visible.append(str(row.get("note") or ""))
    blob = "\n".join(visible)
    assert "9:31 PM" not in blob
    assert "Right now it is" not in blob
    store.close()


@pytest.mark.asyncio
async def test_replayed_blocks_stay_under_budget_and_drop_on_trim(frozen_clock) -> None:
    """Ten turns of notes stay under the budget. Trimming drops the old ones."""
    del frozen_clock
    loop = _loop()
    for minute in range(10):
        _stamp(minute)
        ctx = await prepare_turn(loop, "hello", "fast")
        assert ctx is not None
        loop.memory.add("assistant", f"Reply {minute}.")
    replayed = [
        message
        for message in loop.memory.as_ollama()
        if message.get("role") == "system"
    ]
    assert len(replayed) >= 10
    cost = sum(
        estimate_tokens(str(message.get("content") or ""), chars_per_token=3.5)
        for message in replayed
    )
    assert cost < REPLAY_BUDGET_10
    oldest = str(replayed[0]["content"])
    newest = str(replayed[-1]["content"])
    loop.memory.max_messages = 4
    loop.memory._trim()
    after = json.dumps(loop.memory.as_ollama())
    assert oldest not in after
    assert newest in after


@pytest.mark.asyncio
async def test_vision_does_not_schedule_a_warmup(tmp_path) -> None:
    """A look on the chat model must not start another prefix seed."""
    from PIL import Image

    from arelis.llm.startup import PrefixWarmup
    from arelis.tools.vision import VisionTool
    from arelis.workspace import WorkspaceRoots

    path = tmp_path / "shot.png"
    Image.new("RGB", (32, 24), (10, 20, 30)).save(path, format="PNG")

    class _Bus:
        async def publish(self, event) -> None:
            del event

    class _Provider:
        def __init__(self) -> None:
            self.calls = 0

        async def stream_chat(self, model, messages, **kwargs):
            del model, messages, kwargs
            self.calls += 1
            yield ("token", "x")

    class _LookRouter:
        def __init__(self) -> None:
            self.warm_on_start = True
            self.prefix_warmup = PrefixWarmup(
                messages=[{"role": "system", "content": "PERSONA"}],
                tools=[{"type": "function", "function": {"name": "weather"}}],
                num_ctx=4096,
            )
            self.bus = _Bus()
            self.provider = _Provider()
            self.active_model = "probe-chat"
            self.default_role = "fast"
            self.default_keep_alive = "30m"
            self.images: list[str] = []

        def model_for(self, role=None):
            del role
            return self.active_model

        async def chat_sees_images(self) -> bool:
            return True

        async def run_vision(self, prompt, images_b64, **_kwargs):
            del prompt
            self.images.extend(images_b64)
            return "seen"

    router = _LookRouter()
    tool = VisionTool(WorkspaceRoots.from_paths([str(tmp_path)]), router)
    result = await tool.run(path=str(path), question="what is this")
    assert result.ok
    from arelis.llm import startup as startup_mod

    task = getattr(startup_mod, "_reseed_task", None)
    if task is not None and not task.done():
        await task
    assert router.provider.calls == 0
