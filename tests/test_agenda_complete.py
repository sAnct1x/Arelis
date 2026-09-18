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
    AgendaDraft,
    agenda_force_call_notice,
    agenda_preflight_nudge,
    agenda_read_action,
    complete_agenda_draft,
    draft_agenda_create_args,
    draft_agenda_delete_args,
    fill_agenda_args,
    last_agenda_create_summary,
    lock_agenda_delete_args,
    looks_like_calendar_close,
    looks_like_calendar_create,
    looks_like_calendar_delete,
    looks_like_calendar_open,
    looks_like_calendar_read,
    normalize_agenda_start,
    normalize_calendar_speech,
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
    assert draft.provider == "google"
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


def test_an_utterance_with_no_time_at_all_is_not_a_draft() -> None:
    assert parse_agenda_utterance("add something to my calendar") is None


def test_a_reminder_keeps_the_whole_clause_as_notes_and_a_short_title() -> None:
    draft = parse_agenda_utterance("set a reminder to call the bank tomorrow at 10am")
    assert draft is not None
    assert draft.summary.startswith("Reminder:")
    assert "call the bank" in draft.description


def test_the_named_provider_wins_over_the_google_default() -> None:
    draft = parse_agenda_utterance(
        "add a calendar event called Standup, tomorrow at 9am, on outlook"
    )
    assert draft is not None
    assert draft.provider == "outlook"


def test_an_hour_long_event_gets_an_end() -> None:
    draft = parse_agenda_utterance("add an event called Standup, tomorrow at 9am, for 1 hour")
    assert draft is not None
    assert draft.end
    span = _parse_dt(draft.end, field="end") - _parse_dt(draft.start, field="start")
    assert span == timedelta(hours=1)


# ----------------------------------------- the start the tool has to swallow


def test_a_bare_tomorrow_still_reaches_the_tool_as_a_real_date() -> None:
    """The defect the missing test file hid, and the most ordinary ask there is.

    `complete` gates the force-gate inject, so a complete draft is a call that
    is going to be made. `start="tomorrow"` was complete, and `agenda` answers
    it with `Invalid start 'tomorrow'; use ISO date/datetime` — a turn that
    dead-ends after the user has already seen a confirm card.
    """
    draft = parse_agenda_utterance("add an event called Dentist, tomorrow")
    assert draft is not None
    assert draft.complete
    parsed = _parse_dt(draft.start, field="start")
    assert parsed.date() == (_wall() + timedelta(days=1)).date()


def test_every_start_a_complete_draft_offers_is_one_agenda_accepts() -> None:
    """The general form of the above, over the phrasings that reach this module.

    Stated as a loop on purpose. The bare-day case is the one that was broken,
    but the contract worth holding is that `complete` and "the tool will take
    it" are the same question, not two questions that happen to agree.
    """
    asks = [
        "add an event called Dentist, tomorrow",
        "add an event called Dentist, tomorrow at 3pm",
        "add an event called Dentist, today at 11pm",
        "add an event called Dentist, tonight at 8pm",
        "add a calendar event called Standup, monday at 9am",
        "schedule a meeting titled Budget review, on August 13th at 7am",
        "add an event called Anniversary, two weeks from today at 6pm",
        "put Team sync on my calendar tomorrow at 9am",
    ]
    for ask in asks:
        draft = parse_agenda_utterance(ask)
        assert draft is not None and draft.complete, ask
        # Raises ValueError if the tool would refuse it.
        _parse_dt(draft.start, field="start")


def test_a_weekday_inside_the_title_does_not_win_over_the_real_time() -> None:
    """ "Taco Tuesday tomorrow at 6pm" is one event, not a Tuesday.

    `_WHEN` takes the leftmost match, and a weekday in the title sits to the
    left of the clause that carries the clock. The draft came out with
    `start="Tuesday"` — unparseable, and the wrong day even if it had parsed.
    """
    draft = parse_agenda_utterance("add an event called Taco Tuesday tomorrow at 6pm")
    assert draft is not None
    parsed = _parse_dt(draft.start, field="start")
    assert parsed.hour == 18
    assert parsed.date() == (_wall() + timedelta(days=1)).date()


# ------------------------------------------------------------------ the title


def test_the_title_does_not_swallow_the_time_the_user_said_it_at() -> None:
    """A comma is not available over voice, and the title depended on one.

    `_TITLE` runs to the first comma or period, so typed
    "called Dentist, tomorrow at 3pm" gave "Dentist" and spoken
    "called Dentist tomorrow at 3pm" gave "Dentist tomorrow at 3pm" — the same
    event, named differently depending on punctuation nobody dictates.
    """
    spoken = parse_agenda_utterance("add a calendar event called Dentist tomorrow at 3pm")
    typed = parse_agenda_utterance("add a calendar event called Dentist, tomorrow at 3pm")
    assert spoken is not None and typed is not None
    assert spoken.summary == "Dentist"
    assert spoken.summary == typed.summary


