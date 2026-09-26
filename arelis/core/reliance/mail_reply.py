"""One yes between an inbox reply draft and send_email.

Inbox reply returns ``{action, id, to, subject, body, sent: False}`` and
tells the model to call send_email as a second step. This module is that
handoff: a SendReady the confirm path can take, plus who to surface first
among unread mail. It does not send.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Address inside a display name, else a bare mailbox in the string.
_ANGLE = re.compile(r"<\s*([^<>]*@[^<>]*)\s*>")
_BARE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


@dataclass(frozen=True)
class SendReady:
    to: str
    subject: str
    body: str
    source_id: str


def send_ready(reply_data: dict) -> SendReady:
    """Raise ValueError if sent is true, or to/subject/body missing."""
    if reply_data.get("sent") is True:
        raise ValueError("reply was already sent")
    missing = [
        name
        for name in ("to", "subject", "body")
        if not str(reply_data.get(name) or "").strip()
    ]
    if missing:
        raise ValueError("missing " + ", ".join(missing))
    return SendReady(
        to=str(reply_data.get("to") or "").strip(),
        subject=str(reply_data.get("subject") or "").strip(),
        body=str(reply_data.get("body") or "").strip(),
        source_id=str(reply_data.get("id") or "").strip(),
    )


def rank_unread(messages: list[dict], *, frequent: set[str]) -> list[dict]:
    """Stable. Addresses in `frequent` come first. Do not drop anyone.

    Comparison is case-insensitive. Use the email when the from string has
    one, otherwise the whole from string. Original order otherwise.
    """
    known = {_match_key(item) for item in frequent}
    known.discard("")

    def _order(message: dict) -> int:
        key = _from_key(str(message.get("from") or ""))
        return 0 if key and key in known else 1

    return sorted(messages, key=_order)


def frequent_from_sent(sent_to: list[str]) -> set[str]:
    """Normalize addresses the user has sent to.

    Lowercase, strip display names: 'Sam <sam@x.com>' -> 'sam@x.com'.
    Drop blanks.
    """
    found: set[str] = set()
    for raw in sent_to:
        addr = _email_in(str(raw or ""))
        if addr:
            found.add(addr)
    return found


def _email_in(text: str) -> str:
    """Lowercase mailbox, or empty when the string has no address."""
    raw = text.strip()
    if not raw:
        return ""
    angled = _ANGLE.search(raw)
    if angled:
        return angled.group(1).strip().lower()
    bare = _BARE.search(raw)
    if bare:
        return bare.group(0).lower()
    return ""


def _match_key(text: str) -> str:
    """Email when present, otherwise the whole string, lowercased."""
    addr = _email_in(text)
    if addr:
        return addr
    return text.strip().lower()


def _from_key(sender: str) -> str:
    return _match_key(sender)
