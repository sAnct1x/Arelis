"""LAN ingest for the Android notify companion — no live phone."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import yaml

from arelis.contacts import Contact, match_contact_label, normalize_phone
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.sms_inbound import SeenMessageStore
from arelis.sms_ingest import (
    InboundIngestServer,
    RecentInboundLog,
    format_ingest_listen_urls,
    load_ingest_token,
    parse_ingest_payload,
    publish_inbound,
)
from arelis.tools.inbound_sms import InboundSmsTool


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
            email="",
            aliases=tuple(str(a) for a in raw_aliases),
        )
    return out


def test_format_ingest_listen_urls_mentions_port() -> None:
    text = format_ingest_listen_urls(8765)
    assert ":8765" in text
    assert text.startswith("http://")


def test_load_ingest_token(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "secrets.yaml"
    path.write_text(
        yaml.safe_dump({"sms": {"ingest_token": "secret-token"}}),
        encoding="utf-8",
    )
    monkeypatch.delenv("ARELIS_INGEST_TOKEN", raising=False)
    assert load_ingest_token(path) == "secret-token"
    monkeypatch.setenv("ARELIS_INGEST_TOKEN", "from-env")
    assert load_ingest_token(path) == "from-env"


def test_match_contact_label_strips_emoji() -> None:
    book = _book(
        wife={
            "name": "Robin Hale",
            "phone": "+15551112222",
            "aliases": ("robbie",),
        }
    )
    assert match_contact_label("My Wife 💋", book) is book["wife"]
    assert match_contact_label("Robin Hale", book) is book["wife"]


def test_parse_ingest_resolves_name() -> None:
    book = _book(wife={"name": "Robin Hale", "phone": "5551112222"})
    msg = parse_ingest_payload(
        {"id": "n1", "from": "My Wife", "body": "I love you too"},
        contacts=book,
    )
    assert msg is not None
    assert msg.contact_name == "Robin Hale"
    assert msg.body == "I love you too"


async def test_publish_dedupes(tmp_path: Path) -> None:
    bus = EventBus()
    received: list[dict] = []

    async def capture(event) -> None:
        if event.type == EventType.SMS_RECEIVED:
            received.append(dict(event.payload))

    bus.subscribe(EventType.SMS_RECEIVED, capture)
    task = asyncio.create_task(bus.run())
    seen = SeenMessageStore(tmp_path / "seen.json")
    book = _book(wife={"name": "Robin", "phone": "5551112222"})
    msg = parse_ingest_payload(
        {"id": "dup1", "from": "Robin", "body": "hi"},
        contacts=book,
    )
    assert msg is not None
    assert await publish_inbound(bus, msg, seen=seen) is True
    assert await publish_inbound(bus, msg, seen=seen) is False
    await asyncio.sleep(0.05)
    assert len(received) == 1
    bus.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_ingest_http_server(tmp_path: Path) -> None:
    bus = EventBus()
    received: list[dict] = []

    async def capture(event) -> None:
        if event.type == EventType.SMS_RECEIVED:
            received.append(dict(event.payload))

    bus.subscribe(EventType.SMS_RECEIVED, capture)
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(bus.run())
    seen = SeenMessageStore(tmp_path / "seen.json")
    server = InboundIngestServer(
        bus,
        loop,
        token="test-token",
        host="127.0.0.1",
        port=18765,
        seen=seen,
    )
    server.start()
    try:
        async with httpx.AsyncClient() as client:
            health = await client.get("http://127.0.0.1:18765/inbound/health")
            assert health.status_code == 200
            assert health.json()["ok"] is True
            bad = await client.get("http://127.0.0.1:18765/inbound/ping")
            assert bad.status_code == 401
            ping = await client.get(
                "http://127.0.0.1:18765/inbound/ping",
                headers={"X-Arelis-Token": "test-token"},
            )
            assert ping.status_code == 200
            assert ping.json()["ok"] is True

            post = await client.post(
                "http://127.0.0.1:18765/inbound/sms",
                headers={"Authorization": "Bearer test-token"},
                json={
                    "id": "notif:abc",
                    "from": "Piper",
                    "body": "G",
                    "source": "notification",
                },
            )
            assert post.status_code == 200
            assert post.json()["published"] is True
        await asyncio.sleep(0.05)
        assert len(received) == 1
        assert received[0]["body"] == "G"
        assert received[0]["source"] == "notification"
    finally:
        server.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_inbound_sms_tool_lists_recent() -> None:
    log = RecentInboundLog(limit=5)
    from arelis.sms_inbound import InboundSms

    log.record(
        InboundSms(
            id="1",
            sender="+1",
            body="hello",
            time="t",
            contact_name="Robin",
        ),
        source="notification",
    )
    # Swap process log for the tool call.
    import arelis.sms_ingest as mod
    import arelis.tools.inbound_sms as tool_mod

    old = mod.RECENT_INBOUND
    mod.RECENT_INBOUND = log
    tool_mod.RECENT_INBOUND = log
    try:
        result = await InboundSmsTool().run(limit=5)
        assert result.ok
        assert "Robin" in result.output
        assert result.data["count"] == 1
    finally:
        mod.RECENT_INBOUND = old
        tool_mod.RECENT_INBOUND = old
