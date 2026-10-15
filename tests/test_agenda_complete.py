"""Calendar draft reconstruction — the module that had no test file.

`sms_complete` and `email_complete` each have a real suite. `agenda_complete`
had none: `test_agenda_parse.py` reads `tools/agenda._parse_dt`, which is the
tool on the far side of this module, not this module. So every claim in here
was unchecked, and the first pass over it found four defects that a live
session would have shown as "the calendar just doesn't work sometimes."

Three of them share one shape, and it is the shape worth remembering. This
module hands a draft to the force gate, which *injects* an `agenda(create)`
call without the model's help. So a draft that is wrong is not a suggestion
the model can decline — it is the call. `AgendaDraft.complete` is the only
thing standing between a half-parsed utterance and a confirm card, and it was
answering a weaker question than its callers were asking:

  - `start="tomorrow"` counted as complete, and `agenda` refuses it
    (`Invalid start 'tomorrow'; use ISO date/datetime`). "Add an event called
    Dentist tomorrow" is about as ordinary as a calendar ask gets.
  - the title swallowed the time clause, so the event was called
    "Dentist tomorrow at 3pm" unless the user happened to type a comma.
  - the delete draft read the clock and ignored the day, so "delete the
    standup tomorrow at 9am" pointed at *today* at 9am.

The fourth is a whole feature that never ran: the history walk did not drop
the current turn, and both callers pass history that already contains it.

Dates are asserted by shape rather than by literal, because these functions
read the wall clock and a test pinned to a day fails on that day next year.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from arelis.core.agenda_complete import (
    lock_agenda_delete_args,
    looks_like_calendar_open,
    looks_like_calendar_read,
    parse_agenda_utterance,
)
from arelis.tools.agenda import _parse_dt


def _turns(*rows: tuple[str, str]) -> list[dict[str, str]]:
    return [{"role": role, "content": content} for role, content in rows]


def _as_live_history(rows: list[dict[str, str]], user_text: str) -> list[dict[str, str]]:
    """History the way the two real callers pass it.

    `turn_prepare` runs `loop.memory.add("user", text)` before it builds any
    draft, so by the time `complete_agenda_draft` is reached the turn being
    parsed is already the last entry. A test that omits it is testing a shape
    that does not occur.
    """
    return [*rows, {"role": "user", "content": user_text}]


def _wall() -> datetime:
    return datetime.now().astimezone()


# ------------------------------------------------------------------ the parse


def test_a_titled_event_with_a_time_becomes_a_complete_draft() -> None:
    draft = parse_agenda_utterance("add a calendar event called Dentist, tomorrow at 3pm")
    assert draft is not None
    assert draft.complete
    assert draft.summary == "Dentist"
    assert draft.provider == "local"
    assert _parse_dt(draft.start, field="start").hour == 15


def test_an_event_with_no_title_is_an_incomplete_draft() -> None:
    """Incomplete is the useful answer: preflight still routes to agenda.

    A start with no summary must not be `complete`, because complete is what
    lets the force gate inject the create, and an event called "" is worse
    than asking.
    """
    draft = parse_agenda_utterance("add an event for tonight at 8pm")
    assert draft is not None
    assert draft.summary == ""
    assert not draft.complete
    assert _parse_dt(draft.start, field="start").hour == 20


def test_a_reminder_keeps_the_whole_clause_as_notes_and_a_short_title() -> None:
    draft = parse_agenda_utterance("set a reminder to call the bank tomorrow at 10am")
    assert draft is not None
    assert draft.summary.startswith("Reminder:")
    assert "call the bank" in draft.description


def test_an_hour_long_event_gets_an_end() -> None:
    draft = parse_agenda_utterance("add an event called Standup, tomorrow at 9am, for 1 hour")
    assert draft is not None
    assert draft.end
    span = _parse_dt(draft.end, field="end") - _parse_dt(draft.start, field="start")
    assert span == timedelta(hours=1)


# ----------------------------------------- the start the tool has to swallow


# ------------------------------------------------------------------ the title


# --------------------------------------------------- the guard and the parser


# ---------------------------------------------------------- history revival


# ------------------------------------------------------------------- deletes


def test_the_delete_lock_forces_keep_zero_over_a_model_guess() -> None:
    """keep=1 on a titled delete leaves the event the user asked to remove."""
    locked = lock_agenda_delete_args({"summary": "Standup", "keep": 1}, "delete the Standup event")
    assert locked["keep"] == 0


# ------------------------------------------------------------- the args lock


# -------------------------------------------------------- normalize the start


# ------------------------------------------------------------------- speech


# ------------------------------------------------------------------- guards


def test_opening_the_tile_is_told_apart_from_reading_the_day() -> None:
    assert looks_like_calendar_open("open my calendar")
    assert looks_like_calendar_open("pull up the agenda")
    assert not looks_like_calendar_read("open my calendar")
    assert looks_like_calendar_read("what is on my calendar today")
    assert not looks_like_calendar_open("what is on my calendar today")
    # "open the calendar for tomorrow" wants the day, not the panel.
    assert looks_like_calendar_read("open the calendar for tomorrow")
    assert not looks_like_calendar_open("open the calendar for tomorrow")


# ------------------------------------------------------------------ notices


