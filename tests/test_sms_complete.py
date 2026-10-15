"""SMS draft completion across turns."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import ChatMessage, SessionMemory
from arelis.core.sms_complete import (
    complete_sms_draft,
    fill_send_sms_args,
    parse_sms_utterance,
)
from arelis.tools.base import ToolRegistry, ToolResult


def _book(**people: dict) -> dict[str, Contact]:
    out: dict[str, Contact] = {}
    for alias, fields in people.items():
        phone = str(fields.get("phone") or "5551112222")
        raw_aliases = fields.get("aliases") or ()
        if isinstance(raw_aliases, str):
            raw_aliases = (raw_aliases,)
        out[alias] = Contact(
            alias=alias,
            name=str(fields.get("name") or ""),
            phone=phone,
            digits=normalize_phone(phone),
            aliases=tuple(str(a).lower() for a in raw_aliases),
        )
    return out


def test_parse_text_a_raw_number_and_tell_him() -> None:
    """A number the user typed is the recipient. Letter-only `to` hid send_sms."""
    draft = parse_sms_utterance(
        "chillin, chillin, i want you to text 5551112222 and tell him hes late"
    )
    assert draft is not None
    assert draft.complete
    assert "5551112222" in draft.to
    assert "late" in draft.body.lower()
    filled = fill_send_sms_args({}, draft)
    assert filled["to"] == "5551112222"
    assert "late" in filled["body"].lower()


def test_text_message_to_wife_is_not_to_message() -> None:
    """STT often drops 'send a' and hears 'in a text message to my wife'."""
    book = _book(wife={"name": "Robin", "aliases": ("wife", "robbie")})
    spoken = (
        "in a text message to my wife and just tell her "
        "good nights, sweet dreams"
    )
    draft = parse_sms_utterance(spoken)
    assert draft is not None
    assert draft.to.lower() == "wife"
    assert "message" not in draft.to.lower()
    assert "good night" in draft.body.lower()
    done = complete_sms_draft(spoken, contacts=book)
    assert done is not None
    assert done.complete
    assert done.tool_to == "wife"
    assert "sweet dreams" in done.body.lower()
    filled = fill_send_sms_args(
        {"to": "message", "body": "good nights, sweet dreams"},
        done,
        contacts=book,
    )
    assert filled["to"] == "wife"


def test_contacts_phone_and_proceed_are_lookups() -> None:
    from arelis.core.sms_complete import (
        looks_like_contacts_followup,
        looks_like_contacts_utterance,
    )

    assert looks_like_contacts_utterance("Who is my wife in my contacts?")
    assert looks_like_contacts_utterance("what is my wifes phone number?")
    assert looks_like_contacts_utterance("What is her phone number?")
    from arelis.core.sms_complete import looks_like_contact_phone_ask

    assert looks_like_contact_phone_ask("what is her phone number?")
    assert looks_like_contact_phone_ask("what is my wifes phone number?")
    assert not looks_like_contact_phone_ask("Who is my wife in my contacts?")
    history = [
        ChatMessage(role="user", content="Who is my wife in my contacts?"),
        ChatMessage(role="assistant", content="I would need to call the tool."),
    ]
    assert looks_like_contacts_followup("proceed", history)
    assert not looks_like_contacts_followup("proceed")


class _SmsStub:
    name = "send_sms"
    description = "sms"
    risk = "side_effect"
    parameters_schema = {
        "type": "object",
        "properties": {"to": {}, "body": {}},
        "required": ["to", "body"],
    }

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(dict(kwargs))
        return ToolResult(ok=True, output="queued", data=dict(kwargs))


class _Router:
    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        self.script = script
        self.i = 0
        self.active_model = "mock"
        self.default_role = "fast"

    def model_for(self, role=None) -> str:
        return "mock"

    async def ensure_role(self, role, *, force: bool = False) -> str:
        del force
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    async def stream(self, role, messages, **kwargs):
        steps = self.script[self.i]
        self.i += 1
        for item in steps:
            yield item


async def _allow(*_a: Any, **_k: Any) -> str:
    return "allow"


@pytest.mark.asyncio
async def test_loop_confirms_when_the_model_calls_send_sms(monkeypatch) -> None:
    """A model that calls send_sms still hits Allow. Nothing is invented if it only talks."""
    book = _book(brian={"name": "Brian", "aliases": ("brian",)})
    monkeypatch.setattr(
        "arelis.core.sms_complete.load_contacts", lambda: book
    )
    monkeypatch.setattr(
        "arelis.core.preflight.complete_sms_draft",
        lambda text, history=None, contacts=None: complete_sms_draft(
            text, history=history, contacts=book
        ),
    )

    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    tools = ToolRegistry()
    sms = _SmsStub()
    tools.register(sms)

    router = _Router(
        [
            [
                (
                    "tool_calls",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "send_sms",
                                "arguments": {
                                    "to": "brian",
                                    "body": "WRONG",
                                },
                            },
                        }
                    ],
                )
            ],
            [("token", "Confirm card is up.")],
        ]
    )
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 6,
                "tool_output_chars": 4000,
                "confirm_send": True,
                "json_fallback": True,
                "skill_cards": True,
                "intent_preflight": True,
                "sms_force_call": True,
                "sms_preinject": False,
                "turn_telemetry": False,
            },
            "ollama": {"num_ctx": 8192},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    task = asyncio.create_task(bus.run())
    try:
        await loop.run("Text Brian: Running late", "fast")
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    starts = [e.payload.get("tool") for e in events if e.type == EventType.TOOL_START]
    assert starts == ["send_sms"]
    assert sms.calls
    assert sms.calls[0]["to"] == "brian"
    assert "late" in str(sms.calls[0].get("body") or "").lower()
    assert "WRONG" not in str(sms.calls[0].get("body") or "")


@pytest.mark.asyncio
async def test_a_model_send_sms_still_asks_allow_and_locks_the_body(
    monkeypatch,
) -> None:
    """Allow still gates the send. The draft body wins over a wrong tool argument."""
    book = _book(wife={"name": "Robin", "aliases": ("wife",)})
    monkeypatch.setattr("arelis.core.sms_complete.load_contacts", lambda: book)
    monkeypatch.setattr(
        "arelis.core.preflight.complete_sms_draft",
        lambda text, history=None, contacts=None: complete_sms_draft(
            text, history=history, contacts=book
        ),
    )

    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    tools = ToolRegistry()
    sms = _SmsStub()
    tools.register(sms)
    asked: list[dict[str, Any]] = []

    async def confirm(confirm_id, tool, args, summary) -> str:
        asked.append({"tool": tool, "args": dict(args)})
        return "allow"

    # The model calls send_sms. Allow still has to happen, and the body stays
    # the draft, not whatever the call invented.
    router = _Router(
        [
            [
                (
                    "tool_calls",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "send_sms",
                                "arguments": {
                                    "to": "wife",
                                    "body": "WRONG",
                                },
                            },
                        }
                    ],
                )
            ],
            [("token", "Confirm card is up.")],
        ]
    )
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 6,
                "tool_output_chars": 4000,
                "confirm_send": True,
                "json_fallback": True,
                "skill_cards": True,
                "intent_preflight": True,
                "sms_force_call": True,
                "turn_telemetry": False,
            },
            "ollama": {"num_ctx": 8192},
        },
        request_confirm=confirm,
        is_cancelled=lambda: False,
    )
    task = asyncio.create_task(bus.run())
    try:
        await loop.run("Send a text to my wife telling her I love her", "fast")
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert [a["tool"] for a in asked] == ["send_sms"], "Allow must still be asked"
    assert asked[0]["args"]["to"] == "wife"
    assert "love" in asked[0]["args"]["body"].lower()
    assert "WRONG" not in asked[0]["args"]["body"]
    assert sms.calls and sms.calls[0]["to"] == "wife"
    assert router.i >= 1
    done = [e for e in events if e.type == EventType.ASSISTANT_DONE]
    assert done and "Sent your text" in str(done[-1].payload.get("text") or "")


@pytest.mark.asyncio
async def test_a_ready_send_says_why_send_sms_is_unavailable(monkeypatch) -> None:
    """Missing capability has two causes and they need different fixes."""
    book = _book(wife={"name": "Robin", "aliases": ("wife",)})
    monkeypatch.setattr("arelis.core.sms_complete.load_contacts", lambda: book)
    monkeypatch.setattr(
        "arelis.core.preflight.complete_sms_draft",
        lambda text, history=None, contacts=None: complete_sms_draft(
            text, history=history, contacts=book
        ),
    )

    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    # send_sms is not registered at all — the Notify account is absent.
    tools = ToolRegistry()
    router = _Router([[("token", "I cannot text from here.")]])
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 2,
                "tool_output_chars": 4000,
                "confirm_send": True,
                "json_fallback": True,
                "intent_preflight": True,
                "sms_force_call": True,
                "turn_telemetry": False,
            },
            "ollama": {"num_ctx": 8192},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    task = asyncio.create_task(bus.run())
    try:
        await loop.run("Send a text to my wife telling her I love her", "fast")
        await bus.drain()
    finally:
        bus.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    done = [e for e in events if e.type == EventType.ASSISTANT_DONE]
    assert done
    text = str(done[-1].payload.get("text") or "")
    assert "Settings → Notify" in text
    assert "scan the QR" in text
    assert router.i == 0


def test_yes_comma_please_confirms_sms_draft() -> None:
    book = _book(wife={"name": "Robin", "aliases": ("wife",)})
    history = [
        ChatMessage(
            role="user",
            content="Text my wife and say, hey, grocery test, please ignore",
        ),
        ChatMessage(
            role="assistant",
            content="Would you like me to proceed with sending this message?",
        ),
    ]
    done = complete_sms_draft("Yes, please", history=history, contacts=book)
    assert done is not None and done.complete
    assert done.tool_to == "wife"
    assert "grocery test" in done.body.lower()


