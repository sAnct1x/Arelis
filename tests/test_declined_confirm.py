"""A no on the confirm card is a no, not a missing tool."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from arelis.core.turn_confirm import SKIP, confirm_call
from arelis.core.turn_context import TurnContext
from arelis.tools.base import ToolRegistry, ToolResult


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
