"""One sentence in, one destination out. Recurrence is not a fired reminder."""

from __future__ import annotations

from datetime import datetime

import pytest

from arelis.core.reliance.capture import Capture, classify_capture

NOW = datetime(2026, 9, 26, 12, 0)


def test_in_20_minutes_is_remind() -> None:
    got = classify_capture("stretch in 20 minutes", now=NOW)
    assert got == Capture(
        dest="remind",
        title="stretch",
        when_text="in 20 minutes",
        minutes=20,
    )


def test_in_an_hour_is_60_minutes() -> None:
    got = classify_capture("in an hour", now=NOW)
    assert got.dest == "remind"
    assert got.minutes == 60
    assert got.when_text == "in an hour"
    assert got.title == ""


def test_in_2_hours_and_90_seconds() -> None:
    hours = classify_capture("leave in 2 hours", now=NOW)
    assert hours.dest == "remind"
    assert hours.minutes == 120
    assert hours.title == "leave"
    assert hours.when_text == "in 2 hours"

    seconds = classify_capture("in 90 seconds", now=NOW)
    assert seconds.dest == "remind"
    assert seconds.minutes == 2
    assert seconds.when_text == "in 90 seconds"

    under_a_minute = classify_capture("in 30 seconds", now=NOW)
    assert under_a_minute.minutes == 1


def test_remind_me_to_buy_milk_is_a_task() -> None:
    got = classify_capture("remind me to buy milk", now=NOW)
    assert got == Capture(dest="task", title="buy milk", when_text=None, minutes=None)


def test_buy_milk_is_a_task() -> None:
    got = classify_capture("buy milk", now=NOW)
    assert got == Capture(dest="task", title="buy milk", when_text=None, minutes=None)


def test_at_3pm_call_sam_is_remind() -> None:
    got = classify_capture("at 3pm call Sam", now=NOW)
    assert got == Capture(
        dest="remind",
        title="call Sam",
        when_text="at 3pm",
        minutes=None,
    )


def test_clock_phrases_are_reminders_without_minutes() -> None:
    cases = {
        "at 3 call Sam": ("call Sam", "at 3"),
        "stand up at 15:00": ("stand up", "at 15:00"),
        "tomorrow at 8 wake up": ("wake up", "tomorrow at 8"),
        "tonight take out the trash": ("take out the trash", "tonight"),
        "tomorrow morning check mail": ("check mail", "tomorrow morning"),
    }
    for text, (title, when_text) in cases.items():
        got = classify_capture(text, now=NOW)
        assert got.dest == "remind", text
        assert got.minutes is None, text
        assert got.title == title, text
        assert got.when_text == when_text, text


def test_every_morning_check_mail_is_task_with_when_text() -> None:
    got = classify_capture("every morning check mail", now=NOW)
    assert got.dest == "task"
    assert got.title == "check mail"
    assert got.when_text == "every morning"
    assert got.minutes is None

    daily = classify_capture("check mail daily", now=NOW)
    assert daily.dest == "task"
    assert daily.title == "check mail"
    assert daily.when_text == "daily"

    weekdays = classify_capture("weekdays stand up", now=NOW)
    assert weekdays.dest == "task"
    assert weekdays.when_text == "weekdays"
    assert weekdays.title == "stand up"


def test_empty_raises() -> None:
    with pytest.raises(ValueError):
        classify_capture("", now=NOW)
    with pytest.raises(ValueError):
        classify_capture("   ", now=NOW)


def test_title_does_not_keep_the_time_phrase() -> None:
    got = classify_capture("call Sam at 3pm", now=NOW)
    assert got.dest == "remind"
    assert got.title == "call Sam"
    assert "at 3pm" not in got.title
    assert "3" not in got.title

    delayed = classify_capture("remind me in 20 minutes to buy milk", now=NOW)
    assert delayed == Capture(
        dest="remind",
        title="buy milk",
        when_text="in 20 minutes",
        minutes=20,
    )
    assert "minute" not in delayed.title
    assert "remind" not in delayed.title


def test_recurrence_is_not_a_fired_reminder() -> None:
    got = classify_capture("every day at 8 take meds", now=NOW)
    assert got.dest == "task"
    assert got.minutes is None
    assert got.when_text == "every day at 8"
    assert got.title == "take meds"

