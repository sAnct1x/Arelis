"""A declined or complaining send ask must never become a send draft.

Filament voice mode runs a pre-model send_sms / send_email with no card, so
"don't text mom that I'm running late" building a complete draft could send a
real text. The send verb only counts when no "don't / no need / never / why
did you" sits before it in the same clause.
"""

from __future__ import annotations

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.email_complete import complete_email_draft, parse_email_utterance
from arelis.core.preflight import detect_intents
from arelis.core.sms_complete import complete_sms_draft, parse_sms_utterance


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
