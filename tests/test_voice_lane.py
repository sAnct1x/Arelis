"""Spoken first pass skips tool schemas; a tool signal hands off; typed is unchanged."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

import arelis.core.agent_loop as agent_loop_mod
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.voice_lane import (
    FILLER_EN,
    NEED_TOOL_MARKER,
    first_pass_needs_tool,
    lane_enabled,
)
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect


class _Clock(datetime):
    when = datetime(2026, 11, 10, 17, 40)

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return cls.when
        return cls.when.replace(tzinfo=tz)


class _Tool:
    description = "probe"
    risk = "read"
    parameters_schema = {"type": "object", "properties": {}}

    def __init__(self, name: str) -> None:
        self.name = name

    async def run(self, **kwargs):
        del kwargs
        return ToolResult(ok=True, output="ok")


class _RecordingRouter:
    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        self.script = script
        self.i = 0
        self.sent: list[tuple[list, Any, dict]] = []
        self.active_model = None

    def model_for(self, role=None):
        del role
        return "probe-model"

    async def stream(self, role, messages, **kwargs):
        del role
        self.sent.append(
            (json.loads(json.dumps(messages)), kwargs.get("tools"), dict(kwargs))
        )
        steps = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        for item in steps:
            yield item


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    for name in ("weather", "web_search", "calculator", "catalog"):
        registry.register(_Tool(name))  # type: ignore[arg-type]
    return registry


def _config(*, speak: bool = False, lane: bool | None = True, voice: bool = False) -> dict[str, Any]:
    voice_cfg: dict[str, Any] = {
        "enabled": voice,
        "tts": {"enabled": True},
    }
    if lane is not None:
        voice_cfg["lane"] = {"enabled": lane}
    return {
        "agent": {
            "chat_fast_path": False,
            "lessons": True,
            "max_rounds": 4,
            "json_fallback": False,
        },
        "llamacpp": {"default_cap": 32768},
        "voice": voice_cfg,
        "_speak_replies": speak,
        "_persona_path": "does-not-exist.md",
    }


def _loop(router: _RecordingRouter, cfg: dict[str, Any]) -> AgentLoop:
    return AgentLoop(
        EventBus(),
        router,  # type: ignore[arg-type]
        _registry(),
        SessionMemory(),
        "PERSONA",
        cfg,
        request_confirm=lambda *_: False,
        is_cancelled=lambda: False,
    )


def _stable_leading(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cacheable voice-lane prefix: system lines before history or the clock."""
    out: list[dict[str, Any]] = []
    for message in messages:
        if message.get("role") == "user":
            break
        content = str(message.get("content") or "")
        if content.startswith(("Right now it is ", "World state:", "Turn goal:")):
            break
        if content.startswith("## Lessons"):
            break
        out.append(message)
    return out


def _event_blob(events: list[Event]) -> str:
    parts: list[str] = []
    for event in events:
        payload = event.payload or {}
        parts.append(str(payload.get("text") or payload.get("message") or payload))
    return "\n".join(parts)


def _request_fingerprint(sent: list[tuple[list, Any, dict]]) -> str:
    rows = []
    for messages, tools, kwargs in sent:
        rows.append(
            {
                "messages": messages,
                "tools": tools,
                "think": kwargs.get("think"),
                "options": kwargs.get("options"),
            }
        )
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


@pytest.mark.asyncio
async def test_spoken_turn_has_no_tools_and_a_stable_prefix(monkeypatch) -> None:
    """Two spoken follow-ups omit schemas and share the same system prefix."""
    monkeypatch.setattr(agent_loop_mod, "datetime", _Clock)
    router = _RecordingRouter(
        [
            [("token", "Paris.")],
            [("token", "A fox found a quiet hill and watched the stars.")],
        ]
    )
    loop = _loop(router, _config(speak=True, lane=True, voice=False))
    await loop.run("What's the capital of France?", "fast")
    await loop.run("Tell me a very short story.", "fast")
    assert len(router.sent) == 2
    first_messages, first_tools, first_kwargs = router.sent[0]
    second_messages, second_tools, second_kwargs = router.sent[1]
    assert first_tools is None
    assert second_tools is None
    assert first_kwargs.get("think") is False
    assert second_kwargs.get("think") is False
    first_prefix = _stable_leading(first_messages)
    second_prefix = _stable_leading(second_messages)
    assert first_prefix == second_prefix
    assert first_prefix, "voice-lane prefix should not be empty"
    assert first_messages[: len(first_prefix)] == first_prefix
    assert second_messages[: len(second_prefix)] == second_prefix
    blob = json.dumps(first_prefix)
    assert "PERSONA" not in blob
    assert "STATIC_TOOL_POLICY" not in blob
    assert NEED_TOOL_MARKER in blob
    users = [m.get("content") for m in first_messages if m.get("role") == "user"]
    assert any("capital of France" in str(c) for c in users)

    # Default is off: a spoken turn with no lane key must send today's request.
    shipped = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "arelis" / "config" / "default.yaml").read_text()
    )
    assert lane_enabled(shipped) is False

    async def _spoken_fingerprint(*, lane: bool | None) -> str:
        probe = _RecordingRouter([[("token", "Paris.")]])
        await _loop(probe, _config(speak=True, lane=lane, voice=False)).run(
            "What's the capital of France?", "fast"
        )
        assert len(probe.sent) == 1
        _messages, tools, _kwargs = probe.sent[0]
        assert tools, "today's spoken request still carries the session tool schemas"
        return _request_fingerprint(probe.sent)

    assert await _spoken_fingerprint(lane=None) == await _spoken_fingerprint(lane=False)


