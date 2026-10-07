"""The line is whether to leave. A forecast with nowhere to be stays quiet."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arelis.core.reliance.leave_now import leave_line

_NOW = datetime(2026, 9, 26, 9, 0)


def test_no_event_returns_none() -> None:
    assert leave_line(now=_NOW, event_start=None) is None


def test_event_in_four_hours_returns_none() -> None:
    assert leave_line(now=_NOW, event_start=_NOW + timedelta(hours=4)) is None


def test_event_in_forty_minutes_names_place_and_rain() -> None:
    line = leave_line(
        now=_NOW,
        event_start=_NOW + timedelta(minutes=40),
        place="Midtown",
        conditions="Rain",
    )
    assert line == "In 40 minutes at Midtown. Rain."


def test_travel_longer_than_the_gap_says_leave_now() -> None:
    line = leave_line(
        now=_NOW,
        event_start=_NOW + timedelta(minutes=40),
        place="Midtown",
        conditions="Rain",
        travel_minutes=55,
    )
    assert line == "In 40 minutes at Midtown. Rain. Leave now."


def test_travel_with_slack_says_when_to_leave() -> None:
    line = leave_line(
        now=_NOW,
        event_start=_NOW + timedelta(minutes=40),
        place="Midtown",
        conditions="Rain",
        travel_minutes=15,
    )
    assert line == "In 40 minutes at Midtown. Rain. Leave in 25 minutes."


def test_already_started_returns_none() -> None:
    assert leave_line(now=_NOW, event_start=_NOW) is None
    assert (
        leave_line(now=_NOW, event_start=_NOW - timedelta(minutes=5)) is None
    )


def test_empty_conditions_omit_weather_words() -> None:
    line = leave_line(
        now=_NOW,
        event_start=_NOW + timedelta(minutes=40),
        place="Midtown",
        conditions="",
        travel_minutes=15,
    )
    assert line == "In 40 minutes at Midtown. Leave in 25 minutes."
    lowered = line.lower()
    for word in ("rain", "snow", "sunny", "cloud", "weather", "forecast"):
        assert word not in lowered


def test_negative_travel_counts_as_no_trip() -> None:
    line = leave_line(
        now=_NOW,
        event_start=_NOW + timedelta(minutes=40),
        place="Midtown",
        travel_minutes=-12,
    )
    assert line == "In 40 minutes at Midtown."


def test_naive_and_aware_share_the_aware_zone() -> None:
    zone = timezone(timedelta(hours=-4))
    aware_now = datetime(2026, 9, 26, 9, 0, tzinfo=zone)
    naive_start = datetime(2026, 9, 26, 9, 40)
    line = leave_line(now=aware_now, event_start=naive_start, place="Midtown")
    assert line == "In 40 minutes at Midtown."

    naive_now = datetime(2026, 9, 26, 9, 0)
    aware_start = datetime(2026, 9, 26, 9, 40, tzinfo=zone)
    line = leave_line(now=naive_now, event_start=aware_start, place="Midtown")
    assert line == "In 40 minutes at Midtown."
