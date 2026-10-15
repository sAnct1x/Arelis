"""Email draft completion across turns."""

from __future__ import annotations

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.email_complete import (
    complete_email_draft,
    draft_schedule_briefing_args,
    fill_send_email_args,
    looks_like_bare_confirm,
    looks_like_schedule_manage,
    looks_like_scheduled_send,
    looks_like_standard_briefing,
    parse_email_utterance,
    rewrite_schedule_calls,
)
from arelis.core.memory import ChatMessage
from arelis.core.preflight import detect_intents


@pytest.fixture(autouse=True)
def _no_standing_inbox(monkeypatch) -> None:
    monkeypatch.setattr("arelis.profile.load_profile_email", lambda **k: "")


def _book(**people: dict) -> dict[str, Contact]:
    out: dict[str, Contact] = {}
    for alias, fields in people.items():
        phone = str(fields.get("phone") or "5551112222")
        raw_aliases = fields.get("aliases") or ()
        if isinstance(raw_aliases, str):
            raw_aliases = (raw_aliases,)
        out[alias] = Contact(
            alias=alias,
            name=str(fields.get("name") or ""),
            phone=phone,
            digits=normalize_phone(phone),
            aliases=tuple(str(a).lower() for a in raw_aliases),
            email=str(fields.get("email") or ""),
        )
    return out


@pytest.mark.parametrize(
    "ask",
    ["Email sam@example.com with the subject Lunch and tell him I'm running ten minutes late.", "Email sam@example.com subject: Lunch and tell him I'm running ten minutes late."],
)
def test_named_subject_lands_on_the_confirm_card(ask: str) -> None:
    """A named subject is the subject. The rest is the body.

    The email force preinject used to keep the default subject and stuff
    'with the subject Lunch and tell him...' into the body, so the Allow
    card showed 'A message from Arelis'.
    """
    from arelis.tools.policy import describe_call

    draft = complete_email_draft(ask)
    assert draft is not None
    assert draft.complete
    assert draft.subject == "Lunch"
    assert "running ten minutes late" in draft.body
    assert "subject" not in draft.body.lower()
    assert "titled" not in draft.body.lower()
    assert draft.tool_subject == "Lunch"

    locked = fill_send_email_args(
        {"to": "wrong@example.com", "subject": "WRONG", "body": "WRONG"},
        draft,
    )
    assert locked["subject"] == "Lunch"
    card = describe_call("send_email", locked)
    assert any(line.strip() == "Subject: Lunch" for line in card.splitlines())
    assert "A message from Arelis" not in card
    assert "running ten minutes late" in card


def test_address_plus_body_without_subject_is_complete() -> None:
    """Missing subject alone must not skip force — default subject at send."""
    draft = parse_email_utterance("Email bob@example.com that I'll be late")
    assert draft is not None
    assert draft.complete
    assert draft.body
    assert draft.tool_subject == "A message from Arelis"
    filled = fill_send_email_args({}, draft)
    assert filled["subject"] == "A message from Arelis"
    assert filled["to"] == "bob@example.com"


def test_history_merges_body_after_email_about() -> None:
    history = [
        ChatMessage(role="user", content="Email Brian about Thursday"),
        ChatMessage(role="assistant", content="What should the body say?"),
    ]
    book = _book(
        brian={
            "name": "Brian Montgomery",
            "aliases": ["brian"],
            "email": "brian@example.com",
        }
    )
    draft = complete_email_draft(
        "Can we meet at 3pm?",
        history=history,
        contacts=book,
    )
    assert draft is not None
    assert draft.complete
    assert draft.tool_to == "brian@example.com"
    assert draft.subject.lower() == "thursday"
    assert draft.body == "Can we meet at 3pm?"
    assert draft.source == "history"


