"""One sentence in, one destination out. Recurrence is not a fired reminder."""

from __future__ import annotations

from datetime import datetime

from arelis.core.reliance.capture import Capture, classify_capture

NOW = datetime(2026, 9, 26, 12, 0)


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


