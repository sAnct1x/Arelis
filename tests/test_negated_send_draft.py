"""A declined or complaining send ask must never become a send draft.

Filament voice mode runs a pre-model send_sms / send_email with no card, so
"don't text mom that I'm running late" building a complete draft could send a
real text. The send verb only counts when no "don't / no need / never / why
did you" sits before it in the same clause.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.email_complete import complete_email_draft, parse_email_utterance
from arelis.core.memory import ChatMessage
from arelis.core.preflight import detect_intents
from arelis.core.sms_complete import complete_sms_draft, parse_sms_utterance
from arelis.core.turn_prepare import _prepare_sms_first_move
from tests.test_no_call_path import _ctx, _FakeLoop


@pytest.fixture(autouse=True)
def _no_standing_inbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arelis.profile.load_profile_email", lambda **k: "")


def _book() -> dict[str, Contact]:
    phone = "5551112222"
    return {
        "mom": Contact(
            alias="mom",
            name="Test Mom",
            phone=phone,
            digits=normalize_phone(phone),
            aliases=("mom",),
            email="mom@example.com",
        )
    }


SMS_DECLINED = (
    "don't text mom that I'm running late",
    "why did you text mom that I'm running late?",
    "I never said text mom that I'm running late",
    "no need to text mom that I'm running late",
    "don't send her a text saying I'm late",
)

EMAIL_DECLINED = (
    "don't email mom saying I'm running late",
    "don't email test@example.com subject hi body see you soon",
    "why did you email mom saying I'm running late?",
    "don't email the file to test@example.com",
)


@pytest.mark.parametrize("text", SMS_DECLINED)
def test_declined_text_is_not_an_sms_draft(text: str) -> None:
    assert parse_sms_utterance(text) is None
    draft = complete_sms_draft(text, history=[], contacts=_book())
    assert draft is None or not draft.complete


@pytest.mark.parametrize("text", EMAIL_DECLINED)
def test_declined_email_is_not_an_email_draft(text: str) -> None:
    assert parse_email_utterance(text) is None
    draft = complete_email_draft(text, history=[], contacts=_book())
    assert draft is None or not draft.complete


def test_declined_sends_give_no_send_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arelis.core.sms_complete.load_contacts", _book)
    monkeypatch.setattr("arelis.core.email_complete.load_contacts", _book)
    for text in SMS_DECLINED + EMAIL_DECLINED:
        tools = {t for h in detect_intents(text) for t in h.expected_tools}
        assert "send_sms" not in tools, text
        assert "send_email" not in tools, text


def test_real_send_asks_still_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    book = _book()
    sms = complete_sms_draft("text mom that I'm running late", history=[], contacts=book)
    assert sms is not None and sms.complete
    assert sms.body == "I'm running late"
    # A negation inside the body does not veto the verb before it.
    sms_body_neg = complete_sms_draft(
        "text mom that I'm running late, don't wait up", history=[], contacts=book
    )
    assert sms_body_neg is not None and sms_body_neg.complete
    assert "don't wait up" in sms_body_neg.body
    mail = complete_email_draft("email mom saying don't wait up", history=[], contacts=book)
    assert mail is not None and mail.complete
    assert mail.body == "don't wait up"
    monkeypatch.setattr("arelis.core.sms_complete.load_contacts", _book)
    tools = {t for h in detect_intents("text mom that I'm running late") for t in h.expected_tools}
    assert "send_sms" in tools


def test_text_mom_dont_wait_up_parses_the_same_as_before() -> None:
    """The verb is not negated, so this guard leaves the parse alone.

    Today's parser reads the recipient as "mom don" with no body (incomplete),
    on main too. That is a separate parse limit, not a negation, and is pinned
    here so a change to it is a deliberate one.
    """
    draft = parse_sms_utterance("text mom don't wait up")
    assert draft is not None
    assert draft.to.lower().startswith("mom")


def test_a_declined_ask_in_history_does_not_complete_a_later_send() -> None:
    history: list[Any] = [
        ChatMessage(role="user", content="don't text mom that I'm running late"),
        ChatMessage(role="assistant", content="Okay, I won't."),
    ]
    for follow in ("send it", "yes", "go ahead"):
        draft = complete_sms_draft(follow, history=history, contacts=_book())
        assert draft is None or not draft.complete, follow
    mail_history: list[Any] = [
        ChatMessage(role="user", content="don't email mom saying I'm running late"),
        ChatMessage(role="assistant", content="Okay, I won't."),
    ]
    for follow in ("send it", "send the email"):
        mail = complete_email_draft(follow, history=mail_history, contacts=_book())
        assert mail is None or not mail.complete, follow


def test_suggestion_and_never_mind_still_draft_a_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    book = _book()
    for text in (
        "why don't you text mom that I'm running late",
        "never mind, text mom that I'm running late",
    ):
        draft = complete_sms_draft(text, history=[], contacts=book)
        assert draft is not None and draft.complete
        assert draft.body == "I'm running late"
        monkeypatch.setattr("arelis.core.sms_complete.load_contacts", _book)
        tools = {t for h in detect_intents(text) for t in h.expected_tools}
        assert "send_sms" in tools, text


@pytest.mark.asyncio
async def test_curly_apostrophe_decline_does_not_arm_a_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sms_text = "don\u2019t text mom that I\u2019m running late"
    email_text = "don\u2019t email mom saying I\u2019m running late"

    assert parse_sms_utterance(sms_text) is None
    sms_draft = complete_sms_draft(sms_text, history=[], contacts=_book())
    assert sms_draft is None or not sms_draft.complete

    assert parse_email_utterance(email_text) is None
    email_draft = complete_email_draft(email_text, history=[], contacts=_book())
    assert email_draft is None or not email_draft.complete

    monkeypatch.setattr("arelis.core.sms_complete.load_contacts", _book)
    monkeypatch.setattr("arelis.core.email_complete.load_contacts", _book)
    for text in (sms_text, email_text):
        tools = {t for h in detect_intents(text) for t in h.expected_tools}
        assert "send_sms" not in tools, text
        assert "send_email" not in tools, text

    loop = _FakeLoop()
    ctx = _ctx(text=sms_text)
    ctx.tool_names = {"send_sms"}
    ctx.available_all = {"send_sms"}
    ctx.sms_draft = complete_sms_draft(sms_text, history=[], contacts=_book())
    await _prepare_sms_first_move(loop, ctx, sms_text, {})
    assert ctx.sms_preinject is None

    # Control: the same arming path does arm for the real request.
    real_text = "text mom that I'm running late"
    real = _ctx(text=real_text)
    real.tool_names = {"send_sms"}
    real.available_all = {"send_sms"}
    real.sms_draft = complete_sms_draft(real_text, history=[], contacts=_book())
    await _prepare_sms_first_move(_FakeLoop(), real, real_text, {})
    assert real.sms_preinject is not None
