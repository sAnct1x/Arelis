"""Answer path applies the dash filter end to end (no mock of the filter)."""

from __future__ import annotations

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.core.turn_telemetry import TurnTimer
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
async def test_streamed_answer_unspaced_em_dash_token() -> None:
    bus = EventBus()
    router = _ScriptedRouter([[("token", "yes"), ("token", EM), ("token", "no")]])
    tools = ToolRegistry()
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
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
    assert "".join(deltas) == "yes, no"


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
async def test_finish_marks_dash_filter_telemetry() -> None:
    loop = _loop_with_tools(_ScriptedRouter(["ignored"]))
    loop._timer = TurnTimer(
        source="eval", role="fast", speak=False, user_chars=5, enabled=False
    )
    seen: list[dict[str, object]] = []
    original = loop._timer.mark

    def _capture(event: str, **fields: object) -> None:
        seen.append({"event": event, **fields})
        original(event, **fields)

    loop._timer.mark = _capture  # type: ignore[method-assign]
    await _collect(loop.bus, loop._finish(f"Hello {EM} world", []))
    marks = [m for m in seen if m.get("event") == "dash_filter"]
    assert marks
    assert int(marks[0].get("replaced") or 0) >= 1
