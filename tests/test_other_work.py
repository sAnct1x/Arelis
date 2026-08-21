"""Four skip-lists used to disagree about when a pending draft must stay dead.

The agent loop, the SMS completer, the email completer and preflight each
kept their own "this turn is about something else" list. A calendar-open
turn skipped the draft in the loop and revived it inside complete_sms_draft,
because that copy had never learned looks_like_calendar_open. Weather did
the same to email.

looks_like_other_work is the union. These tests pin the phrases that used
to split them, so teaching a fifth site a new exception is not how the next
one gets added.
"""

from __future__ import annotations

import pytest

from arelis.core.other_work import looks_like_other_work

OTHER = [
    "what's on my calendar today",
    "open the calendar",
    "close the calendar",
    "delete the dentist appointment",
    "put dinner on my calendar Friday at 7",
    "summarize data.csv",
    "find me a paper on fusion",
    "show me a chart of this",
    "what's 3 + 4",
    "write a temp file called notes.txt",
    "what's the weather in Springfield",
    "list my tasks",
    "what are my goals",
    "open youtube.com",
    "email me the weather every morning",
]


@pytest.mark.parametrize("text", OTHER)
def test_other_work_is_recognised(text: str) -> None:
    assert looks_like_other_work(text)


def test_a_plain_text_is_not_other_work() -> None:
    assert not looks_like_other_work("text Sam that I'm running late")


def test_a_plain_email_is_not_other_work() -> None:
    assert not looks_like_other_work("email Jordan the notes from today")


def test_empty_is_not_other_work() -> None:
    assert not looks_like_other_work("")
    assert not looks_like_other_work("   ")
