"""Email draft completion across turns."""

from __future__ import annotations

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.email_complete import (
    complete_email_draft,
    draft_schedule_briefing_args,
    draft_schedule_job_args,
    fill_send_email_args,
    looks_like_bare_confirm,
    looks_like_schedule_manage,
    looks_like_scheduled_send,
    looks_like_standard_briefing,
    parse_email_utterance,
    resolve_email_address,
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


def test_parse_email_quoted_subject_and_body() -> None:
    draft = parse_email_utterance(
        "Email me at bob@example.com with subject 'Arelis operator e2e' "
        "and body 'synthetic operator mail. ignore.'"
    )
    assert draft is not None
    assert draft.to == "bob@example.com"
    assert draft.subject == "Arelis operator e2e"
    assert draft.body == "synthetic operator mail. ignore."
    assert "@gmail.com with subject" not in draft.body


def test_parse_email_with_subject_and_body() -> None:
    draft = parse_email_utterance(
        "Email bob@example.com about Dinner plans: See you at 7"
    )
    assert draft is not None
    assert draft.complete
    assert draft.to == "bob@example.com"
    assert "Dinner" in draft.subject
    assert "See you at 7" in draft.body


def test_parse_email_subject_comma_body_markers() -> None:
    """Latency-style: subject: test, body: … must not glue body into subject."""
    draft = parse_email_utterance(
        "send an email to you@gmail.com subject: test, body: "
        "this is a test email disregard we are measuring latency"
    )
    assert draft is not None
    assert draft.complete
    assert draft.subject == "test"
    assert "measuring latency" in draft.body
    assert "body" not in draft.subject.lower()


def test_parse_email_to_name_incomplete_without_subject() -> None:
    draft = parse_email_utterance("email Brian that I'll be late")
    assert draft is not None
    assert draft.to.lower().startswith("brian")
    assert draft.body
    # Named recipient without a contacts email must not look "complete".
    assert draft.unresolved_named_to
    assert not draft.complete


def test_about_without_colon_fills_body_for_force() -> None:
    """'email X about the trip…' must not leave body empty (second-ask trap)."""
    draft = parse_email_utterance(
        "email bob@example.com about the trip this weekend"
    )
    assert draft is not None
    assert draft.complete
    assert "trip" in draft.body.lower()
    assert draft.subject


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


def test_send_the_email_revives_complete_draft() -> None:
    history = [
        ChatMessage(
            role="user",
            content="Email bob@example.com about Dinner: See you at 7",
        ),
        ChatMessage(role="assistant", content="Ready when you are."),
    ]
    draft = complete_email_draft("send the email", history=history)
    assert draft is not None and draft.complete
    assert draft.tool_to == "bob@example.com"
    assert "Dinner" in draft.subject
    assert "See you at 7" in draft.body


def test_send_it_revives_incomplete_draft() -> None:
    """'send it' after a to-only compose must revive so force/preflight can finish."""
    history = [
        ChatMessage(
            role="user",
            content="Email bob@example.com",
        ),
        ChatMessage(role="assistant", content="What should the body say?"),
    ]
    draft = complete_email_draft("send it", history=history)
    assert draft is not None
    assert draft.to == "bob@example.com"
    assert not draft.complete


def test_resolve_name_to_contact_email() -> None:
    book = _book(wife={"name": "Robin", "aliases": ("wife",), "email": "w@x.com"})
    assert resolve_email_address("my wife", book) == "w@x.com"
    assert resolve_email_address("w@x.com", book) == "w@x.com"


def test_fill_send_email_args_locks_complete_draft() -> None:
    book = _book(brian={"name": "Brian", "aliases": ("brian",), "email": "b@x.com"})
    draft = complete_email_draft(
        "Email Brian about Running late: Stuck in traffic",
        contacts=book,
    )
    assert draft and draft.complete
    filled = fill_send_email_args(
        {
            "to": "invented@evil.test",
            "subject": "Totally different",
            "body": "Model invention",
        },
        draft,
    )
    assert filled["to"] == "b@x.com"
    assert filled["subject"] == "Running late"
    assert filled["body"] == "Stuck in traffic"


def test_check_my_email_is_not_a_compose_draft() -> None:
    assert parse_email_utterance("check my email later") is None
    assert complete_email_draft("What's in my email?") is None


def test_compose_email_preflight_intent() -> None:
    hints = detect_intents(
        "Email bob@example.com about Dinner: See you at 7"
    )
    assert any(h.kind == "compose_email" for h in hints)
    email = next(h for h in hints if h.kind == "compose_email")
    assert email.expected_tools == ("send_email",)
    assert "bob@example.com" in email.nudge
    assert "Dinner" in email.nudge


def test_bare_gmail_repairs_to_gmail_com() -> None:
    from arelis.core.email_complete import named_address_in_text, repair_email_address

    assert repair_email_address("you@gmail") == "you@gmail.com"
    assert named_address_in_text("send an email to you@gmail, be creative") == (
        "you@gmail.com"
    )
    draft = parse_email_utterance("send an email to you@gmail, be creative")
    assert draft is not None
    assert draft.tool_to == "you@gmail.com"


def test_analyze_json_does_not_revive_compose_email() -> None:
    history = [
        ChatMessage(
            role="user",
            content="send an email to you@gmail.com, be creative",
        ),
        ChatMessage(role="assistant", content="Sent email to you@gmail.com."),
    ]
    hints = detect_intents(
        "analyze this file attached to this message and give me a brief summary\n"
        "e2e_full_capability.json",
        history=history,
    )
    kinds = [h.kind for h in hints]
    assert "compose_email" not in kinds
    assert "analyze" in kinds


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


def test_email_me_does_not_use_smtp_from(monkeypatch) -> None:
    """'me' is the user, not the Gmail Arelis sends from."""
    from arelis.mail import MailAccount

    monkeypatch.setattr("arelis.profile.load_profile_email", lambda **k: "")
    monkeypatch.setattr(
        "arelis.mail.load_account",
        lambda path=None: MailAccount(
            address="bot@example.com",
            password="x",
            default_recipient="",
        ),
    )
    assert resolve_email_address("me") == ""
    monkeypatch.setattr(
        "arelis.mail.load_account",
        lambda path=None: MailAccount(
            address="bot@example.com",
            password="x",
            default_recipient="you@example.com",
        ),
    )
    assert resolve_email_address("me") == "you@example.com"


def test_subject_colon_body_colon_splits() -> None:
    draft = parse_email_utterance(
        "email you@example.com subject: test, body: just a test"
    )
    assert draft is not None
    assert draft.tool_subject == "test"
    assert "just a test" in draft.tool_body
    assert "subject" not in draft.tool_body.lower()


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


def test_every_other_day_headlines_are_a_custom_job() -> None:
    ask = "Every other day at 7am, email me the headlines."
    assert looks_like_scheduled_send(ask)
    assert not looks_like_standard_briefing(ask)
    args = draft_schedule_job_args(ask)
    assert args["action"] == "create"
    assert "headlines" in args["prompt"].lower()


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


def test_every_time_it_rains_is_not_a_timer() -> None:
    assert not looks_like_scheduled_send("tell me every time it rains")


def test_non_recurring_email_me_a_test_still_drafts() -> None:
    draft = complete_email_draft("email me a test saying hello")
    assert draft is not None
    assert draft.complete


def test_analyze_followup_does_not_complete_pending_email() -> None:
    history = [
        ChatMessage(role="user", content="email bob@example.com"),
        ChatMessage(
            role="assistant",
            content="What should the subject and body be?",
        ),
    ]
    assert (
        complete_email_draft(
            "summarize the csv at data/sales.csv",
            history=history,
        )
        is None
    )
