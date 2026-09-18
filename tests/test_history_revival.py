"""A stray "yes" must not send a draft the user walked away from.

This is the file for item 3.7, and the defect it exists to catch is the worst
one this lane found. `email_complete`'s confirmation walk had no stop
condition. Its first pass went backwards through history and `continue`d over
every user turn that did not parse as mail, so:

    user       email bob@example.com about Dinner: See you at 7
    assistant  Here is a draft.
    user       actually never mind, what is the weather
    assistant  It is raining.
    user       who wrote Dracula
    assistant  Bram Stoker.
    user       thanks
    assistant  Any time.
    user       yes

returned that draft. Complete, addressed, body intact, handed to the force
gate. The Allow card would have described it perfectly correctly, because the
address and the body genuinely are the ones the user dictated — just not now,
and not in answer to this. "Never mind" did not stop it and neither did four
unrelated exchanges.

`sms_complete` had carried a guard against exactly this for a year, in a
comment worth quoting: *bare "yes" after a non-SMS turn must not revive an
older complete draft — only confirm when the assistant just asked about
sending.* Agenda had a version of it too. Email was the outlier, and email is
the channel where it matters most: a text goes to a number the user has texted
before, an email goes into a stranger's permanent archive.

The rule that tells the two conversations apart is not whether the assistant
offered. It is whether the user has *moved on*. A user turn that is not about
the draft is a new subject, and consent does not carry across it.

The three-channel matrix at the end is the real subject of the file. Each
individual walk looked locally reasonable; the disagreement was only visible
with all three answering the same question at once, which is why the roadmap's
claim that this was "roughly 80 lines, written three times" was worth checking
rather than acting on.
"""

from __future__ import annotations

import pytest

from arelis.contacts import Contact, normalize_phone
from arelis.core.agenda_complete import complete_agenda_draft
from arelis.core.email_complete import complete_email_draft
from arelis.core.history_revival import last_draft_before_confirm
from arelis.core.memory import ChatMessage
from arelis.core.sms_complete import complete_sms_draft


def _book() -> dict[str, Contact]:
    phone = "5551112222"
    return {
        "brian": Contact(
            alias="brian",
            name="Brian",
            phone=phone,
            digits=normalize_phone(phone),
            email="brian@example.com",
        )
    }


DRAFTS = {
    "sms": "text Brian saying I am running late",
    "email": "Email bob@example.com about Dinner: See you at 7",
    "agenda": "add an event called Dentist tomorrow at 3pm",
}
OFFERS = {
    "sms": "Would you like me to send it?",
    "email": "Would you like me to send it?",
    "agenda": "Shall I create the event?",
}
COMMANDS = {"sms": "send the text", "email": "send the email", "agenda": "proceed"}
STALL = "Ready when you are."

MOVED_ON = [
    ("assistant", STALL),
    ("user", "actually never mind, what is the weather"),
    ("assistant", "It is raining."),
]
LONG_GONE = [
    *MOVED_ON,
    ("user", "who wrote Dracula"),
    ("assistant", "Bram Stoker."),
    ("user", "thanks"),
    ("assistant", "Any time."),
]


def _revives(channel: str, middle: list[tuple[str, str]], said: str) -> bool:
    """Does this channel bring a draft back for `said`, given this history?

    The current turn is appended to history on purpose. `AgentLoop` adds the
    user message before any of these functions read it, so a test that leaves
    it off is testing a shape production never sees — which is how the agenda
    walk stayed dead for as long as it did.
    """
    turns = [("user", DRAFTS[channel]), *middle, ("user", said)]
    history = [ChatMessage(role=role, content=content) for role, content in turns]
    if channel == "sms":
        draft = complete_sms_draft(said, history=history, contacts=_book())
    elif channel == "email":
        draft = complete_email_draft(said, history=history, contacts=_book())
    else:
        draft = complete_agenda_draft(said, history=history)
    return draft is not None


@pytest.mark.parametrize("channel", ["sms", "email", "agenda"])
def test_a_yes_right_after_the_assistant_offered_brings_the_draft_back(
    channel: str,
) -> None:
    """The feature. Without this the guards below would be free to refuse all."""
    assert _revives(channel, [("assistant", OFFERS[channel])], "yes")


@pytest.mark.parametrize("channel", ["sms", "email", "agenda"])
def test_a_yes_after_the_user_changed_the_subject_revives_nothing(
    channel: str,
) -> None:
    """The bug. Email said yes to this for a year; the other two did not."""
    assert not _revives(channel, MOVED_ON, "yes"), (
        "A draft the user said 'never mind' to came back on a bare yes. "
        "This is the defect item 3.7 exists to catch."
    )


@pytest.mark.parametrize("channel", ["sms", "email", "agenda"])
def test_a_yes_four_exchanges_after_the_draft_revives_nothing(channel: str) -> None:
    """How far email used to reach: there was no limit at all."""
    assert not _revives(channel, LONG_GONE, "yes")


