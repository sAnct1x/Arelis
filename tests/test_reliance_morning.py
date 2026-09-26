"""Morning plate: time-bound first, then mail, then home weather."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from arelis.core.reliance.morning import (
    MorningPlate,
    PlateRow,
    compose_morning,
    render_plate,
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


def test_event_inside_horizon_is_included() -> None:
    plate = _plate(
        events=[
            {
                "summary": "Dentist",
                "starts_at": "2026-09-26T14:00:00",
                "ends_at": "2026-09-26T14:30:00",
                "location": "Clinic",
            }
        ]
    )
    assert plate.rows == (
        PlateRow(
            kind="event",
            title="Dentist",
            detail="14:00-14:30, Clinic",
        ),
    )
    assert plate.lead == "Dentist at 14:00."


def test_event_tomorrow_outside_18h_is_excluded() -> None:
    at_horizon = (NOW + timedelta(hours=18)).isoformat()
    plate = _plate(
        events=[
            {"summary": "Inside", "starts_at": "2026-09-26T20:00:00"},
            {"summary": "Tomorrow", "starts_at": "2026-09-27T15:00:00"},
            {"summary": "At horizon", "starts_at": at_horizon},
        ]
    )
    assert [row.title for row in plate.rows] == ["Inside"]


def test_events_are_chronological() -> None:
    plate = _plate(
        events=[
            {"summary": "Later", "starts_at": "2026-09-26T15:00:00"},
            {"summary": "Soon", "starts_at": "2026-09-26T09:00:00"},
        ]
    )
    assert [row.title for row in plate.rows] == ["Soon", "Later"]


def test_overdue_task_is_included() -> None:
    plate = _plate(
        tasks=[{"title": "Pay rent", "due": "2026-09-25", "priority": "normal"}]
    )
    assert plate.rows == (
        PlateRow(kind="task", title="Pay rent", detail="overdue, 2026-09-25"),
    )
    assert plate.lead == "Pay rent is overdue."


def test_future_task_next_week_is_excluded() -> None:
    plate = _plate(
        tasks=[
            {"title": "Later", "due": "2026-10-03", "priority": "high"},
            {"title": "Today", "due": "2026-09-26T18:00:00", "priority": "low"},
            {"title": "No date", "due": "", "priority": "high"},
        ]
    )
    assert [row.title for row in plate.rows] == ["Today"]
    assert plate.lead == "Today is due."


def test_high_priority_tasks_come_first_and_cap_at_five() -> None:
    tasks = [
        {"title": f"n{i}", "due": "2026-09-26", "priority": "normal"}
        for i in range(6)
    ]
    tasks.append({"title": "Hot", "due": "2026-09-20", "priority": "high"})
    plate = _plate(tasks=tasks)
    titles = [row.title for row in plate.rows]
    assert titles == ["Hot", "n0", "n1", "n2", "n3"]


def test_unread_caps_at_five_and_does_not_change_the_lead() -> None:
    unread = [
        {"from": f"p{i}@x", "subject": f"S{i}", "id": str(i)} for i in range(8)
    ]
    plate = _plate(unread=unread)
    assert plate.lead == "Nothing time-bound."
    assert plate.rows == tuple(
        PlateRow(kind="mail", title=f"S{i}", detail=f"p{i}@x") for i in range(5)
    )


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


def test_empty_plate() -> None:
    plate = _plate()
    assert plate == MorningPlate(lead="Nothing time-bound.", rows=())
    assert render_plate(plate) == "Nothing time-bound.\n"


def test_empty_plate_may_keep_home_weather() -> None:
    plate = _plate(weather_home="Foggy")
    assert plate.lead == "Nothing time-bound."
    assert plate.rows == (PlateRow(kind="weather", title="Home", detail="Foggy"),)


def test_location_weather_is_attached_case_insensitively() -> None:
    plate = _plate(
        events=[
            {
                "summary": "Site walk",
                "starts_at": "2026-09-26T11:00:00",
                "ends_at": "2026-09-26T12:00:00",
                "location": "Downtown",
            }
        ],
        weather_by_place={"downtown": "Light rain", "clinic": "Sunny"},
    )
    assert plate.rows[0].detail == "11:00-12:00, Downtown, Light rain"


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


def test_ended_event_is_skipped() -> None:
    plate = _plate(
        events=[
            {
                "summary": "Already done",
                "starts_at": "2026-09-26T08:00:00",
                "ends_at": "2026-09-26T07:30:00",
            },
            {
                "summary": "Still ahead",
                "starts_at": "2026-09-26T09:00:00",
                "ends_at": "2026-09-26T09:30:00",
            },
            {
                "summary": "Yesterday",
                "starts_at": "2026-09-25T09:00:00",
                "ends_at": "2026-09-25T10:00:00",
            },
        ]
    )
    assert [row.title for row in plate.rows] == ["Still ahead"]


def test_event_that_started_before_now_is_outside_the_window() -> None:
    plate = _plate(
        events=[
            {
                "summary": "Still going",
                "starts_at": "2026-09-26T07:00:00",
                "ends_at": "2026-09-26T10:00:00",
            }
        ]
    )
    assert plate.rows == ()
    assert plate.lead == "Nothing time-bound."


def test_aware_now_treats_naive_inputs_as_that_zone() -> None:
    zone = timezone(timedelta(hours=-4))
    now = datetime(2026, 9, 26, 8, 0, tzinfo=zone)
    plate = _plate(
        now=now,
        events=[{"summary": "Dentist", "starts_at": "2026-09-26T09:00:00"}],
        tasks=[{"title": "Rent", "due": "2026-09-25", "priority": "high"}],
    )
    assert [row.title for row in plate.rows] == ["Dentist", "Rent"]
    assert plate.lead == "Dentist at 09:00."


def test_naive_now_strips_aware_inputs() -> None:
    plate = _plate(
        events=[
            {
                "summary": "UTC morning",
                "starts_at": "2026-09-26T09:00:00+00:00",
            }
        ]
    )
    assert plate.rows[0].title == "UTC morning"
    assert plate.rows[0].detail == "09:00"


def test_render_plate_is_stable() -> None:
    plate = MorningPlate(
        lead="Leave by 8:40.",
        rows=(
            PlateRow(kind="leave", title="by 8:40", detail=""),
            PlateRow(kind="mail", title="Hi", detail="Ada"),
            PlateRow(kind="weather", title="Home", detail="Clear, 62"),
        ),
    )
    assert render_plate(plate) == (
        "Leave by 8:40.\n"
        "\n"
        "[leave] by 8:40\n"
        "\n"
        "[mail] Hi\n"
        "Ada\n"
        "\n"
        "[weather] Home\n"
        "Clear, 62\n"
    )
