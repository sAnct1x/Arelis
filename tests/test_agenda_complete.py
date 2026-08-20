"""Agenda create draft lock."""

from __future__ import annotations

from datetime import datetime

from arelis.core.agenda_complete import (
    complete_agenda_draft,
    fill_agenda_args,
    looks_like_calendar_create,
    looks_like_calendar_read,
    normalize_agenda_start,
    parse_agenda_utterance,
)
from arelis.tools.agenda import _parse_dt


def test_parse_create_with_title_and_when() -> None:
    draft = parse_agenda_utterance(
        "Add to my calendar an event called Arelis test tomorrow at 3pm"
    )
    assert draft is not None
    assert draft.complete
    assert "Arelis test" in draft.summary
    start = datetime.fromisoformat(draft.start)
    assert start.hour == 15
    assert start.tzinfo is not None


def test_fill_locks_complete_draft() -> None:
    draft = complete_agenda_draft(
        'Create an event called "Budget review" on 2026-08-12T15:00'
    )
    assert draft is not None and draft.complete
    out = fill_agenda_args(
        {
            "action": "create",
            "summary": "Wrong title",
            "start": "1999-01-01",
            "provider": "google",
        },
        draft,
    )
    assert out["summary"] == draft.summary
    assert out["start"] == normalize_agenda_start(draft.start)


def test_fill_ignores_non_create() -> None:
    draft = complete_agenda_draft(
        'Create an event called "X" on 2026-08-12T15:00'
    )
    out = fill_agenda_args({"action": "delete", "event_id": "abc"}, draft)
    assert out["action"] == "delete"
    assert "summary" not in out


def test_naive_iso_is_local_not_utc() -> None:
    """S11: 23:00 naive must stay 23:00 local, not become 19:00 Eastern."""
    dt = _parse_dt("2026-08-09T23:00:00", field="start")
    assert dt.tzinfo is not None
    assert dt.hour == 23
    assert dt.utcoffset() == datetime.now().astimezone().utcoffset()


def test_normalize_today_at_11pm_has_local_offset() -> None:
    fixed = datetime(2026, 8, 9, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)
    out = normalize_agenda_start("today at 11pm", now=fixed)
    parsed = datetime.fromisoformat(out)
    assert parsed.hour == 23
    assert parsed.day == 9
    assert parsed.tzinfo is not None


def test_parse_tonight_at_11pm() -> None:
    draft = parse_agenda_utterance(
        'Add to my calendar an event called "Push and commit" tonight at 11pm'
    )
    assert draft is not None and draft.complete
    assert "Push and commit" in draft.summary
    start = datetime.fromisoformat(draft.start)
    assert start.hour == 23


def test_parse_calendar_event_reminder_to_text() -> None:
    """Create-calendar + nested 'text my wife' is an agenda draft, not SMS."""
    draft = parse_agenda_utterance(
        "create a calendar event for tomorrow at 4pm. I want this calendar "
        "event to be a reminder to text my wife and tell her I love her."
    )
    assert draft is not None and draft.complete
    assert draft.start
    start = datetime.fromisoformat(draft.start)
    assert start.hour == 16
    assert "wife" in draft.summary.lower() or "text" in draft.summary.lower()
    assert "love" in (draft.description or draft.summary).lower()
    locked = fill_agenda_args({"action": "create", "summary": "Wrong"}, draft)
    assert locked["summary"] == draft.summary
    assert locked["start"] == draft.start
    assert locked.get("provider") == "google"


def test_looks_like_calendar_create_not_sms_lead() -> None:
    from arelis.core.agenda_complete import looks_like_calendar_create

    assert looks_like_calendar_create(
        "create a calendar event for tomorrow at 4pm as a reminder to text wife"
    )
    assert not looks_like_calendar_create("text my wife that I love her")


def test_voice_at_an_event_for_tomorrow_is_calendar_create() -> None:
    from arelis.core.agenda_complete import (
        looks_like_calendar_create,
        looks_like_calendar_delete,
        parse_agenda_utterance,
    )
    from arelis.core.preflight import detect_intents

    ask = "At an event for to morrow at eleven a m to go to the lab"
    assert looks_like_calendar_create(ask)
    draft = parse_agenda_utterance(ask)
    assert draft is not None and draft.complete
    assert "lab" in draft.summary.lower()
    start = datetime.fromisoformat(draft.start)
    assert start.hour == 11
    kinds = [h.kind for h in detect_intents(ask)]
    assert "agenda_create" in kinds
    assert "schedule" not in kinds
    assert looks_like_calendar_delete(
        "Delight the calendar event for to morrow"
    )
    assert not looks_like_calendar_create("is there an event for tomorrow")


