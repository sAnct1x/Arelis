"""Agenda create must accept the date phrases the model actually sends."""

from __future__ import annotations

from datetime import timedelta

from arelis.tools.agenda import _parse_dt


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
