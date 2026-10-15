"""The line is whether to leave. A forecast with nowhere to be stays quiet."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arelis.core.reliance.leave_now import leave_line

_NOW = datetime(2026, 9, 26, 9, 0)


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
