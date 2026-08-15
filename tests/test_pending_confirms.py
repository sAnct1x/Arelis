"""Pending send-confirm store and headless auto-reply parking."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.presence.confirm_persist import ConfirmPersister
from arelis.presence.pending_confirms import (
    PendingConfirm,
    PendingConfirmStore,
    pending_from_event_payload,
)
from arelis.sms_auto_reply import SmsAutoReply
from arelis.tools.base import ToolResult
from arelis.tools.sms_send import SendSmsTool


def test_pending_store_roundtrip(tmp_path: Path) -> None:
    store = PendingConfirmStore(tmp_path / "pending_confirms.json")
    item = PendingConfirm(
        id="sms-auto-abc",
        tool="send_sms",
        args={"to": "wife", "body": "On my way"},
        summary="send_sms(...)",
        detail="full card",
        source="sms_auto_reply",
    )
    store.upsert(item)
    loaded = store.list()
    assert len(loaded) == 1
    assert loaded[0].args["body"] == "On my way"
    assert store.get("sms-auto-abc") is not None
    assert store.remove("sms-auto-abc") is not None
    assert store.list() == []


def test_pending_from_event_uses_full_args() -> None:
    item = pending_from_event_payload(
        {
            "id": "x1",
            "tool": "send_sms",
            "args": {"to": "wife", "body": "short"},
            "full_args": {"to": "wife", "body": "full body text"},
            "summary": "s",
            "source": "sms_auto_reply",
        }
    )
    assert item is not None
    assert item.args["body"] == "full body text"
    assert pending_from_event_payload({"id": "y", "tool": "workspace"}) is None


def test_pending_from_event_prefers_full_args_over_truncated_preview() -> None:
    long_body = "good nights, sweet dreams. " * 20
    assert len(long_body) > 200
    item = pending_from_event_payload(
        {
            "id": "park-1",
            "tool": "send_sms",
            "args": {"to": "wife", "body": long_body[:200]},
            "full_args": {"to": "wife", "body": long_body},
            "summary": "send_sms",
            "detail": f"body={long_body}",
        }
    )
    assert item is not None
    assert item.args["body"] == long_body
    assert item.args["to"] == "wife"


@pytest.mark.asyncio
async def test_confirm_persister_writes_and_clears(tmp_path: Path) -> None:
    store = PendingConfirmStore(tmp_path / "p.json")
    bus = EventBus()
    persister = ConfirmPersister(bus, store)
    persister.start()
    task = asyncio.create_task(bus.run())
    try:
        await bus.publish(
            Event(
                EventType.TOOL_CONFIRM,
                {
                    "id": "c1",
                    "tool": "send_sms",
                    "full_args": {"to": "wife", "body": "hi"},
                    "args": {"to": "wife", "body": "hi"},
                    "summary": "send_sms",
                    "source": "sms_auto_reply",
                },
            )
        )
        await bus.drain()
        assert store.get("c1") is not None
        await bus.publish(
            Event(
                EventType.TOOL_CONFIRM_REPLY,
                {"id": "c1", "decision": "skip", "allow_turn": False},
            )
        )
        await bus.drain()
        assert store.get("c1") is None
    finally:
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_restored_confirm_appends_action_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arelis.core import receipts as receipts_mod
    from arelis.mail import MailAccount
    from arelis.presence import confirm_exec
    from arelis.tools.base import ToolResult

    ledger = tmp_path / "action_ledger.jsonl"
    monkeypatch.setattr(receipts_mod, "DEFAULT_LEDGER_PATH", ledger)

    async def _fake_run(self, **kwargs):  # type: ignore[no-untyped-def]
        return ToolResult(
            ok=True,
            output="Sent to a@b.com with subject 'Hi'.",
            data={"to": "a@b.com", "subject": "Hi", "message_id": "<x>"},
        )

    monkeypatch.setattr(confirm_exec.SendEmailTool, "run", _fake_run)
    monkeypatch.setattr(
        confirm_exec,
        "load_account",
        lambda: MailAccount(
            address="me@x.com",
            password="secret",
            default_recipient="me@x.com",
        ),
    )
    item = PendingConfirm(
        id="e1",
        tool="send_email",
        args={"to": "a@b.com", "subject": "Hi", "body": "Hello"},
        summary="send_email",
        detail="card",
        source="agent",
    )
    ok, output = await confirm_exec.execute_pending_confirm(item, {})
    assert ok
    assert "Sent" in output
    assert ledger.is_file()
    line = ledger.read_text(encoding="utf-8").strip()
    assert "send_email" in line
    assert "a@b.com" in line


class _FakeSend(SendSmsTool):
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        return ToolResult(ok=True, output="sent")


@pytest.mark.asyncio
async def test_headless_auto_reply_does_not_send() -> None:
    from arelis.contacts import Contact, normalize_phone

    bus = EventBus()
    fake = _FakeSend()
    cfg = {
        "tools": {
            "sms": {
                "auto_reply": {
                    "enabled": True,
                    "contacts": ["wife"],
                    "default_reply": "Got it.",
                }
            }
        }
    }
    book = {
        "wife": Contact(
            alias="wife",
            name="Robin",
            phone="+15551112222",
            digits=normalize_phone("+15551112222"),
            email="",
            aliases=(),
        )
    }
    reply = SmsAutoReply(
        bus, cfg, send_tool=fake, contacts_loader=lambda: book, headless=True
    )
    reply.start()
    task = asyncio.create_task(bus.run())
    events: list[Event] = []

    async def collect(event: Event) -> None:
        events.append(event)

    bus.subscribe(EventType.TOOL_CONFIRM, collect)
    try:
        await bus.publish(
            Event(
                EventType.SMS_RECEIVED,
                {
                    "id": "m1",
                    "from": "+15551112222",
                    "body": "hello",
                    "contact_alias": "wife",
                    "contact_name": "Robin",
                },
            )
        )
        await asyncio.sleep(0.05)
        await bus.drain()
        assert fake.calls == []
        assert any(e.type == EventType.TOOL_CONFIRM for e in events)
    finally:
        reply.stop()
        bus.stop()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