def test_delete_two_of_them_is_calendar_delete() -> None:
    from arelis.core.agenda_complete import (
        event_id_from_text,
        looks_like_calendar_delete,
    )

    assert looks_like_calendar_delete("you created 3 events. delete two of them.")
    assert looks_like_calendar_delete(
        "Delete the Arelis operator e2e calendar event"
    )
    assert looks_like_calendar_delete("Delete the Arelis operator e2e event")
    assert not looks_like_calendar_delete("delete the task operator-smoke-task")
    quoted = (
        'they are all the same event. google:k398nrkdurm7hcrrvm3p6epqs4'
    )
    assert looks_like_calendar_delete(quoted)
    assert (
        event_id_from_text(quoted) == "google:k398nrkdurm7hcrrvm3p6epqs4"
    )


def test_calendar_read_does_not_need_google_id() -> None:
    from arelis.core.agenda_complete import (
        agenda_read_action,
        draft_agenda_delete_args,
        looks_like_calendar_read,
    )

    ask = "What's on my calendar tomorrow?"
    assert looks_like_calendar_read(ask)
    assert agenda_read_action(ask) == "tomorrow"
    assert agenda_read_action("what's on my calendar") == "list"
    assert not looks_like_calendar_read(
        "create a calendar event for tomorrow at 4pm"
    )
    inj = draft_agenda_delete_args(
        "you created 3 events. delete two of them.",
        receipts=[{"tool": "agenda", "action": "agenda.create", "summary": "Spill"}],
    )
    assert inj["action"] == "delete"
    assert inj.get("keep") == 1
    assert inj["summary"] == "Spill"
    assert "event_id" not in inj
    titled = draft_agenda_delete_args(
        "Delete the Arelis operator e2e calendar event"
    )
    assert titled["action"] == "delete"
    assert titled.get("keep") == 0
    assert titled["summary"] == "Arelis operator e2e"
    from arelis.core.agenda_complete import lock_agenda_delete_args

    locked = lock_agenda_delete_args(
        {"action": "delete", "keep": 1, "summary": "Arelis operator e2e"},
        "Delete the Arelis operator e2e calendar event",
    )
    assert locked.get("keep") == 0


def test_open_my_calendar_is_open_not_read_or_website() -> None:
    from arelis.core.agenda_complete import (
        looks_like_calendar_open,
        looks_like_calendar_read,
    )

    assert looks_like_calendar_open("open my calendar")
    assert looks_like_calendar_open("pull up my calendar")
    assert looks_like_calendar_open("show me my calendar")
    assert looks_like_calendar_open("bring up the calendar tile")
    assert not looks_like_calendar_read("open my calendar")
    assert not looks_like_calendar_read("show me my calendar")
    assert looks_like_calendar_read("What's on my calendar tomorrow?")
    assert looks_like_calendar_read("show me my calendar for today")
    assert not looks_like_calendar_open("What's on my calendar?")
    assert not looks_like_calendar_open("show me my calendar for today")
    assert not looks_like_calendar_open("open calendar.google.com")
    assert not looks_like_calendar_open("open my calendar in chrome")
    assert not looks_like_calendar_open("pull up YouTube")


def test_close_my_calendar_is_close_not_delete() -> None:
    from arelis.core.agenda_complete import (
        looks_like_calendar_close,
        looks_like_calendar_delete,
        looks_like_calendar_open,
        looks_like_calendar_read,
    )

    assert looks_like_calendar_close("close my calendar")
    assert looks_like_calendar_close("hide the calendar")
    assert looks_like_calendar_close("put away the calendar tile")
    assert not looks_like_calendar_open("close my calendar")
    assert not looks_like_calendar_read("close my calendar")
    assert not looks_like_calendar_delete("close my calendar")
    assert not looks_like_calendar_close("close the calendar event")
    assert not looks_like_calendar_close("open my calendar")
    assert looks_like_calendar_close(
        "Delight the calendar event for tomorrow and then close my calendar"
    )
    assert looks_like_calendar_delete(
        "Delight the calendar event for tomorrow and then close my calendar"
    )


def test_put_quoted_title_on_calendar_is_create_not_read() -> None:
    """10.2: 'Put TITLE on my calendar' must create once, not list tomorrow."""
    ask = "Put 'Arelis test event' on my calendar for tomorrow at 3pm."
    assert looks_like_calendar_create(ask)
    assert not looks_like_calendar_read(ask)
    draft = complete_agenda_draft(ask)
    assert draft is not None and draft.complete
    assert draft.summary == "Arelis test event"
    start = datetime.fromisoformat(draft.start)
    assert start.hour == 15
    delta = (start.date() - datetime.now().astimezone().date()).days
    assert delta == 1


def test_parse_two_weeks_from_today_at_3pm() -> None:
    now = datetime.now().astimezone()
    draft = parse_agenda_utterance(
        "Create a calendar event titled Arelis operator e2e. i want this "
        "event to be 2 weeks from today at 3pm and i want the event to "
        "last for 1 hour."
    )
    assert draft is not None and draft.complete
    assert draft.summary == "Arelis operator e2e"
    start = datetime.fromisoformat(draft.start)
    assert start.hour == 15
    delta = (start.date() - now.date()).days
    assert 13 <= delta <= 15
    assert draft.end
    end = datetime.fromisoformat(draft.end)
    assert (end - start).total_seconds() == 3600