def test_email_me_quoted_subject_comma_body(monkeypatch) -> None:
    """9.3: subject 'X', body 'Y' (comma) and me → the user's inbox."""
    monkeypatch.setattr(
        "arelis.profile.load_profile_email", lambda **k: "you@example.com"
    )
    ask = "Email me a test: subject 'Arelis test', body 'this is a test'."
    draft = parse_email_utterance(ask)
    assert draft is not None
    assert draft.tool_subject == "Arelis test"
    assert "this is a test" in draft.tool_body.lower()
    assert "email me a test" not in draft.tool_body.lower()
    assert draft.tool_to == "you@example.com"
    filled = fill_send_email_args({}, draft)
    assert filled["to"] == "you@example.com"
    assert filled["subject"] == "Arelis test"


def test_recurring_weather_email_is_a_scheduled_job() -> None:
    """11.1: every day at 7am is a scheduled job, not send_email this turn."""
    ask = "Every day at 7am, email me a summary of the weather."
    assert complete_email_draft(ask) is None
    assert parse_email_utterance(ask) is None
    hints = detect_intents(ask)
    tools = {t for h in hints for t in h.expected_tools}
    kinds = [h.kind for h in hints]
    assert "schedule" in tools
    assert "send_email" not in tools
    assert "weather" not in tools
    assert "compose_email" not in kinds
    from arelis.core.skills import select_skill_ids

    ids = select_skill_ids(
        ask,
        available_tools={"schedule", "send_email", "weather", "inbox"},
    )
    assert "schedule" in ids
    args = draft_schedule_briefing_args(ask)
    assert args["action"] == "create_briefing"
    assert args["time"] == "7am"
    rewritten = rewrite_schedule_calls(
        ask,
        [("schedule", {"action": "create", "prompt": "weather", "time": "7am"})],
        schedule_used=False,
        schedule_available=True,
    )
    assert rewritten == [("schedule", args)]
    confirm = rewrite_schedule_calls(
        "confirm",
        [("schedule", {"action": "run_now", "id": "daily-weather-summary"})],
        schedule_used=True,
        schedule_available=True,
    )
    assert confirm == []
    assert looks_like_bare_confirm("confirm")
    assert looks_like_bare_confirm("yes")
    assert not looks_like_bare_confirm("confirm the weather job for friday")


def test_every_single_morning_is_still_a_scheduled_job() -> None:
    ask = (
        "I want you to send me an email, every single morning at 7 am, "
        "giving me a summary of what the weather is going to be like in "
        "springfield illinois, and metropolis illinois. keep it brief, friendly, and fun."
    )
    assert looks_like_scheduled_send(ask)
    assert not looks_like_standard_briefing(ask)
    hints = detect_intents(ask)
    tools = {t for h in hints for t in h.expected_tools}
    kinds = [h.kind for h in hints]
    assert "schedule" in tools
    assert "send_email" not in tools
    assert "weather" not in tools
    assert "compose_email" not in kinds
    rewritten = rewrite_schedule_calls(
        ask,
        [("weather", {"place": "Metropolis, Illinois"}), ("schedule", {"action": "create"})],
        schedule_used=False,
        schedule_available=True,
    )
    assert len(rewritten) == 1
    name, args = rewritten[0]
    assert name == "schedule"
    assert args["action"] == "create"
    assert "metropolis" in args["prompt"].lower()
    assert args["time"].lower().replace(" ", "") in {"7am", "7:00am"}


def test_schedule_manage_does_not_force_weather_or_mail() -> None:
    delete = "please delete the second briefing named Morning Weather Briefing"
    listing = "can you show me all of my briefings? or all of my automations?"
    assert looks_like_schedule_manage(delete)
    assert looks_like_schedule_manage(listing)
    assert not looks_like_scheduled_send(delete)
    for ask in (delete, listing):
        hints = detect_intents(ask)
        tools = {t for h in hints for t in h.expected_tools}
        kinds = [h.kind for h in hints]
        assert "schedule" in tools
        assert "weather" not in tools
        assert "send_email" not in tools
        assert "compose_email" not in kinds
    assert not looks_like_schedule_manage("What's the weather in Springfield?")