@pytest.mark.parametrize("channel", ["sms", "email", "agenda"])
def test_an_explicit_command_does_not_reach_across_a_change_of_subject_either(
    channel: str,
) -> None:
    """Naming the act buys you the offer requirement, not the subject bound.

    Tempting to let "send the text" through here on the grounds that the user
    said what they wanted. But they said "never mind" first, and there is no
    draft since — so the only thing to revive is the one they cancelled. The
    one-line version of the SMS fix seeded `saw_ask` from the command and got
    this wrong; it is a separate flag for this reason.
    """
    assert not _revives(channel, MOVED_ON, COMMANDS[channel])
    assert not _revives(channel, LONG_GONE, COMMANDS[channel])


def test_an_explicit_send_command_works_when_the_model_stalled_instead_of_asking() -> None:
    """The other direction of the same mistake, this one SMS's.

    "Ready when you are." is not an offer by any of the ask patterns, so a
    bare "yes" after it is correctly refused. But SMS refused "send the text"
    too, every time, with nothing said about why — the user repeats themselves
    and the assistant keeps chatting.
    """
    assert _revives("sms", [("assistant", STALL)], "send the text")
    assert _revives("email", [("assistant", STALL)], "send the email")


def test_a_fresh_ask_does_not_need_history_at_all() -> None:
    """The revival walk is a fallback, not the main path."""
    assert _revives("sms", [], "text Brian saying I am running late")


# ------------------------------------------------- the shared walk, on its own


def _pairs(*turns: tuple[str, str]) -> list[tuple[str, str]]:
    return list(turns)


def test_the_shared_walk_takes_the_newest_draft_it_can_accept() -> None:
    found = last_draft_before_confirm(
        _pairs(("user", "draft-one"), ("assistant", "ok"), ("user", "draft-two")),
        parse=lambda text: text if text.startswith("draft") else None,
        accept=lambda draft: True,
    )
    assert found == "draft-two"


def test_the_shared_walk_stops_where_the_user_moved_on() -> None:
    """With no offer latched, an unparseable user turn ends it. The whole point."""
    found = last_draft_before_confirm(
        _pairs(("user", "draft-one"), ("assistant", "ok"), ("user", "weather?")),
        parse=lambda text: text if text.startswith("draft") else None,
        accept=lambda draft: True,
    )
    assert found is None


def test_a_reask_lets_the_walk_past_a_turn_it_cannot_parse() -> None:
    """The latch only licenses what is *older* than the offer, which is the point.

    The walk runs backwards, so the offer has to be newer than the turn it
    excuses. That is not an implementation detail — it is the rule. An
    unparseable turn newer than every offer means the user has said something
    since being asked, and consent does not survive that. An unparseable turn
    *older* than the newest offer is a mumble the assistant then asked again
    about, which is an answer attempt.

    Chronologically here: draft, "what should the body be?", "um", asked
    again, and then the confirmation the caller has already matched.
    """
    found = last_draft_before_confirm(
        _pairs(
            ("user", "draft-one"),
            ("assistant", "what should the body be?"),
            ("user", "um"),
            ("assistant", "what should I put?"),
        ),
        parse=lambda text: text if text.startswith("draft") else None,
        accept=lambda draft: True,
        asked=lambda content: "what should" in content,
    )
    assert found == "draft-one"


def test_a_mumble_newer_than_every_offer_still_ends_the_walk() -> None:
    """The companion to the above, and the half that carries the safety."""
    found = last_draft_before_confirm(
        _pairs(
            ("user", "draft-one"),
            ("assistant", "what should the body be?"),
            ("user", "um"),
        ),
        parse=lambda text: text if text.startswith("draft") else None,
        accept=lambda draft: True,
        asked=lambda content: "what should" in content,
    )
    assert found is None


def test_a_draft_the_caller_will_not_accept_is_skipped_rather_than_returned() -> None:
    """`accept` is separate from `parse` because email needs both questions.

    Email's first pass wants only complete composes and has a second pass for
    the rest; agenda will take anything with a start time. So a turn that
    parses but fails `accept` must be stepped over, not handed back — and the
    older draft behind it is the answer.

    The newest draft has to be the unacceptable one for this to test anything.
    An earlier version put them the other way round and the walk returned the
    right answer whether `accept` was consulted or not, which made the test
    decoration: deleting the `accept` call from the walk did not fail it.
    """
    found = last_draft_before_confirm(
        _pairs(
            ("user", "draft-full"),
            ("assistant", "what should the body be?"),
            ("user", "draft-partial"),
            ("assistant", "what should I put?"),
        ),
        parse=lambda text: text if text.startswith("draft") else None,
        accept=lambda draft: draft.endswith("full"),
        asked=lambda content: "what should" in content,
    )
    assert found == "draft-full", (
        "The walk returned a draft the caller said it could not use. For "
        "email that means reviving a compose with no body as though it were "
        "ready to send."
    )


def test_an_empty_history_revives_nothing_rather_than_raising() -> None:
    assert last_draft_before_confirm([], parse=lambda text: text, accept=lambda draft: True) is None
