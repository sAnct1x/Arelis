"""Shared completion helpers for SMS, email, and agenda drafts."""

from __future__ import annotations

from arelis.core.agenda_complete import AgendaDraft, agenda_force_call_notice
from arelis.core.complete_protocol import (
    history_with_current,
    next_unsent,
    remaining_labels,
    unfinished_call_notice,
    with_current_user_turn,
)
from arelis.core.email_complete import EmailDraft, email_force_call_notice, email_remaining
from arelis.core.sms_complete import SmsDraft, sms_force_call_notice


def test_remaining_labels_skips_sent_case_insensitive() -> None:
    assert remaining_labels(["Brian", "Robin"], {"brian"}) == ["Robin"]
    assert remaining_labels(["a", "", "b"], {"B"}) == ["a"]
    assert next_unsent(["a", "b"], {"a"}, fallback="z") == "b"
    assert next_unsent(["a"], {"a"}, fallback="z") == "z"


def test_current_user_turn_is_appended_once() -> None:
    pairs = [("user", "hi"), ("assistant", "ok")]
    assert with_current_user_turn(pairs, "go")[-1] == ("user", "go")
    already = [("user", "go")]
    assert with_current_user_turn(already, "go") == already
    assert history_with_current([], "now") == [("user", "now")]


def test_unfinished_notice_keeps_the_allow_closer() -> None:
    text = unfinished_call_notice("send_sms", 'Call it now with to="x" body="hi"')
    assert text.startswith("You have not finished send_sms. Call it now with")
    assert "confirm card will ask the user to Allow" in text


def test_sms_force_notice_still_names_the_next_alias() -> None:
    draft = SmsDraft(
        to="brian",
        body="Running late",
        alias="brian",
        recipients=("brian", "robin"),
        aliases=("brian", "robin"),
    )
    notice = sms_force_call_notice(draft, already_sent={"brian"})
    assert 'to="robin"' in notice
    assert 'body="Running late"' in notice
    assert "Then repeat" not in notice


def test_email_remaining_and_force_notice_share_the_walk() -> None:
    draft = EmailDraft(
        to="one@example.com",
        subject="Hi",
        body="Test",
        recipients=("one@example.com", "two@example.com"),
    )
    assert email_remaining(draft, {"one@example.com"}) == ["two@example.com"]
    notice = email_force_call_notice(draft, already_sent={"one@example.com"})
    assert 'to="two@example.com"' in notice
    assert 'subject="Hi"' in notice


def test_agenda_force_notice_still_locks_create_args() -> None:
    draft = AgendaDraft(
        summary="Budget review",
        start="2026-08-12T15:00:00",
        provider="google",
    )
    notice = agenda_force_call_notice(draft)
    assert "Call agenda now with action=create" in notice
    assert 'summary="Budget review"' in notice
    assert "Chatting is not creating" in notice
