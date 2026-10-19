"""A reply may not say a file was made when this turn never made one.

The live miss: analyze printed the region totals, no spreadsheet was written,
and the reply still said the Excel file had been created. A real file this
turn may say so. An offer, a refusal, or a file from another turn stays as
written.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config, _ScriptedRouter

_ASK = "Add up revenue by region in my sales sheet and make an Excel file called Region Totals"
_CLAIM = (
    "I've created the Region Totals Excel file with revenue sums for each "
    "region: east 100, north 250, south 250, and west 150."
)
_NUDGE = "No file was made yet."


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


class _RecordingRouter(_ScriptedRouter):
    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        super().__init__(script)
        self.seen: list[str] = []

    async def stream(self, role, messages, **kwargs):
        parts: list[str] = []
        for item in messages:
            content = item.get("content") if isinstance(item, dict) else None
            if isinstance(content, str):
                parts.append(content)
        self.seen.append("\n".join(parts))
        async for item in super().stream(role, messages, **kwargs):
            yield item


class _Analyze:
    name = "analyze"
    description = "Read a table."
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "action": {"type": "string"}},
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(
            ok=True,
            output=("5 of 5 rows matched. region revenue east 100 north 250 south 250 west 150"),
        )


class _Document:
    name = "document"
    description = "Write a file."
    risk = "write"
    parameters_schema = {
        "type": "object",
        "properties": {
            "format": {"type": "string"},
            "title": {"type": "string"},
            "body": {"type": "string"},
        },
    }

    def __init__(self) -> None:
        self.calls = 0

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        self.calls += 1
        return ToolResult(ok=True, output="Wrote the spreadsheet.")


async def _allow(*_args: Any, **_kwargs: Any) -> str:
    return "allow"


def _loop(router: _RecordingRouter, document: _Document, *, native: bool) -> AgentLoop:
    tools = ToolRegistry()
    tools.register(_Analyze())
    tools.register(document)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["confirm_writes"] = False
    cfg["agent"]["native_tool_calling"] = native
    cfg["agent"]["json_fallback"] = True
    cfg["agent"]["max_rounds"] = 6
    return AgentLoop(
        EventBus(),
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )


async def _reply(loop: AgentLoop, bus: EventBus, text: str = _ASK) -> str:
    events = await _collect(bus, loop.run(text, "fast"))
    done = next(event for event in events if event.type == EventType.ASSISTANT_DONE)
    return str(done.payload.get("text") or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [True, False])
async def test_a_false_file_claim_is_nudged_then_kept_when_the_file_is_made(
    native: bool,
) -> None:
    """Analyze, a created-file claim, then a real spreadsheet. The claim stays."""
    document = _Document()
    router = _RecordingRouter(
        [
            [_call("analyze", {"action": "summary", "path": "work/sales.csv"})],
            [("token", _CLAIM)],
            [
                _call(
                    "document",
                    {
                        "format": "xlsx",
                        "title": "Region Totals",
                        "body": "east 100, north 250, south 250, west 150",
                    },
                )
            ],
            [("token", _CLAIM)],
        ]
    )
    loop = _loop(router, document, native=native)
    text = await _reply(loop, loop.bus)
    assert any(_NUDGE in blob for blob in router.seen), router.seen
    assert document.calls == 1
    assert "created" in text.casefold()
    assert "north 250" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [True, False])
async def test_a_repeated_file_claim_admits_nothing_was_saved(native: bool) -> None:
    """The model ignores the nudge and claims the file again."""
    document = _Document()
    router = _RecordingRouter(
        [
            [_call("analyze", {"action": "summary", "path": "work/sales.csv"})],
            [("token", _CLAIM)],
            [("token", _CLAIM)],
        ]
    )
    loop = _loop(router, document, native=native)
    text = await _reply(loop, loop.bus)
    assert any(_NUDGE in blob for blob in router.seen), text
    assert document.calls == 0
    assert "created" not in text.casefold()
    assert "did not make" in text.casefold()
    assert "north 250" in text


@pytest.mark.asyncio
async def test_a_file_made_this_turn_may_say_it_was_created() -> None:
    document = _Document()
    router = _RecordingRouter(
        [
            [
                _call(
                    "document",
                    {
                        "format": "xlsx",
                        "title": "Region Totals",
                        "body": "east 100",
                    },
                )
            ],
            [("token", "I've created the file.")],
        ]
    )
    loop = _loop(router, document, native=True)
    text = await _reply(loop, loop.bus, "Save the region totals for me.")
    assert document.calls == 1
    assert text == "I've created the file."
    assert all(_NUDGE not in blob for blob in router.seen)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        "I can create a spreadsheet with these if you want.",
        "Want me to save this as a PDF?",
        "The spreadsheet you created yesterday has 4 rows.",
        "I didn't create a file; here are the totals.",
    ],
)
async def test_offers_and_old_files_are_not_treated_as_a_new_file(reply: str) -> None:
    document = _Document()
    router = _RecordingRouter([[("token", reply)]])
    tools = ToolRegistry()
    tools.register(_Analyze())
    tools.register(document)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["confirm_writes"] = False
    cfg["agent"]["native_tool_calling"] = True
    cfg["agent"]["exactness"] = False
    cfg["agent"]["numeric_gate"] = False
    cfg["agent"]["evidence_gate"] = False
    bus = EventBus()
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("Tell me what you would do with this.", "fast"))
    done = next(event for event in events if event.type == EventType.ASSISTANT_DONE)
    text = str(done.payload.get("text") or "")
    assert text == reply
    assert router.i == 1
    assert document.calls == 0
    assert all(_NUDGE not in blob for blob in router.seen)


async def _untouched_reply(reply: str, *, native: bool) -> tuple[str, _RecordingRouter]:
    """One plain answer, no file written. Other gates stay off."""
    document = _Document()
    router = _RecordingRouter([[("token", reply)]])
    tools = ToolRegistry()
    tools.register(_Analyze())
    tools.register(document)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["confirm_writes"] = False
    cfg["agent"]["native_tool_calling"] = native
    cfg["agent"]["exactness"] = False
    cfg["agent"]["numeric_gate"] = False
    cfg["agent"]["evidence_gate"] = False
    bus = EventBus()
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("Tell me what you would do with this.", "fast"))
    done = next(event for event in events if event.type == EventType.ASSISTANT_DONE)
    return str(done.payload.get("text") or ""), router


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [True, False])
async def test_a_calendar_event_is_not_a_file_claim(native: bool) -> None:
    reply = "I created a calendar event for the quarterly report review on Friday."
    text, router = await _untouched_reply(reply, native=native)
    assert text == reply
    assert router.i == 1
    assert all(_NUDGE not in blob for blob in router.seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [True, False])
async def test_a_report_written_below_stays_in_the_reply(native: bool) -> None:
    reply = "I've written a short report below. Revenue rose 10 percent."
    text, router = await _untouched_reply(reply, native=native)
    assert text == reply
    assert router.i == 1
    assert all(_NUDGE not in blob for blob in router.seen)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        "I made a few edits to the document you shared.",
        "I wrote a summary of the PDF you sent: sales rose.",
        "I saved the document you shared.",
    ],
)
async def test_a_file_the_user_provided_is_not_a_new_file(reply: str) -> None:
    text, router = await _untouched_reply(reply, native=True)
    assert text == reply
    assert router.i == 1
    assert all(_NUDGE not in blob for blob in router.seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [True, False])
async def test_a_file_from_last_time_is_not_a_new_file(native: bool) -> None:
    reply = "Here is the file I made last time."
    text, router = await _untouched_reply(reply, native=native)
    assert text == reply
    assert router.i == 1
    assert all(_NUDGE not in blob for blob in router.seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [True, False])
async def test_making_a_list_after_reading_a_file_is_not_a_file_claim(native: bool) -> None:
    reply = "I read the file and I made a list: apples 3, pears 4."
    text, router = await _untouched_reply(reply, native=native)
    assert text == reply
    assert router.i == 1
    assert all(_NUDGE not in blob for blob in router.seen)
