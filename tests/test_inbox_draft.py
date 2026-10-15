"""inbox could list/read/trash. send_email fired a send. Nothing built a reply.

Roadmap 4.9: a person says "reply to that email from Sam" and today there is
no way to PEEK that UID, quote it, and look at {to, subject, body} before
the Allow card. `reply` is that verb. It does not send. Saving to IMAP
Drafts is not this work — `_special_mailbox` has no drafts helper, and a
server write would have to join INBOX_WRITE_ACTIONS in both inbox.py and
policy.py.

EmailDraft already reviews a payload before send_email. The hook is
`email_draft_from_inbox`, not a second draft type.
"""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import pytest

from arelis.core.email_complete import (
    email_draft_from_inbox,
)
from arelis.mail import MailAccount, Mailer
from arelis.tools.inbox import (
    InboxTool,
)


def _rfc822(
    *,
    sender: str,
    subject: str,
    body: str,
    reply_to: str = "",
    date: str = "Sat, 08 Aug 2026 12:00:00 +0000",
) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["To"] = "me@example.com"
    msg["Subject"] = subject
    msg["Date"] = date
    msg.set_content(body)
    return msg.as_bytes()


SAM = _rfc822(
    sender="Sam <sam@example.com>",
    reply_to="sam@example.com",
    subject="Lunch tomorrow",
    body="Can you make the 3pm meeting?",
)
PAT = _rfc822(
    sender="Pat <pat@example.com>",
    subject="Invoices",
    body="Please pay the bill this week.",
)


class _FakeImap:
    """Serves messages by UID. Records FETCH spec so a BODY[] slip fails."""

    def __init__(self, messages: dict[str, bytes]) -> None:
        self.messages = messages
        self.fetches: list[tuple[str, str]] = []
        self.commands: list[str] = []
        self.readonly: bool | None = None
        self.writable_connect: bool | None = None
        self.seen: set[str] = set()

    def __enter__(self) -> _FakeImap:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def select(self, _mailbox: str, readonly: bool = False) -> tuple[str, list[Any]]:
        self.readonly = readonly
        return "OK", [b"1"]

    def uid(self, command: str, *args: object) -> tuple[str, list[Any]]:
        self.commands.append(command)
        if command == "FETCH":
            uid = str(args[0])
            spec = str(args[1])
            self.fetches.append((uid, spec))
            if "BODY.PEEK" not in spec:
                self.seen.add(uid)
            raw = self.messages.get(uid)
            if raw is None:
                return "OK", [None]
            meta = f"{uid} (BODY[] {{{len(raw)}}})"
            return "OK", [(meta.encode(), raw)]
        if command == "STORE":
            self.seen.add(str(args[0]))
            return "OK", [None]
        return "NO", [None]


def _tool(
    monkeypatch: pytest.MonkeyPatch,
    messages: dict[str, bytes] | None = None,
    **kwargs: Any,
) -> tuple[InboxTool, _FakeImap]:
    tool = InboxTool(MailAccount("me@example.com", "pw"), **kwargs)
    fake = _FakeImap(messages or {"12": SAM, "13": PAT})

    def _connect(*, writable: bool = False) -> _FakeImap:
        fake.writable_connect = writable
        fake.select("INBOX", readonly=not writable)
        return fake

    monkeypatch.setattr(tool, "_connect", _connect)
    return tool, fake


def _sent_trap(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """If reply grows a silent send, these names show up and the test dies."""
    hits: list[str] = []

    def _send(self: Mailer, **_kwargs: Any) -> str:
        hits.append("Mailer.send")
        return "mid"

    async def _send_async(self: Mailer, **_kwargs: Any) -> str:
        hits.append("Mailer.send_async")
        return "mid"

    monkeypatch.setattr(Mailer, "send", _send)
    monkeypatch.setattr(Mailer, "send_async", _send_async)
    return hits


# ------------------------------------------------------------------ the verb


@pytest.mark.asyncio
async def test_reply_uses_that_uid_not_another(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation (3): draft UID 13's subject into a reply to 12 and this fails."""
    tool, fake = _tool(monkeypatch)

    result = await tool.run(action="reply", id="12", body="I'll be late.")

    assert result.ok, result.output
    assert result.data["id"] == "12"
    assert result.data["to"] == "sam@example.com"
    assert result.data["subject"] == "Re: Lunch tomorrow"
    assert result.data["source_subject"] == "Lunch tomorrow"
    assert "Invoices" not in result.data["subject"]
    assert "Invoices" not in result.data["body"]
    assert "Please pay the bill" not in result.data["body"]
    assert fake.fetches
    assert all(uid == "12" for uid, _spec in fake.fetches)


@pytest.mark.asyncio
async def test_reply_does_not_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mutation (2): call Mailer.send from reply and this fails."""
    hits = _sent_trap(monkeypatch)
    tool, fake = _tool(monkeypatch)
    tool.mailer = Mailer(MailAccount("me@example.com", "pw"))  # type: ignore[attr-defined]

    result = await tool.run(action="reply", id="12", body="I'll be late.")

    assert result.ok, result.output
    assert hits == []
    assert result.data.get("sent") is False
    assert "STORE" not in fake.commands
    assert "APPEND" not in fake.commands
    assert "COPY" not in fake.commands
    assert "MOVE" not in fake.commands


@pytest.mark.asyncio
async def test_empty_body_is_not_a_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    tool, fake = _tool(monkeypatch)

    result = await tool.run(action="reply", id="12", body="   ")

    assert not result.ok
    assert "nothing was drafted" in result.output.lower()
    assert not result.data.get("to")
    assert not result.data.get("body")
    assert email_draft_from_inbox(result.data) is None
    assert fake.fetches == []


