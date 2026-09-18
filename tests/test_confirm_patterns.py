"""The confirmation drift, pinned so it cannot happen again quietly.

Three modules each hand-wrote "match an utterance that is nothing but yes",
and the three copies disagreed. Not about anything anyone had decided —
about a comma. Email's trailing allowance was ``(?:\\s+please)?`` where SMS
took ``(?:\\s*,?\\s*please)?``, so "yes, please" confirmed a text and a
calendar event and did nothing whatever to an email. The user says it, nothing
happens, they say it again. There is no error and nothing in a log.

That class of bug has one property that makes it worth a test file: it is
invisible from inside any one module. Each regex is locally reasonable. Only
the three side by side show the disagreement, so the test has to be the thing
that puts them side by side.

The second half of this file is the distinction the shared builder turned up,
which none of the three had right. `_SEND_CONFIRM` was matching two different
kinds of utterance:

- "yes", "ok", "please" — content-free, could be answering anything in the
  conversation or be a fragment out of room noise.
- "send the text", "send it now" — names the act, and nothing else in the room
  it could be answering.

Email required no offer for either, which is how a stale "yes" revived a
sendable draft (see `test_history_revival`). SMS required one for both, which
meant a user who said "send the text" after the model stalled got silence.
Both wrong, opposite directions, same cause.
"""

from __future__ import annotations

import pytest

from arelis.core.agenda_complete import _PROCEED_ASK as AGENDA_ASK
from arelis.core.agenda_complete import _SEND_CONFIRM as AGENDA_CONFIRM
from arelis.core.confirm_patterns import (
    affirmation_pattern,
    send_command_pattern,
    send_confirm_pattern,
)
from arelis.core.email_complete import _PROCEED_ASK as EMAIL_ASK
from arelis.core.email_complete import _SEND_CONFIRM as EMAIL_CONFIRM
from arelis.core.sms_complete import _PROCEED_ASK as SMS_ASK
from arelis.core.sms_complete import _SEND_COMMAND as SMS_COMMAND
from arelis.core.sms_complete import _SEND_CONFIRM as SMS_CONFIRM

CONFIRMS = (SMS_CONFIRM, EMAIL_CONFIRM, AGENDA_CONFIRM)
CHANNELS = ("sms", "email", "agenda")


def _who_accepts(text: str) -> set[str]:
    return {
        name
        for name, pattern in zip(CHANNELS, CONFIRMS, strict=True)
        if pattern.match(text)
    }


# Ordinary agreement. Every channel has to take all of it — this is the list
# whose disagreements were pure accident.
@pytest.mark.parametrize(
    "text",
    [
        "yes",
        "Yes.",
        "yes,",
        "yes please",
        "yes, please",
        "Yes , please",
        "yep",
        "yeah",
        "ok",
        "okay",
        "OK.",
        "okay,",
        "go ahead",
        "Go ahead!",
        "do it",
        "do it please",
    ],
)
def test_an_ordinary_yes_means_yes_on_every_channel(text: str) -> None:
    """The regression that motivated the module.

    "yes, please" is the specific one that was broken, and it was broken only
    for email. The rest are here because the same three regexes disagreed
    about trailing commas and about the word "please" in four more places, and
    a parametrized list is how that stays fixed.
    """
    assert _who_accepts(text) == set(CHANNELS), (
        f"{text!r} is accepted by {_who_accepts(text) or 'nobody'} and not by "
        "the rest. An ordinary yes is not domain knowledge; if one channel "
        "disagrees, punctuation has drifted again."
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # These three ARE domain knowledge, and the split is deliberate.
        ("ship it", {"email"}),
        ("proceed", {"agenda"}),
        ("send the text", {"sms"}),
        ("send the email", {"email"}),
        ("please", {"sms", "agenda"}),
    ],
)
def test_the_verbs_that_differ_differ_on_purpose(text: str, expected: set) -> None:
    """Sending a text and creating an event are different acts.

    "ship it" is a thing people say about email and not about a dentist
    appointment. "proceed" is unambiguous for a calendar create and is not for
    a send, where the Allow card's own button reads Confirm and the word is as
    likely to be the user reading the UI back. Keeping these apart is why the
    verb lists are arguments at the call site rather than buried in the
    builder.
    """
    assert _who_accepts(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "sure",
        "no",
        "not yet",
        "cancel",
        "send",
        "yes but change the body first",
        "yes and also text Brian that I am late",
        "send the text to Brian saying hello",
        "please send the report",
        "do it tomorrow",
        "okay so",
        "yesterday",
        "",
        "   ",
    ],
)
def test_anything_carrying_new_content_is_not_a_confirmation(text: str) -> None:
    """The anchoring, which is the safety property of the whole module.

    "Yes, and also text Brian that I am late" is a new turn with new content.
    Treating the leading "yes" as a grant would send the draft in history
    while the user was in the middle of replacing it. "sure" and bare
    "confirm" are refused everywhere too — deliberately, because neither is
    on any channel's list and the confirmation only counts when it is the
    entire thing the user said.
    """
    assert _who_accepts(text) == set(), (
        f"{text!r} is being read as a bare confirmation by "
        f"{_who_accepts(text)}. It carries content the draft in history does "
        "not have."
    )