def test_a_month_and_day_clause_is_stripped_from_the_title_too() -> None:
    draft = parse_agenda_utterance("schedule a meeting titled Budget review on August 13th at 7am")
    assert draft is not None
    assert draft.summary == "Budget review"


def test_a_title_that_ends_in_a_weekday_keeps_it_when_no_clock_follows() -> None:
    """The limit of the strip above, and the reason it is not a plain split.

    "Taco Tuesday" is a real event name. Removing every trailing day word would
    rename it "Taco". A weekday only goes when a time follows it, which is what
    separates a name from a when-clause; today / tonight / tomorrow go either
    way, because nobody titles an event "Dentist tomorrow".
    """
    draft = parse_agenda_utterance("add an event called Taco Tuesday tomorrow at 6pm")
    assert draft is not None
    assert draft.summary == "Taco Tuesday"


def test_a_title_with_a_time_of_its_own_and_no_day_still_loses_the_time() -> None:
    draft = parse_agenda_utterance("add an event called Coffee with the team at 3pm")
    assert draft is not None
    assert draft.summary == "Coffee with the team"


# --------------------------------------------------- the guard and the parser


def test_a_text_first_utterance_is_not_a_calendar_create() -> None:
    """The guard and the parser disagreed, and the parser is the one that ships.

    `looks_like_calendar_create` vetoes an utterance that opens with an SMS
    verb — "text my wife and…" is a send, and `parse_sms_utterance` declines
    the mirror case for the same reason. `parse_agenda_utterance` went
    straight to `_CREATE` and skipped the veto, so `turn_prepare` — which
    calls `complete_agenda_draft` unconditionally, without the guard in front
    of it — armed the agenda force gate on a text turn.
    """
    ask = "text my wife and add an event called Dinner for tomorrow at 7pm"
    assert not looks_like_calendar_create(ask)
    assert parse_agenda_utterance(ask) is None


def test_a_delete_is_never_read_as_a_create() -> None:
    for ask in (
        "delete the Dentist event",
        "cancel my dentist appointment tomorrow at 3pm",
        "remove that meeting",
    ):
        assert looks_like_calendar_delete(ask), ask
        assert not looks_like_calendar_create(ask), ask
        assert parse_agenda_utterance(ask) is None, ask


# ---------------------------------------------------------- history revival


def test_yes_after_the_assistant_offered_to_create_revives_the_draft() -> None:
    """The walk that never ran.

    `complete_agenda_draft` iterated the whole history including the turn it
    was called for, so the first thing it looked at was the user's own "yes".
    That parses as nothing, `saw_ask` was still false, and it broke out on
    iteration one — every time, for every conversation. The test that would
    have caught it is the one that passes history the way the callers do.
    """
    ask = "add a calendar event called Dentist, tomorrow at 3pm"
    rows = _turns(
        ("user", ask),
        ("assistant", "Would you like me to proceed with creating it?"),
    )
    draft = complete_agenda_draft("yes", history=_as_live_history(rows, "yes"))
    assert draft is not None
    assert draft.summary == "Dentist"
    assert draft.complete


def test_yes_after_an_unrelated_turn_does_not_revive_a_stale_event() -> None:
    """Agenda gets this right by a different route than SMS, so pin it.

    `sms_complete` requires that the assistant have just asked before a bare
    "yes" revives anything. Agenda has no such flag on the first hop — it
    relies on breaking out at the first user turn that is not a calendar
    create, which covers the same hazard as long as the walk is not allowed
    to skip past one. If that break is ever loosened, this goes red.
    """
    rows = _turns(
        ("user", "add a calendar event called Dentist, tomorrow at 3pm"),
        ("assistant", "Created on google: Dentist @ 2026-01-01T15:00:00."),
        ("user", "what is the weather"),
        ("assistant", "Clear and mild."),
    )
    assert complete_agenda_draft("yes", history=_as_live_history(rows, "yes")) is None


def test_yes_with_no_calendar_ask_anywhere_creates_nothing() -> None:
    rows = _turns(
        ("user", "what is on my plate today"),
        ("assistant", "Nothing scheduled."),
    )
    assert complete_agenda_draft("yes", history=_as_live_history(rows, "yes")) is None


