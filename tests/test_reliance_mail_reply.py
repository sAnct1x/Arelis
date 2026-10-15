"""Inbox reply stops at an unsent draft. One yes should hand that to send_email."""

from __future__ import annotations

import pytest

from arelis.core.reliance.mail_reply import (
    rank_unread,
    send_ready,
)


def test_send_ready_refuses_already_sent() -> None:
    with pytest.raises(ValueError):
        send_ready(
            {
                "id": "12",
                "to": "sam@example.com",
                "subject": "Re: Lunch",
                "body": "I'll be late.",
                "sent": True,
            }
        )


def test_rank_puts_frequent_sender_first_and_keeps_strangers() -> None:
    messages = [
        {"id": "1", "from": "Ada <ada@elsewhere.com>", "subject": "Invoice"},
        {"id": "2", "from": "Sam <Sam@X.com>", "subject": "Lunch"},
        {"id": "3", "from": "newsletter@lists.example", "subject": "Weekly"},
    ]
    ranked = rank_unread(messages, frequent={"sam@x.com"})
    assert [row["id"] for row in ranked] == ["2", "1", "3"]
    assert {row["id"] for row in ranked} == {"1", "2", "3"}


def test_empty_frequent_leaves_order_alone() -> None:
    messages = [
        {"id": "1", "from": "ada@elsewhere.com"},
        {"id": "2", "from": "Sam <sam@x.com>"},
        {"id": "3", "from": "Pat"},
    ]
    ranked = rank_unread(messages, frequent=set())
    assert [row["id"] for row in ranked] == ["1", "2", "3"]
