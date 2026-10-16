"""Answer path applies the dash filter end to end (no mock of the filter)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry
from tests.hardening_helpers import (
    _collect,
    _config,
    _deny,
    _loop_with_tools,
    _ScriptedRouter,
)

EM = "\u2014"


@pytest.mark.asyncio
async def test_streamed_answer_strips_em_dash_deltas_and_done() -> None:
    """Model tokens with an em dash land clean in deltas, done, memory, voice."""
    bus = EventBus()
    router = _ScriptedRouter(
        [[("token", "Sure "), ("token", EM), ("token", " here"), ("token", " you go.")]]
    )
    tools = ToolRegistry()
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["voice"] = {"enabled": True, "tts": {"enabled": True}}
    from arelis.core.agent_loop import AgentLoop

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
    events = await _collect(bus, loop.run("hi", "fast", source="eval"))

    deltas = [
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.ASSISTANT_DELTA
    ]
    dones = [
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.ASSISTANT_DONE
    ]
    speaks = [
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.VOICE_SPEAK
    ]
    retracts = [e for e in events if e.type == EventType.ASSISTANT_RETRACT]

    joined = "".join(deltas)
    assert joined == "Sure, here you go."
    assert dones == ["Sure, here you go."]
    assert speaks == ["Sure, here you go."]
    assert EM not in joined
    assert not retracts
    last = [m for m in loop.memory.messages if m.role == "assistant"][-1]
    assert last.content == "Sure, here you go."


@pytest.mark.asyncio
async def test_finish_passthrough_keeps_dash() -> None:
    loop = _loop_with_tools(_ScriptedRouter(["ignored"]))
    text = f"tool said {EM} keep it"
    events = await _collect(
        loop.bus, loop._finish(text, [], passthrough_tool="weather")
    )
    dones = [
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.ASSISTANT_DONE
    ]
    assert dones == [text]
    assert EM in dones[0]


@pytest.mark.asyncio
async def test_finish_does_not_rewrite_source_titles() -> None:
    loop = _loop_with_tools(_ScriptedRouter(["ignored"]))
    title = f"Paper {EM} Title"
    events = await _collect(
        loop.bus,
        loop._finish("Here is the summary.", [(title, "https://example.com/a")]),
    )
    dones = [
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.ASSISTANT_DONE
    ]
    assert len(dones) == 1
    assert title in dones[0]
    assert "Here is the summary." in dones[0]




@pytest.mark.asyncio
async def test_answer_after_a_tool_streams_instead_of_landing_whole() -> None:
    """#260 (b): the write-up round after a tool paints (and so speaks) per token."""
    from arelis.core.agent_loop import AgentLoop
    from arelis.tools.base import ToolResult

    class _Catalog:
        name = "weather"
        description = "current weather"
        risk = "read"
        parameters_schema = {"type": "object", "properties": {"place": {"type": "string"}}}

        async def run(self, **kwargs):
            return ToolResult(ok=True, output="Paris: 18 C, sunny")

    call = {"type": "function", "function": {"name": "weather", "arguments": {"place": "Paris"}}}
    router = _ScriptedRouter(
        [
            [("tool_calls", [call])],
            [("token", "It is sunny and 18 degrees in Paris. "), ("token", "A good day for a walk.")],
        ]
    )
    tools = ToolRegistry()
    tools.register(_Catalog())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    bus = EventBus()
    loop = AgentLoop(
        bus, router, tools, SessionMemory(), "persona", cfg,  # type: ignore[arg-type]
        request_confirm=_deny, is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("what is the weather in Paris right now?", "fast"))
    deltas = [str(e.payload.get("text") or "") for e in events if e.type == EventType.ASSISTANT_DELTA]
    assert "".join(deltas) == "It is sunny and 18 degrees in Paris. A good day for a walk."
    assert len(deltas) >= 2

    # A withdrawn chunk is already on the TTS buffer when the real reply is
    # queued. Speech is the reply alone; the withdrawn word is not glued on.
    reply = "Boston is sunny today."
    spoken = await _spoken_after_withdrawn_chunk(reply)
    assert spoken == [reply]


async def _spoken_after_withdrawn_chunk(reply: str) -> list[str]:
    """Publish withdraw-then-reply the way the bus does: all queued, then handled."""
    from arelis.voice import VoiceService

    class _FakeTTS:
        def __init__(self) -> None:
            self.spoken: list[str] = []

        def problem(self) -> None:
            return None

        async def synthesize(self, text: str, out: Path, language: str = "") -> Path:
            self.spoken.append(text)
            path = Path(out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"RIFF")
            return path

    bus = EventBus()
    voice = VoiceService(
        bus, {"voice": {"enabled": True, "tts": {"enabled": True, "backend": "piper"}}}
    )
    voice.speak_enabled = True
    fake = _FakeTTS()
    voice.tts = fake  # type: ignore[assignment]
    task = asyncio.create_task(bus.run())
    for event in (
        Event(EventType.ASSISTANT_DELTA, {"text": "done"}),
        Event(EventType.ASSISTANT_RETRACT, {}),
        Event(EventType.ASSISTANT_DELTA, {"text": reply}),
        Event(EventType.VOICE_SPEAK, {"text": reply}),
    ):
        bus.publish_nowait(event)
    await bus.drain()
    bus.stop()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    return list(fake.spoken)
