"""Email draft completion across turns."""

from __future__ import annotations

from arelis.contacts import Contact, normalize_phone
from arelis.core.email_complete import (
    complete_email_draft,
    fill_send_email_args,
    parse_email_utterance,
    resolve_email_address,
)
from arelis.core.memory import ChatMessage
from arelis.core.preflight import detect_intents


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