def test_a_fresh_calendar_ask_does_not_need_history_at_all() -> None:
    draft = complete_agenda_draft(
        "add a calendar event called Dentist, tomorrow at 3pm", history=[]
    )
    assert draft is not None
    assert draft.summary == "Dentist"


# ------------------------------------------------------------------- deletes


def test_a_delete_at_a_named_day_does_not_point_at_today() -> None:
    """The one on this list that can remove the wrong event.

    `_CLOCK` read "9am" and built the timestamp from `datetime.now()`, so the
    day the user named was dropped. `agenda._delete_resolved` filters matches
    on `starts_at.date() == when.date() and starts_at.hour == when.hour`, so
    for a daily standup that is not a failed delete — it is today's standup
    deleted instead of tomorrow's.
    """
    args = draft_agenda_delete_args("delete the Standup event tomorrow at 9am")
    when = _parse_dt(args["start"], field="start")
    assert when.hour == 9
    assert when.date() == (_wall() + timedelta(days=1)).date()


def test_a_delete_with_a_bare_clock_still_means_today() -> None:
    args = draft_agenda_delete_args("delete the Standup event at 9am")
    when = _parse_dt(args["start"], field="start")
    assert when.hour == 9
    assert when.date() == _wall().date()


def test_a_delete_with_no_clock_carries_no_start_at_all() -> None:
    """An absent filter is not the same as a filter on midnight today."""
    args = draft_agenda_delete_args("delete the Standup event")
    assert "start" not in args
    assert args["summary"] == "Standup"
    assert args["keep"] == 0


def test_a_titled_delete_removes_every_copy_and_a_duplicate_ask_keeps_one() -> None:
    assert draft_agenda_delete_args("delete the Standup event")["keep"] == 0
    assert draft_agenda_delete_args("delete two of them")["keep"] == 1
    assert draft_agenda_delete_args("delete the duplicates")["keep"] == 1


def test_a_pasted_google_id_is_the_whole_delete() -> None:
    args = draft_agenda_delete_args("delete google:abc123def")
    assert args["event_id"] == "google:abc123def"
    assert "summary" not in args


def test_a_pronoun_is_never_sent_as_the_title_to_delete() -> None:
    """The worst one found in this module, and it hides behind ordinary words.

    `_DELETE_TITLED` read "delete that event" as title="that". The tool matches
    `summary` as a **substring** of every event's title and description, and
    this module pairs it with keep=0, which means "remove every copy". So the
    most natural way to say "the one you just made" resolved to every event
    with the word "that" anywhere in it and deleted all of them.

    `agenda._delete_resolved` does have an ambiguity guard, and it does not
    help: it only fires when `keep` is None, and keep is 0 here.
    """
    args = draft_agenda_delete_args(
        "delete that event",
        history=_turns(("assistant", "Created on google: Standup @ 2026-01-01T09:00:00-05:00")),
    )
    assert args["summary"] == "Standup"

    # And with nothing to fall back to, no title at all beats a wrong one.
    bare = draft_agenda_delete_args("delete this event")
    assert not bare.get("summary")


def test_a_real_title_is_still_a_title() -> None:
    """The limit of the rule above: only the pronouns go."""
    assert draft_agenda_delete_args("delete the Standup event")["summary"] == "Standup"
    assert draft_agenda_delete_args("delete the Budget review event")["summary"] == "Budget review"


def test_a_receipt_beats_history_for_the_last_created_title() -> None:
    assert (
        last_agenda_create_summary(
            receipts=[{"tool": "agenda", "summary": "Standup"}],
            history=_turns(("assistant", "Created on google: Older @ 2026-01-01T09:00")),
        )
        == "Standup"
    )


def test_the_delete_lock_forces_keep_zero_over_a_model_guess() -> None:
    """keep=1 on a titled delete leaves the event the user asked to remove."""
    locked = lock_agenda_delete_args({"summary": "Standup", "keep": 1}, "delete the Standup event")
    assert locked["keep"] == 0


# ------------------------------------------------------------- the args lock


def test_a_complete_draft_overwrites_a_title_the_model_invented() -> None:
    draft = AgendaDraft(summary="Dentist", start="2026-01-05T15:00:00-05:00")
    out = fill_agenda_args({"action": "create", "summary": "Doctor", "start": "2026-01-01"}, draft)
    assert out["summary"] == "Dentist"
    assert out["start"] == "2026-01-05T15:00:00-05:00"


def test_a_read_call_is_rewritten_to_the_create_the_user_asked_for() -> None:
    """A 7B answers "add an event" with `action=list` and burns the rounds."""
    draft = AgendaDraft(summary="Dentist", start="2026-01-05T15:00:00-05:00")
    for action in ("", "list", "today", "range", "get"):
        assert fill_agenda_args({"action": action}, draft)["action"] == "create"