def test_a_bare_yes_and_an_explicit_command_are_told_apart() -> None:
    """The distinction the side-by-side turned up. See the module docstring.

    A caller needs both halves and needs them separately: the coarse pattern
    to know a draft has to be revived at all, and the command pattern to know
    whether the user was consenting to something offered or instructing
    outright.
    """
    for text in ["yes", "ok", "please", "yes, please", "go ahead"]:
        assert SMS_CONFIRM.match(text), text
        assert not SMS_COMMAND.match(text), (
            f"{text!r} reads as an explicit command. It carries no content, so "
            "it is only a grant for something that was actually offered."
        )
    for text in ["send the text", "send it", "send it now", "please send it"]:
        assert SMS_CONFIRM.match(text), text
        assert SMS_COMMAND.match(text), (
            f"{text!r} names the act. Requiring an offer for it is what made "
            "SMS refuse in silence when the model stalled instead of asking."
        )


def test_the_coarse_pattern_is_exactly_the_two_halves_together() -> None:
    """If it were not, a caller could revive on one and refuse on the other."""
    affirm = affirmation_pattern("please")
    command = send_command_pattern(r"send\s+(?:the\s+)?(?:text|it)")
    both = send_confirm_pattern(r"send\s+(?:the\s+)?(?:text|it)", affirmations=("please",))
    for text in ["yes", "please", "send it", "send the text", "sure", "no", "yes now"]:
        assert bool(both.match(text)) == bool(affirm.match(text) or command.match(text)), text


def test_the_assistant_offering_is_recognised_on_every_phrasing_it_uses() -> None:
    """This is what makes a later bare "yes" mean anything at all.

    Agenda accepted "would you like me to proceed" but not "shall I proceed",
    because its list was written out by hand and that line was simply missed.
    Sharing the skeleton is what fixed it, and this is the test that would
    have caught it.
    """
    for text in [
        "Would you like me to send it?",
        "Would you like to send it?",
        "Shall I send it?",
        "Want me to send that?",
        "Proceed with sending?",
    ]:
        assert SMS_ASK.search(text), text
        assert EMAIL_ASK.search(text), text
    for text in [
        "Would you like me to proceed?",
        "Would you like me to create the event?",
        "Shall I create the event?",
        "Shall I proceed?",
        "Want me to proceed?",
        "Proceed with creating the event?",
    ]:
        assert AGENDA_ASK.search(text), text


def test_a_sentence_that_is_not_an_offer_does_not_latch_one() -> None:
    """A false offer here turns the next stray "yes" into a send."""
    for text in [
        "I have drafted it.",
        "Ready when you are.",
        "Anything else?",
        "Here is a draft for you to look over.",
        "It is raining in your area.",
    ]:
        assert not SMS_ASK.search(text), text
        assert not AGENDA_ASK.search(text), text


def test_the_send_channels_treat_the_word_confirm_as_an_offer_and_agenda_does_not() -> None:
    """A real difference, kept. The Allow card's button says Confirm.

    On the send channels a model sentence containing "confirm" is more often
    the assistant narrating that card than anything else, and reading it as an
    offer is what lets the following "yes" land. Agenda's list leaves it out,
    and this pins that as a choice rather than another omission.
    """
    assert SMS_ASK.search("Please confirm.")
    assert EMAIL_ASK.search("Awaiting your confirmation.")
    assert not AGENDA_ASK.search("Please confirm.")
