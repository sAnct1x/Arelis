"""A no on the confirm card is a no, not a missing tool."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.core.turn_confirm import SKIP, confirm_call
from arelis.core.turn_context import TurnContext
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config


class _Bus:
    async def publish(self, event: Any) -> None:
        return None


class _Stub:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "stub"
        self.parameters_schema = {"type": "object", "properties": {}}
        self.risk = "write"

    async def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(ok=True, output="ok")


class _Loop:
    def __init__(self, *names: str) -> None:
        tools = ToolRegistry()
        for name in names:
            tools.register(_Stub(name))
        self.bus = _Bus()
        self.tools = tools
        self.memory = None
        self._trace: list[str] = []
        self._expected_tools: set[str] = set()
        self._look = None
        self._timer = None
        self.confirm_writes = True
        self.confirm_image = True
        self.confirm_send = True
        self.confirm_browser = True
        self.confirm_desktop = True
        self.confirm_vision = True
        self.confirm_run = True
        self.ask_is_grant = True
        self.tools_used: set[str] = set()
        self.request_confirm = AsyncMock(return_value="skip")

    def _tool_message(self, name: str, content: str) -> dict[str, Any]:
        return {"role": "tool", "name": name, "content": content}

    async def _confirm_wait_heartbeat(self, name: str, started: float) -> None:
        await asyncio.sleep(3600)


def _note(messages: list[dict[str, Any]]) -> str:
    assert messages, "a denied call must leave a tool result for the model"
    return str(messages[-1]["content"])


def _says_they_said_no(text: str) -> None:
    lowered = text.lower()
    assert "said no" in lowered, text
    assert "skipped" in lowered, text
    assert "not available" not in lowered, text
    assert "unavailable" not in lowered, text
    assert "can't" not in lowered, text
    assert "cannot" not in lowered, text


@pytest.mark.asyncio
async def test_a_denied_call_says_the_user_said_no() -> None:
    """The note after a no must not read as 'that tool is missing'.

    Bench runs turned a declined agenda write into 'the agenda tool isn't
    available this turn' and a declined inbox delete into 'I can't delete
    emails from your inbox directly'. Both are the user saying no.
    """
    agenda = _Loop("agenda")
    agenda_messages: list[dict[str, Any]] = []
    action, _summary, _fp = await confirm_call(
        agenda,
        TurnContext(text="add lunch to my calendar", role="fast"),
        "agenda",
        {
            "action": "create",
            "summary": "Lunch",
            "start": "2026-10-12T12:00:00",
        },
        text="add lunch to my calendar",
        fail_counts={},
        skip_counts={},
        messages=agenda_messages,
        drop_wander=lambda _name: None,
    )
    assert action == SKIP
    agenda_note = _note(agenda_messages)
    assert "agenda" in agenda_note.lower()
    _says_they_said_no(agenda_note)

    inbox = _Loop("inbox")
    inbox._expected_tools.add("inbox")
    inbox_messages: list[dict[str, Any]] = []
    action, _summary, _fp = await confirm_call(
        inbox,
        TurnContext(text="delete that email", role="fast"),
        "inbox",
        {"action": "trash", "id": "11"},
        text="delete that email",
        fail_counts={},
        skip_counts={},
        messages=inbox_messages,
        drop_wander=lambda _name: None,
    )
    assert action == SKIP
    inbox_note = _note(inbox_messages)
    assert "inbox" in inbox_note.lower()
    _says_they_said_no(inbox_note)


def _call(name: str, arguments: dict[str, Any]) -> tuple[str, Any]:
    return (
        "tool_calls",
        [
            {
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    )


class _RecordingRouter:
    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        self.script = script
        self.i = 0
        self.seen: list[list[dict[str, Any]]] = []
        self.default_role = "fast"
        self.active_model = None
        self.active_role = None
        self.models = {"fast": "mock", "research": "mock", "code": "mock"}

    def model_for(self, role: Any = None) -> str:
        del role
        return "mock"

    async def ensure_role(self, role: Any, *, force: bool = False) -> str:
        del force
        self.active_role = role
        self.active_model = "mock"
        return "mock"

    def mark_sticky(self, role: Any) -> None:
        del role

    def apply_sticky(self, wanted: Any, reason: str) -> tuple[Any, str]:
        return wanted, reason

    async def stream(self, role: Any, messages: list[dict[str, Any]], **kwargs: Any):
        del role, kwargs
        self.seen.append([dict(item) for item in messages])
        steps = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        for item in steps:
            yield item


class _NamedStub:
    def __init__(self, name: str, risk: str) -> None:
        self.name = name
        self.description = name
        self.risk = risk
        self.parameters_schema = {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "body": {"type": "string"},
                "action": {"type": "string"},
                "fact": {"type": "string"},
                "path": {"type": "string"},
                "prompt": {"type": "string"},
                "query": {"type": "string"},
                "remove_background": {"type": "boolean"},
            },
        }
        self.runs = 0

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        self.runs += 1
        return ToolResult(ok=True, output=f"{self.name} ok")


def _tool_blobs(seen: list[list[dict[str, Any]]]) -> list[str]:
    blobs: list[str] = []
    for messages in seen:
        for row in messages:
            if row.get("role") == "tool":
                blobs.append(str(row.get("content") or ""))
    return blobs


@pytest.mark.asyncio
async def test_a_declined_card_is_not_a_missing_tool_or_a_standing_no() -> None:
    """A no is about that call.

    Declining the follow-up image card used to hide image, and the next
    call was told the tool was unknown and that web_search was available.
    Declining a send used to leave "declined by user" on the next turn,
    and a remember prompt was treated as already refused.
    """
    cards: list[str] = []

    async def confirm(
        cid: str, tool: str, args: dict[str, Any], summary: str
    ) -> str:
        del cid, args, summary
        cards.append(tool)
        if tool in {"image_edit", "memory"}:
            return "allow"
        return "skip"

    edit = _NamedStub("image_edit", "side_effect")
    image = _NamedStub("image", "side_effect")
    web = _NamedStub("web_search", "read")
    vision = _NamedStub("vision", "read")
    registry = ToolRegistry()
    for tool in (edit, image, web, vision):
        registry.register(tool)
    router = _RecordingRouter(
        [
            [_call("image_edit", {"path": "photo.png", "remove_background": True})],
            [_call("image", {"path": "photo.png", "remove_background": True})],
            [_call("image", {"path": "photo.png", "remove_background": True})],
            [_call("web_search", {"query": "background removal"})],
            [("token", "The background is removed.")],
        ]
    )
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 6
    cfg["agent"]["native_tool_calling"] = False
    memory = SessionMemory()
    loop = AgentLoop(
        EventBus(),
        router,  # type: ignore[arg-type]
        registry,
        memory,
        "persona",
        cfg,
        request_confirm=confirm,
        is_cancelled=lambda: False,
    )
    await _collect(
        loop.bus,
        loop.run("Remove the background from this photo", "fast"),
    )
    blobs = _tool_blobs(router.seen)
    assert edit.runs == 1
    assert image.runs == 0
    assert cards.count("image") == 1
    assert any("said no" in blob.lower() and "image" in blob.lower() for blob in blobs)
    for blob in blobs:
        lowered = blob.lower()
        assert "unknown tool" not in lowered, blob
        assert "available:" not in lowered, blob
        assert "what they would prefer" not in lowered, blob
        assert "do not call it again" not in lowered, blob
        if "said no" in lowered:
            assert "web_search" not in lowered, blob

    send = _NamedStub("send_sms", "side_effect")
    remember = _NamedStub("memory", "write")
    send_registry = ToolRegistry()
    send_registry.register(send)
    send_registry.register(remember)
    send_router = _RecordingRouter(
        [[_call("send_sms", {"to": "mom", "body": "hello"})]]
    )
    send_memory = SessionMemory()
    send_loop = AgentLoop(
        EventBus(),
        send_router,  # type: ignore[arg-type]
        send_registry,
        send_memory,
        "persona",
        cfg,
        request_confirm=confirm,
        is_cancelled=lambda: False,
    )
    send_events = await _collect(send_loop.bus, send_loop.run("Text mom hello", "fast"))
    send_done = next(
        event.payload.get("text")
        for event in send_events
        if event.type == EventType.ASSISTANT_DONE
    )
    assert send.runs == 0
    assert send_done == "Okay, I did not send that."
    notes = [item.note for item in send_memory.messages if item.note]
    assert notes and all("declined" not in note.lower() for note in notes)

    next_router = _RecordingRouter(
        [
            [_call("memory", {"action": "remember", "fact": "olives"})],
            [("token", "Saved olives.")],
        ]
    )
    next_loop = AgentLoop(
        EventBus(),
        next_router,  # type: ignore[arg-type]
        send_registry,
        send_memory,
        "persona",
        cfg,
        request_confirm=confirm,
        is_cancelled=lambda: False,
    )
    await _collect(
        next_loop.bus,
        next_loop.run("Remember that I like olives", "fast"),
    )
    assert remember.runs == 1
    prompt = "\n".join(
        str(row.get("content") or "")
        for messages in next_router.seen
        for row in messages
    )
    assert "declined" not in prompt.lower()