@pytest.mark.asyncio
async def test_tool_needed_marker_triggers_filler_and_handoff_without_speaking_it() -> None:
    """NEED_TOOL is never shown or spoken; the same user turn then gets full tools."""
    assert first_pass_needs_tool("NEED_TOOL")
    assert first_pass_needs_tool("```\nNEED_TOOL\n```")
    for form in (
        "NEED_TOOL!",
        "NEED_TOOL?",
        "NEED_TOOL:",
        "NEED_TOOL,",
        "NEED_TOOL...",
        "NEED_TOOL。",
        "need_tool!",
    ):
        assert first_pass_needs_tool(form), form
    assert not first_pass_needs_tool("Paris is the capital of France.")
    assert not first_pass_needs_tool(
        "You may NEED_TOOL if the hours are missing."
    )

    async def _assert_library_handoff(first_tokens: list[tuple[str, Any]]) -> None:
        router = _RecordingRouter(
            [
                first_tokens,
                [("token", "The downtown library closes at 6 tonight.")],
            ]
        )
        cfg = _config(speak=True, lane=True, voice=True)
        loop = _loop(router, cfg)
        events = await _collect(
            loop.bus,
            loop.run("How late is the downtown library open tonight?", "fast"),
        )
        assert len(router.sent) >= 2
        first_messages, first_tools, _first_kwargs = router.sent[0]
        second_messages, second_tools, _second_kwargs = router.sent[1]
        assert first_tools is None
        assert second_tools, "handoff must send the session tool schemas"
        assert any(
            (item.get("function") or item).get("name") == "weather"
            for item in second_tools
        )
        # Same user turn, not a second copy of the ask as a new history item.
        first_users = [m for m in first_messages if m.get("role") == "user"]
        second_users = [m for m in second_messages if m.get("role") == "user"]
        assert first_users
        assert second_users
        assert "library" in str(first_users[-1].get("content")).lower()
        assert "library" in str(second_users[-1].get("content")).lower()

        blob = _event_blob(events)
        assert NEED_TOOL_MARKER not in blob
        deltas = [
            str((event.payload or {}).get("text") or "")
            for event in events
            if event.type == EventType.ASSISTANT_DELTA
        ]
        assert all(NEED_TOOL_MARKER not in text for text in deltas)
        speak_texts = [
            str((event.payload or {}).get("text") or "")
            for event in events
            if event.type == EventType.VOICE_SPEAK
        ]
        assert speak_texts[0] == FILLER_EN
        assert all(NEED_TOOL_MARKER not in text for text in speak_texts)
        done = [
            str((event.payload or {}).get("text") or "")
            for event in events
            if event.type == EventType.ASSISTANT_DONE
        ]
        assert done == ["The downtown library closes at 6 tonight."]
        assert FILLER_EN not in done[0]

        users = [m.content for m in loop.memory.messages if m.role == "user"]
        assistants = [m.content for m in loop.memory.messages if m.role == "assistant"]
        assert users == ["How late is the downtown library open tonight?"]
        assert assistants == ["The downtown library closes at 6 tonight."]
        assert all(
            NEED_TOOL_MARKER not in (m.content or "") for m in loop.memory.messages
        )

    await _assert_library_handoff([("token", "NEED_TOOL")])
    # Repro: a trailing bang must hand off, not be spoken or stored as the answer.
    await _assert_library_handoff([("token", "NEED_TOOL!")])
    # Mid-stream marker then punctuation must stay held (no bubble or speaker leak).
    await _assert_library_handoff([("token", "NEED_TOOL"), ("token", "!")])
