"""Inbound SMS watcher — mocked HTTP, no live SMSGate."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import yaml

from arelis.contacts import Contact, normalize_phone
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.sms_android import SmsGateAccount, load_sms_account
from arelis.sms_inbound import (
    InboundSms,
    InboundSmsWatcher,
    SeenMessageStore,
    SmsInboxError,
    fetch_inbox,
    floor_is_busy,
    format_held_inbound_flush,
    format_held_inbound_voice_cue,
    format_sms_chat_line,
    format_sms_voice_cue,
    parse_inbox_row,
)


def _account(**kwargs) -> SmsGateAccount:
    base = {
        "base_url": "http://192.168.1.20:8080",
        "username": "user",
        "password": "pass",
    }
    base.update(kwargs)
    return SmsGateAccount(**base)


def _book(**people: dict) -> dict[str, Contact]:
    out: dict[str, Contact] = {}
    for alias, fields in people.items():
        phone = str(fields.get("phone") or "")
        out[alias] = Contact(
            alias=alias,
            name=str(fields.get("name") or ""),
            phone=phone,
            digits=normalize_phone(phone),
            email="",
            aliases=(),
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


def test_supports_inbox_poll_local_only() -> None:
    local = _account()
    assert local.supports_inbox_poll()
    assert local.inbox_url == "http://192.168.1.20:8080/inbox"
    assert local.inbox_refresh_url == "http://192.168.1.20:8080/inbox/refresh"

    cloud = _account(base_url="https://api.sms-gate.app/3rdparty/v1")
    assert not cloud.supports_inbox_poll()

    dual = _account(
        base_url="https://api.sms-gate.app/3rdparty/v1",
        inbox_base_url="http://10.0.0.5:8080",
    )
    assert dual.supports_inbox_poll()
    assert dual.inbox_url == "http://10.0.0.5:8080/inbox"
    assert dual.inbox_auth == ("user", "pass")


def test_load_sms_account_inbox_fields(tmp_path: Path) -> None:
    path = tmp_path / "secrets.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "sms": {
                    "base_url": "https://api.sms-gate.app/3rdparty/v1",
                    "username": "cloud",
                    "password": "cpass",
                    "inbox_base_url": "http://192.168.1.9:8080",
                    "inbox_username": "local",
                    "inbox_password": "lpass",
                }
            }
        ),
        encoding="utf-8",
    )
    account = load_sms_account(path)
    assert account is not None
    assert account.inbox_base_url == "http://192.168.1.9:8080"
    assert account.inbox_auth == ("local", "lpass")
    assert account.supports_inbox_poll()


def test_parse_and_format_resolves_contact() -> None:
    book = _book(wife={"name": "Robin", "phone": "+15551112222"})
    msg = parse_inbox_row(
        {
            "id": "msg1",
            "sender": "555-111-2222",
            "contentPreview": "it's a test",
            "createdAt": "2026-08-07T12:00:00Z",
            "type": "SMS",
        },
        contacts=book,
    )
    assert msg is not None
    assert msg.contact_name == "Robin"
    assert format_sms_chat_line(msg) == "Text from Robin: it's a test"
    assert format_sms_voice_cue(msg) == "Text from Robin."


def test_floor_is_busy_for_turn_confirm_or_speech() -> None:
    assert not floor_is_busy()
    assert floor_is_busy(turn_busy=True)
    assert floor_is_busy(confirm_open=True)
    assert floor_is_busy(speaking=True)
    assert not floor_is_busy(turn_busy=False, confirm_open=False, speaking=False)


def test_held_inbound_flush_batches_same_sender() -> None:
    a = InboundSms(
        id="1",
        sender="+1",
        body="Bro that man is SSG",
        time="",
        contact_name="Robin Hale",
    )
    b = InboundSms(
        id="2",
        sender="+1",
        body="But his title is very very important",
        time="",
        contact_name="Robin Hale",
    )
    text = format_held_inbound_flush([a, b])
    assert text.startswith("2 texts from Robin Hale:")
    assert "Bro that man is SSG" in text
    assert "title is very very important" in text
    assert format_held_inbound_voice_cue([a, b]) == "2 texts from Robin Hale."
    assert format_held_inbound_flush([a]) == format_sms_chat_line(a)


def test_parse_accepts_mms_and_skips_self() -> None:
    book = _book(me={"name": "Sam", "phone": "+15550001111"})
    mms = parse_inbox_row(
        {
            "id": "mms:1",
            "sender": "+15559998888",
            "contentPreview": "Gotcha",
            "createdAt": "2026-08-07T12:00:00Z",
            "type": "MMS_DOWNLOADED",
        },
        contacts=book,
    )
    assert mms is not None
    assert mms.body == "Gotcha"

    self_msg = parse_inbox_row(
        {
            "id": "text:9",
            "sender": "+15550001111",
            "recipient": "+15550001111",
            "contentPreview": "loopback",
            "createdAt": "2026-08-07T12:00:00Z",
            "type": "SMS",
        },
        contacts=book,
    )
    assert self_msg is None


def test_format_truncates_body_and_unknown_number() -> None:
    msg = InboundSms(
        id="x",
        sender="+15559998888",
        body="a" * 200,
        time="",
    )
    line = format_sms_chat_line(msg, max_body=40)
    assert line.startswith("Text from +15559998888: ")
    assert line.endswith("…")
    assert len(line) < 80


def test_seen_store_seed_and_persist(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    store = SeenMessageStore(path)
    assert not store.seeded
    store.mark_seeded(["a", "b"])
    assert store.seeded
    assert store.has("a")
    assert path.is_file()

    again = SeenMessageStore(path)
    assert again.seeded
    assert again.has("b")
    again.mark(["c"])
    assert again.has("c")


async def test_fetch_inbox_refreshes_then_lists() -> None:
    account = _account()
    rows = [
        {
            "id": "PyDmBQZZXYmyxMwED8Fzy",
            "type": "SMS",
            "sender": "+15551112222",
            "contentPreview": "Hello",
            "createdAt": "2020-01-01T00:00:00Z",
        }
    ]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST" and request.url.path.endswith("/inbox/refresh"):
            return httpx.Response(202)
        if request.method == "GET" and request.url.path.endswith("/inbox"):
            assert "type" not in request.url.params
            return httpx.Response(200, json=rows)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        got = await fetch_inbox(account, client=client)
    assert got == rows
    assert calls == ["POST /inbox/refresh", "GET /inbox"]


async def test_fetch_inbox_rejects_cloud() -> None:
    account = _account(base_url="https://api.sms-gate.app/3rdparty/v1")
    with pytest.raises(SmsInboxError, match="Cloud"):
        await fetch_inbox(account)


async def test_watcher_seeds_then_publishes_new(tmp_path: Path, monkeypatch) -> None:
    bus = EventBus()
    received: list[dict] = []

    async def capture(event) -> None:
        if event.type == EventType.SMS_RECEIVED:
            received.append(dict(event.payload))

    bus.subscribe(EventType.SMS_RECEIVED, capture)
    run_task = await _drain(bus)

    state: dict[str, list[dict]] = {
        "rows": [
            {
                "id": "old1",
                "sender": "+15551112222",
                "contentPreview": "old",
                "createdAt": "2026-08-01T00:00:00Z",
                "type": "SMS",
            }
        ]
    }

    async def fake_fetch(account, *, limit=50, timeout_s=15.0, client=None, **kwargs):
        return list(state["rows"])

    monkeypatch.setattr("arelis.sms_inbound.fetch_inbox", fake_fetch)

    book = _book(wife={"name": "Robin", "phone": "+15551112222"})
    watcher = InboundSmsWatcher(
        bus,
        _account(),
        seen=SeenMessageStore(tmp_path / "seen.json"),
        contacts_loader=lambda: book,
    )

    assert await watcher.poll_once() == []
    await asyncio.sleep(0.02)
    assert received == []

    state["rows"].append(
        {
            "id": "new1",
            "sender": "+15551112222",
            "contentPreview": "it's a test",
            "createdAt": "2026-08-07T12:00:00Z",
            "type": "SMS",
        }
    )
    fresh = await watcher.poll_once()
    await asyncio.sleep(0.02)
    assert [m.id for m in fresh] == ["new1"]
    assert len(received) == 1
    assert received[0]["contact_name"] == "Robin"
    assert received[0]["body"] == "it's a test"

    assert await watcher.poll_once() == []
    await asyncio.sleep(0.02)
    assert len(received) == 1

    data = json.loads((tmp_path / "seen.json").read_text(encoding="utf-8"))
    assert data["seeded"] is True
    assert "new1" in data["seen_ids"]

    await _stop_bus(bus, run_task)


async def test_start_cloud_only_publishes_status() -> None:
    bus = EventBus()
    statuses: list[str] = []

    async def capture(event) -> None:
        if event.type == EventType.STATUS:
            statuses.append(str(event.payload.get("message") or ""))

    bus.subscribe(EventType.STATUS, capture)
    run_task = await _drain(bus)
    watcher = InboundSmsWatcher(
        bus,
        _account(base_url="https://api.sms-gate.app/3rdparty/v1"),
    )
    await watcher.start()
    await asyncio.sleep(0.05)
    assert not watcher.running
    assert any("Local Server" in s for s in statuses)
    await _stop_bus(bus, run_task)
