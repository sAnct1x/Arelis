"""Agenda find-time — free/busy on one local day, cited from the cache."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from arelis.calendar.models import CachedEvent
from arelis.calendar.secrets import CalendarSecrets
from arelis.calendar.store import CalendarStore
from arelis.tools.agenda import AGENDA_WRITE_ACTIONS, AgendaTool
from arelis.tools.policy import AGENDA_WRITE_ACTIONS as POLICY_WRITES

THURSDAY = date(2026, 9, 17)
TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 17, 8, 0, tzinfo=TZ)


def _covers(start_iso: str, end_iso: str, when: datetime) -> bool:
    return datetime.fromisoformat(start_iso) <= when < datetime.fromisoformat(end_iso)


def _event(
    summary: str,
    *,
    hour: int = 10,
    end_hour: int | None = None,
    all_day: bool = False,
    day: date = THURSDAY,
    start_day: date | None = None,
    end_day: date | None = None,
) -> CachedEvent:
    start_on = start_day or day
    start = datetime(start_on.year, start_on.month, start_on.day, hour, 0, tzinfo=TZ)
    if all_day:
        end = start + timedelta(days=1)
    else:
        finish_on = end_day or day
        finish_hour = end_hour if end_hour is not None else hour + 1
        end = datetime(finish_on.year, finish_on.month, finish_on.day, finish_hour, 0, tzinfo=TZ)
    return CachedEvent(
        id=f"local:{summary}",
        provider="local",
        calendar_id="local",
        summary=summary,
        starts_at=start,
        ends_at=end,
        all_day=all_day,
        raw_id=summary,
    )


def _wire_store(tmp_path, monkeypatch, events: list[CachedEvent]) -> None:
    monkeypatch.setattr("arelis.tools.agenda._local_now", lambda: NOW)
    monkeypatch.setattr(
        "arelis.tools.agenda.load_calendar_secrets",
        lambda: CalendarSecrets(google=None, outlook=None),
    )
    db = tmp_path / "cal.db"
    store = CalendarStore(db)
    for ev in events:
        store.put(ev)
    store.close()
    monkeypatch.setattr(
        "arelis.tools.agenda.CalendarStore",
        lambda: CalendarStore(db),
    )


def _tool(tmp_path) -> AgendaTool:
    return AgendaTool({"tools": {"briefing": {"calendar_path": str(tmp_path / "absent.ics")}}})


def test_free_is_read_not_write() -> None:
    enum = AgendaTool.parameters_schema["properties"]["action"]["enum"]
    assert "free" in enum
    assert "busy" in enum
    assert "duration_min" in AgendaTool.parameters_schema["properties"]
    assert "free" not in AGENDA_WRITE_ACTIONS
    assert "busy" not in AGENDA_WRITE_ACTIONS
    assert "free" not in POLICY_WRITES
    assert "busy" not in POLICY_WRITES


@pytest.mark.asyncio
async def test_meeting_1011_is_not_a_free_1030_slot(tmp_path, monkeypatch) -> None:
    _wire_store(tmp_path, monkeypatch, [_event("Standup", hour=10, end_hour=11)])
    result = await _tool(tmp_path).run(action="free", date="Thursday")
    assert result.ok
    ten_thirty = datetime(2026, 9, 17, 10, 30, tzinfo=TZ)
    assert any(_covers(b["start"], b["end"], ten_thirty) for b in result.data["busy"])
    assert not any(_covers(s["start"], s["end"], ten_thirty) for s in result.data["free"])
    assert not any("10:30" in s["start"] for s in result.data["free"])
    starts = [s["start"] for s in result.data["free"]]
    assert any(s.startswith("2026-09-17T09:00") for s in starts)
    assert any(s.startswith("2026-09-17T11:00") for s in starts)
    assert "Standup" in result.output


@pytest.mark.asyncio
async def test_all_day_blocks_the_work_window(tmp_path, monkeypatch) -> None:
    _wire_store(
        tmp_path,
        monkeypatch,
        [_event("Company holiday", hour=0, all_day=True)],
    )
    result = await _tool(tmp_path).run(action="free", day="2026-09-17")
    assert result.ok
    assert result.data["free"] == []
    assert any(b["all_day"] for b in result.data["busy"])
    assert "Company holiday" in result.output
    assert "no open slot of 30 min on Thursday 2026-09-17" in result.output


@pytest.mark.asyncio
async def test_no_events_is_one_full_work_window(tmp_path, monkeypatch) -> None:
    _wire_store(tmp_path, monkeypatch, [])
    result = await _tool(tmp_path).run(action="free", date="2026-09-17")
    assert result.ok
    assert len(result.data["free"]) == 1
    assert result.data["free"][0]["start"].startswith("2026-09-17T09:00")
    assert result.data["free"][0]["end"].startswith("2026-09-17T17:00")
    assert result.data["busy"] == []


@pytest.mark.asyncio
async def test_duration_120_with_60_min_gaps_is_an_honest_miss(tmp_path, monkeypatch) -> None:
    _wire_store(tmp_path, monkeypatch, [_event("Standup", hour=10, end_hour=11)])
    result = await _tool(tmp_path).run(
        action="free",
        date="2026-09-17",
        duration_min=120,
        work_start="09:00",
        work_end="12:00",
    )
    assert result.ok
    assert result.data["free"] == []
    assert "no open slot of 120 min on Thursday 2026-09-17" in result.output
    assert "09:00 AM–10:00 AM" not in result.output.split("Free slots")[-1]


@pytest.mark.asyncio
async def test_overnight_counts_as_busy_on_the_landing_day(tmp_path, monkeypatch) -> None:
    _wire_store(
        tmp_path,
        monkeypatch,
        [
            _event(
                "Red-eye",
                hour=22,
                end_hour=10,
                start_day=date(2026, 9, 16),
                end_day=THURSDAY,
            )
        ],
    )
    result = await _tool(tmp_path).run(action="free", date="2026-09-17")
    assert result.ok
    nine_thirty = datetime(2026, 9, 17, 9, 30, tzinfo=TZ)
    assert any(_covers(b["start"], b["end"], nine_thirty) for b in result.data["busy"])
    assert result.data["free"][0]["start"].startswith("2026-09-17T10:00")
    assert "Red-eye" in result.output


@pytest.mark.asyncio
async def test_busy_lists_blocks_and_stays_on_one_day(tmp_path, monkeypatch) -> None:
    _wire_store(
        tmp_path,
        monkeypatch,
        [
            _event("Standup", hour=10, end_hour=11),
            _event("Friday only", hour=9, day=date(2026, 9, 18)),
        ],
    )
    result = await _tool(tmp_path).run(
        action="busy",
        date="2026-09-17",
        start="2026-09-17",
        end="2026-09-24",
    )
    assert result.ok
    assert result.data["date"] == "2026-09-17"
    assert result.data["free"] == []
    titles = {b["summary"] for b in result.data["busy"]}
    assert titles == {"Standup"}
    assert "Friday only" not in result.output
    assert "Free slots" not in result.output
