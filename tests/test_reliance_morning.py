"""Morning plate: time-bound first, then mail, then home weather."""

from __future__ import annotations

from datetime import datetime

from arelis.core.reliance.morning import (
    PlateRow,
    compose_morning,
)

NOW = datetime(2026, 9, 26, 8, 0)


def _plate(**overrides: object):
    args = {
        "now": NOW,
        "events": [],
        "unread": [],
        "tasks": [],
    }
    args.update(overrides)
    return compose_morning(**args)


def test_leave_is_first_and_the_lead_mentions_it() -> None:
    plate = _plate(
        leave="by 8:40",
        events=[{"summary": "Standup", "starts_at": "2026-09-26T09:00:00"}],
    )
    assert plate.rows[0] == PlateRow(kind="leave", title="by 8:40", detail="")
    assert plate.lead == "Leave by 8:40."
    assert plate.rows[1].kind == "event"
    assert plate.rows[1].title == "Standup"


def test_weather_is_last() -> None:
    plate = _plate(
        leave="by 8:20",
        events=[{"summary": "Standup", "starts_at": "2026-09-26T09:00:00"}],
        tasks=[{"title": "Invoice", "due": "2026-09-26", "priority": "normal"}],
        unread=[{"from": "Ada", "subject": "Hi", "id": "1"}],
        weather_home="Clear, 62",
    )
    assert [row.kind for row in plate.rows] == [
        "leave",
        "event",
        "task",
        "mail",
        "weather",
    ]
    assert plate.rows[-1] == PlateRow(
        kind="weather", title="Home", detail="Clear, 62"
    )
    assert plate.lead == "Leave by 8:20."


def test_missing_place_weather_is_not_invented() -> None:
    plate = _plate(
        events=[
            {
                "summary": "Site walk",
                "starts_at": "2026-09-26T11:00:00",
                "location": "Uptown",
            }
        ],
        weather_by_place={"downtown": "Light rain"},
        weather_home="Sunny at home",
    )
    event = plate.rows[0]
    assert event.detail == "11:00, Uptown"
    assert "Light rain" not in event.detail
    assert "Sunny" not in event.detail
    assert plate.rows[-1].kind == "weather"