def test_a_delete_call_is_never_rewritten_into_a_create() -> None:
    draft = AgendaDraft(summary="Dentist", start="2026-01-05T15:00:00-05:00")
    out = fill_agenda_args({"action": "delete", "summary": "Other"}, draft)
    assert out["action"] == "delete"
    assert out["summary"] == "Other"


def test_a_relative_start_is_normalized_even_with_no_draft_to_lock() -> None:
    out = fill_agenda_args({"action": "create", "start": "tomorrow at 9am"}, None)
    assert _parse_dt(out["start"], field="start").hour == 9
    assert out["provider"] == "google"


def test_the_inject_args_are_the_draft_and_nothing_else() -> None:
    draft = AgendaDraft(summary="Dentist", start="2026-01-05T15:00:00-05:00")
    assert draft_agenda_create_args(draft) == {
        "action": "create",
        "summary": "Dentist",
        "start": "2026-01-05T15:00:00-05:00",
        "provider": "google",
    }


# -------------------------------------------------------- normalize the start


def test_a_stale_year_the_model_invented_is_clamped_to_this_one() -> None:
    now = datetime(2026, 9, 17, 12, 0).astimezone()
    assert normalize_agenda_start("2023-01-05", now=now).startswith("2026-01-05")


def test_an_iso_datetime_that_is_already_right_is_left_alone() -> None:
    now = datetime(2026, 9, 17, 12, 0).astimezone()
    out = normalize_agenda_start("2026-09-18T09:00:00", now=now)
    assert out.startswith("2026-09-18T09:00:00")


def test_weeks_from_today_lands_on_the_right_day_and_hour() -> None:
    now = datetime(2026, 9, 17, 12, 0).astimezone()
    assert normalize_agenda_start("two weeks from today at 6pm", now=now).startswith(
        "2026-10-01T18:00"
    )


def test_something_that_is_not_a_time_comes_back_untouched() -> None:
    """Fail-soft is right here: the tool's error is clearer than a guess."""
    assert normalize_agenda_start("whenever you like") == "whenever you like"


# ------------------------------------------------------------------- speech


def test_the_splits_whisper_puts_in_a_calendar_ask_are_folded_back() -> None:
    assert normalize_calendar_speech("add an event to morrow at eleven a m") == (
        "add an event tomorrow at 11am"
    )
    assert normalize_calendar_speech("set a reminder to night at eight pm") == (
        "set a reminder tonight at 8pm"
    )


def test_whisper_hearing_add_an_event_as_at_an_event_still_parses() -> None:
    assert looks_like_calendar_create("at an event for tomorrow at 3pm")


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


def test_asking_for_the_website_is_not_asking_for_the_tile() -> None:
    """`agenda(action=open)` opens a panel. It cannot open a browser."""
    assert not looks_like_calendar_open("open calendar.google.com")
    assert not looks_like_calendar_open("open my calendar in chrome")


def test_closing_the_panel_is_told_apart_from_deleting_an_event() -> None:
    assert looks_like_calendar_close("close the calendar")
    assert not looks_like_calendar_close("hide the calendar event")


def test_the_read_window_comes_from_the_day_they_named() -> None:
    assert agenda_read_action("calendar today") == "today"
    assert agenda_read_action("what is on my calendar tomorrow") == "tomorrow"
    assert agenda_read_action("my agenda this week") == "list"


# ------------------------------------------------------------------ notices


def test_the_preflight_nudge_carries_the_args_and_not_a_description() -> None:
    """The nudge exists so the 7B has nothing left to invent."""
    draft = AgendaDraft(summary="Dentist", start="2026-01-05T15:00:00-05:00")
    nudge = agenda_preflight_nudge(draft)
    assert 'summary="Dentist"' in nudge
    assert 'start="2026-01-05T15:00:00-05:00"' in nudge
    assert "action=create" in nudge


def test_a_draft_with_a_time_and_no_title_still_names_the_time() -> None:
    nudge = agenda_preflight_nudge(AgendaDraft(summary="", start="2026-01-05T15:00:00-05:00"))
    assert 'start="2026-01-05T15:00:00-05:00"' in nudge
    assert "summary" in nudge


def test_the_force_notice_says_chatting_is_not_creating() -> None:
    notice = agenda_force_call_notice(
        AgendaDraft(summary="Dentist", start="2026-01-05T15:00:00-05:00")
    )
    assert "Chatting is not creating" in notice
    assert 'summary="Dentist"' in notice
    assert "Do not send_sms" in notice
