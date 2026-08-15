"""Confirm-gated SMS auto-reply — never silent send."""

from __future__ import annotations

import asyncio

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.sms_auto_reply import (
    SmsAutoReply,
    contact_allowlisted,
    pick_auto_reply,
)
from arelis.tools.sms_send import SendSmsTool


def _book(**people: dict) -> dict[str, Contact]:
    out: dict[str, Contact] = {}
    for alias, fields in people.items():
        phone = str(fields.get("phone") or "")
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


async def _drain(bus: EventBus) -> asyncio.Task:
    task = asyncio.create_task(bus.run())
    await asyncio.sleep(0)
    return task


async def _stop_bus(bus: EventBus, task: asyncio.Task) -> None:
    bus.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_pick_auto_reply_matches_case_insensitive_substring() -> None:
    rules = [{"match": "On My Way", "reply": "Drive safe."}]
    assert pick_auto_reply("hey, on my way now", rules) == "Drive safe."
    assert pick_auto_reply("hello", rules) is None
    assert pick_auto_reply("hello", rules, default_reply="Got it.") == "Got it."


def test_contact_allowlisted_by_alias_or_phone() -> None:
    book = _book(
        wife={"name": "Robin", "phone": "+15551110000", "aliases": ["robbie"]},
        piper={"name": "Piper", "phone": "+15552220000"},
    )
    loader = lambda: book  # noqa: E731
    assert (
        contact_allowlisted(
            contact_alias="robbie",
            sender="+15551110000",
            allow=["wife"],
            contacts_loader=loader,
        )
        == "wife"
    )
    assert (
        contact_allowlisted(
            contact_alias="",
            sender="555-222-0000",
            allow=["piper"],
            contacts_loader=loader,
        )
        == "piper"
    )
    assert (
        contact_allowlisted(
            contact_alias="wife",
            sender="+15551110000",
            allow=["piper"],
            contacts_loader=loader,
        )
        is None
    )


class _FakeProvider:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send(self, *, phone: str, body: str) -> str:
        self.sent.append((phone, body))
        return "msg-1"


@pytest.mark.asyncio
async def test_auto_reply_publishes_confirm_and_sends_only_after_allow() -> None:
    book = _book(wife={"name": "Robin", "phone": "+15551110000"})
    provider = _FakeProvider()
    tool = SendSmsTool(provider, contacts_loader=lambda: book)  # type: ignore[arg-type]
    bus = EventBus()
    confirms: list[Event] = []
    results: list[Event] = []

    async def capture(event: Event) -> None:
        if event.type == EventType.TOOL_CONFIRM:
            confirms.append(event)
        elif event.type == EventType.TOOL_RESULT:
            results.append(event)

    bus.subscribe(EventType.TOOL_CONFIRM, capture)
    bus.subscribe(EventType.TOOL_RESULT, capture)

    config = {
        "tools": {
            "sms": {
                "auto_reply": {
                    "enabled": True,
                    "contacts": ["wife"],
                    "rules": [{"match": "running late", "reply": "No rush."}],
                }
            }
        }
    }
    auto = SmsAutoReply(bus, config, send_tool=tool, contacts_loader=lambda: book)
    auto.start()
    bus_task = await _drain(bus)
    try:
        await bus.publish(
            Event(
                EventType.SMS_RECEIVED,
                {
                    "id": "in-1",
                    "from": "+15551110000",
                    "body": "Running late!",
                    "contact_alias": "wife",
                    "contact_name": "Robin",
                },
            )
        )
        for _ in range(50):
            if confirms:
                break
            await asyncio.sleep(0.01)
        assert len(confirms) == 1
        assert confirms[0].payload["tool"] == "send_sms"
        assert confirms[0].payload.get("source") == "sms_auto_reply"
        assert provider.sent == []

        confirm_id = confirms[0].payload["id"]
        await bus.publish(
            Event(
                EventType.TOOL_CONFIRM_REPLY,
                {"id": confirm_id, "decision": "allow", "allow_turn": False},
            )
        )
        for _ in range(50):
            if results:
                break
            await asyncio.sleep(0.01)
        assert results and results[0].payload["ok"] is True
        assert provider.sent == [("+15551110000", "No rush.")]
    finally:
        auto.stop()
        await _stop_bus(bus, bus_task)


@pytest.mark.asyncio
async def test_auto_reply_skip_never_calls_provider() -> None:
    book = _book(wife={"name": "Robin", "phone": "+15551110000"})
    provider = _FakeProvider()
    tool = SendSmsTool(provider, contacts_loader=lambda: book)  # type: ignore[arg-type]
    bus = EventBus()
    confirms: list[Event] = []

    async def capture(event: Event) -> None:
        if event.type == EventType.TOOL_CONFIRM:
            confirms.append(event)

    bus.subscribe(EventType.TOOL_CONFIRM, capture)
    config = {
        "tools": {
            "sms": {
                "auto_reply": {
                    "enabled": True,
                    "contacts": ["wife"],
                    "default_reply": "Got your text.",
                }
            }
        }
    }
    auto = SmsAutoReply(bus, config, send_tool=tool, contacts_loader=lambda: book)
    auto.start()
    bus_task = await _drain(bus)
    try:
        await bus.publish(
            Event(
                EventType.SMS_RECEIVED,
                {
                    "id": "in-2",
                    "from": "+15551110000",
                    "body": "hi",
                    "contact_alias": "wife",
                },
            )
        )
        for _ in range(50):
            if confirms:
                break
            await asyncio.sleep(0.01)
        assert confirms
        await bus.publish(
            Event(
                EventType.TOOL_CONFIRM_REPLY,
                {"id": confirms[0].payload["id"], "decision": "skip"},
            )
        )
        await bus.drain()
        await asyncio.sleep(0.05)
        assert provider.sent == []
    finally:
        auto.stop()
        await _stop_bus(bus, bus_task)


