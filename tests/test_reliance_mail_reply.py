"""Inbox reply stops at an unsent draft. One yes should hand that to send_email."""

from __future__ import annotations

import pytest

from arelis.core.reliance.mail_reply import (
    SendReady,
    frequent_from_sent,
    rank_unread,
    send_ready,
)


def test_send_ready_happy_path() -> None:
    ready = send_ready(
        {
            "action": "reply",
            "id": "12",
            "to": "sam@example.com",
            "subject": "Re: Lunch tomorrow",
            "body": "I'll be late.\n\nOn Sat, Sam wrote:\n> Can you make it?",
            "sent": False,
        }
    )
    assert ready == SendReady(
        to="sam@example.com",
        subject="Re: Lunch tomorrow",
        body="I'll be late.\n\nOn Sat, Sam wrote:\n> Can you make it?",
        source_id="12",
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


def test_send_ready_refuses_missing_to() -> None:
    with pytest.raises(ValueError):
        send_ready(
            {
                "id": "12",
                "subject": "Re: Lunch",
                "body": "I'll be late.",
                "sent": False,
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


def test_frequent_from_sent_strips_display_names() -> None:
    assert frequent_from_sent(
        ["Sam <sam@x.com>", "  ", "Pat <PAT@y.com>", ""]
    ) == {"sam@x.com", "pat@y.com"}


def test_empty_frequent_leaves_order_alone() -> None:
    messages = [
        {"id": "1", "from": "ada@elsewhere.com"},
        {"id": "2", "from": "Sam <sam@x.com>"},
        {"id": "3", "from": "Pat"},
    ]
    ranked = rank_unread(messages, frequent=set())
    assert [row["id"] for row in ranked] == ["1", "2", "3"]
