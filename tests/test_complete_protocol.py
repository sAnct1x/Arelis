"""Shared completion helpers for SMS, email, and agenda drafts."""

from __future__ import annotations

from arelis.core.complete_protocol import (
    history_with_current,
    next_unsent,
    remaining_labels,
    with_current_user_turn,
)
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