@pytest.mark.asyncio
async def test_auto_reply_disabled_by_default() -> None:
    book = _book(wife={"name": "Robin", "phone": "+15551110000"})
    provider = _FakeProvider()
    tool = SendSmsTool(provider, contacts_loader=lambda: book)  # type: ignore[arg-type]
    bus = EventBus()
    confirms: list[Event] = []

    async def capture(event: Event) -> None:
        if event.type == EventType.TOOL_CONFIRM:
            confirms.append(event)

    bus.subscribe(EventType.TOOL_CONFIRM, capture)
    auto = SmsAutoReply(
        bus,
        {
            "tools": {
                "sms": {
                    "auto_reply": {
                        "enabled": False,
                        "contacts": ["wife"],
                        "default_reply": "x",
                    }
                }
            }
        },
        send_tool=tool,
        contacts_loader=lambda: book,
    )
    auto.start()
    bus_task = await _drain(bus)
    try:
        await bus.publish(
            Event(
                EventType.SMS_RECEIVED,
                {
                    "id": "in-3",
                    "from": "+15551110000",
                    "body": "hi",
                    "contact_alias": "wife",
                },
            )
        )
        await bus.drain()
        await asyncio.sleep(0.05)
        assert confirms == []
        assert provider.sent == []
    finally:
        auto.stop()
        await _stop_bus(bus, bus_task)


@pytest.mark.asyncio
async def test_auto_reply_ignores_non_allowlisted_contact() -> None:
    book = _book(
        wife={"name": "Robin", "phone": "+15551110000"},
        other={"name": "Other", "phone": "+15553330000"},
    )
    provider = _FakeProvider()
    tool = SendSmsTool(provider, contacts_loader=lambda: book)  # type: ignore[arg-type]
    bus = EventBus()
    confirms: list[Event] = []

    async def capture(event: Event) -> None:
        if event.type == EventType.TOOL_CONFIRM:
            confirms.append(event)

    bus.subscribe(EventType.TOOL_CONFIRM, capture)
    auto = SmsAutoReply(
        bus,
        {
            "tools": {
                "sms": {
                    "auto_reply": {
                        "enabled": True,
                        "contacts": ["wife"],
                        "default_reply": "Got it.",
                    }
                }
            }
        },
        send_tool=tool,
        contacts_loader=lambda: book,
    )
    auto.start()
    bus_task = await _drain(bus)
    try:
        await bus.publish(
            Event(
                EventType.SMS_RECEIVED,
                {
                    "id": "in-4",
                    "from": "+15553330000",
                    "body": "hi",
                    "contact_alias": "other",
                },
            )
        )
        await bus.drain()
        await asyncio.sleep(0.05)
        assert confirms == []
    finally:
        auto.stop()
        await _stop_bus(bus, bus_task)


@pytest.mark.asyncio
async def test_auto_reply_waits_until_turn_floor_is_free() -> None:
    book = _book(wife={"name": "Robin", "phone": "+15551110000"})
    provider = _FakeProvider()
    tool = SendSmsTool(provider, contacts_loader=lambda: book)  # type: ignore[arg-type]
    bus = EventBus()
    confirms: list[Event] = []

    async def capture(event: Event) -> None:
        if event.type == EventType.TOOL_CONFIRM:
            confirms.append(event)

    bus.subscribe(EventType.TOOL_CONFIRM, capture)
    auto = SmsAutoReply(
        bus,
        {
            "tools": {
                "sms": {
                    "auto_reply": {
                        "enabled": True,
                        "contacts": ["wife"],
                        "default_reply": "Got it.",
                    }
                }
            }
        },
        send_tool=tool,
        contacts_loader=lambda: book,
    )
    auto.start()
    bus_task = await _drain(bus)
    try:
        await bus.publish(Event(EventType.USER_MESSAGE, {"text": "text wife: hi"}))
        await bus.publish(
            Event(
                EventType.SMS_RECEIVED,
                {
                    "id": "in-5",
                    "from": "+15551110000",
                    "body": "hey",
                    "contact_alias": "wife",
                },
            )
        )
        await bus.drain()
        await asyncio.sleep(0.05)
        assert confirms == []
        await bus.publish(Event(EventType.ASSISTANT_DONE, {"text": "Sent."}))
        for _ in range(50):
            if confirms:
                break
            await asyncio.sleep(0.01)
        assert len(confirms) == 1
        assert confirms[0].payload.get("source") == "sms_auto_reply"
    finally:
        auto.stop()
        await _stop_bus(bus, bus_task)
