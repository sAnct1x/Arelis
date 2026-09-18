"""Agenda create must accept the date phrases the model actually sends."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from arelis.tools.agenda import _parse_dt, _parse_duration_min, _parse_free_day, _parse_work_clock


def test_parse_dt_iso_stays_local() -> None:
    dt = _parse_dt("2026-09-06T15:00:00", field="start")
    assert dt.year == 2026
    assert dt.month == 9
    assert dt.day == 6
    assert dt.hour == 15
    assert dt.tzinfo is not None


def test_parse_dt_named_weekday_clock() -> None:
    dt = _parse_dt("Monday September 7, 2026 at 10:15 AM", field="start")
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2026, 9, 7, 10, 15)


def test_parse_dt_tomorrow_afternoon() -> None:
    dt = _parse_dt("tomorrow 3:00 PM", field="start")
    from arelis.tools.agenda import _local_now

    expect = _local_now().date() + timedelta(days=1)
    assert dt.date() == expect
    assert dt.hour == 15
    assert dt.minute == 0


def test_parse_free_day_weekday_iso_and_today() -> None:
    now = datetime(2026, 9, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    assert _parse_free_day("Thursday", now=now) == date(2026, 9, 24)
    assert _parse_free_day("today", now=now) == date(2026, 9, 18)
    assert _parse_free_day("tomorrow", now=now) == date(2026, 9, 19)
    assert _parse_free_day("2026-09-17", now=now) == date(2026, 9, 17)
    thursday = datetime(2026, 9, 17, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    assert _parse_free_day("Thursday", now=thursday) == date(2026, 9, 17)
    assert _parse_free_day("", now=thursday) == date(2026, 9, 17)


def test_parse_duration_and_work_clock() -> None:
    assert _parse_duration_min(None) == 30
    assert _parse_duration_min(120) == 120
    assert _parse_duration_min("2 hours") == 120
    assert _parse_work_clock("", default=(9, 0)) == (9, 0)
    assert _parse_work_clock("17:00", default=(9, 0)) == (17, 0)
    assert _parse_work_clock("9am", default=(9, 0)) == (9, 0)
    assert _parse_work_clock("5pm", default=(17, 0)) == (17, 0)
