"""Asking for alt text or a rewrite is not a request to send a text."""

from __future__ import annotations

import pytest

from arelis.core.sms_complete import SmsDraft, parse_sms_utterance, sms_intent_this_turn

# Phrases about writing. None of these is someone asking to text a person.
_NOT_A_TEXT = (
    "Give me three alt-text options",
    "write alt text for this",
    "give me some text options",
    "rewrite this text",
    "can you give me a text summary",
    "three alt-text options please",
)

# Real texts, locked to the draft main produces for each sentence.
_REAL_TEXTS = (
    (
        "text Sam I'm late",
        SmsDraft(
            to="Sam I",
            body="",
            alias="",
            source="current",
            recipients=("Sam I",),
            aliases=(),
            missing=(),
        ),
    ),
    (
        "send a text to mom",
        SmsDraft(
            to="mom",
            body="",
            alias="",
            source="current",
            recipients=("mom",),
            aliases=(),
            missing=(),
        ),
    ),
    (
        "text my brother",
        SmsDraft(
            to="brother",
            body="",
            alias="",
            source="current",
            recipients=("brother",),
            aliases=(),
            missing=(),
        ),
    ),
)


@pytest.mark.parametrize("spoken", _NOT_A_TEXT)
def test_writing_about_text_stays_off_the_texting_path(spoken: str) -> None:
    draft = parse_sms_utterance(spoken)
    assert draft is None, draft
    assert sms_intent_this_turn(spoken) is False


@pytest.mark.parametrize(("spoken", "expected"), _REAL_TEXTS)
def test_a_real_text_still_parses_the_same_draft(spoken: str, expected: SmsDraft) -> None:
    assert sms_intent_this_turn(spoken) is True
    assert parse_sms_utterance(spoken) == expected
