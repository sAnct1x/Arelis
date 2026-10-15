"""Local ICS agenda for briefings and the agenda tool."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from arelis.briefing.calendar import (
    format_agenda_section,
    parse_ics_events,
)
from arelis.calendar.store import CalendarStore
from arelis.tools import build_tool_registry
from arelis.tools.agenda import AgendaTool
from arelis.workspace import WorkspaceRoots

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20260808T090000
SUMMARY:Morning standup
LOCATION:Lab
DESCRIPTION:Standup notes for the week
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260809
SUMMARY:All-day errand
END:VEVENT
BEGIN:VEVENT
DTSTART:20260810T120000
SUMMARY:Too far out
END:VEVENT
END:VCALENDAR
"""


def test_parse_ics_events_reads_timed_and_all_day() -> None:
    tz = ZoneInfo("America/New_York")
    events = parse_ics_events(ICS, default_tz=tz)
    assert len(events) == 3
    assert events[0].summary == "Morning standup"
    assert not events[0].all_day
    assert events[0].starts_at.hour == 9
    assert events[0].location == "Lab"
    assert "Standup notes" in events[0].description
    assert events[1].all_day
    assert events[1].summary == "All-day errand"


def test_format_agenda_section_labels_today_tomorrow() -> None:
    tz = ZoneInfo("America/New_York")
    now = datetime(2026, 8, 8, 8, 0, tzinfo=tz)
    events = parse_ics_events(ICS, default_tz=tz)
    kept = [e for e in events if e.summary != "Too far out"]
    text = format_agenda_section(kept, now=now)
    assert "**Today**" in text
    assert "Morning standup" in text
    assert "Lab" in text
    assert "Standup notes" in text
    assert "**Tomorrow**" in text
    assert "all day, All-day errand" in text


@pytest.mark.asyncio
async def test_agenda_tool_range_includes_source(tmp_path) -> None:
    path = tmp_path / "calendar.ics"
    path.write_text(ICS, encoding="utf-8")
    tool = AgendaTool(
        {"tools": {"briefing": {"calendar_path": str(path)}}}
    )
    result = await tool.run(action="range", start="2026-08-08", end="2026-08-09")
    assert result.ok
    assert "Morning standup" in result.output
    assert "All-day errand" in result.output
    assert str(path) in result.output
    assert result.data["count"] == 2
    assert result.data["source"] == str(path)


@pytest.mark.asyncio
async def test_agenda_list_default_covers_next_week(tmp_path, monkeypatch) -> None:
    path = tmp_path / "calendar.ics"
    path.write_text(ICS, encoding="utf-8")
    tool = AgendaTool(
        {"tools": {"briefing": {"calendar_path": str(path)}}}
    )
    fixed = datetime(2026, 8, 8, 8, 0, tzinfo=ZoneInfo("America/New_York"))
    monkeypatch.setattr("arelis.tools.agenda._local_now", lambda: fixed)
    monkeypatch.setattr(
        "arelis.tools.agenda.load_calendar_secrets",
        lambda: __import__(
            "arelis.calendar.secrets", fromlist=["CalendarSecrets"]
        ).CalendarSecrets(google=None, outlook=None),
    )
    monkeypatch.setattr(
        "arelis.tools.agenda.CalendarStore",
        lambda: CalendarStore(tmp_path / "empty.db"),
    )
    listed = await tool.run(action="list")
    assert listed.ok
    assert "Morning standup" in listed.output
    assert "All-day errand" in listed.output
    assert "Too far out" in listed.output
    assert "google:" not in listed.output


@pytest.mark.asyncio
async def test_ics_sync_missing_secret_is_clear(tmp_path, monkeypatch) -> None:
    from arelis.briefing.ics_sync import sync_ics_from_url

    dest = tmp_path / "calendar.ics"
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("calendar:\n  google:\n    client_id: x\n", encoding="utf-8")
    summary = await sync_ics_from_url(
        {"tools": {"briefing": {"calendar_path": str(dest)}}},
        secrets_path=secrets,
    )
    assert summary.get("missing_secret") is True
    assert not dest.exists()

    monkeypatch.setattr("arelis.briefing.ics_sync.load_ics_url", lambda path=None: "")
    tool = AgendaTool({"tools": {"briefing": {"calendar_path": str(dest)}}})
    result = await tool.run(action="sync", provider="ics")
    assert result.ok
    assert "ics_url" in result.output.lower() or "not configured" in result.output.lower()
    assert result.data.get("missing_secret") is True


@pytest.mark.asyncio
async def test_agenda_ics_sync_uses_allow_gate(tmp_path, monkeypatch) -> None:
    workspace = WorkspaceRoots.from_config(
        {"workspace": {"roots": [{"name": "t", "path": str(tmp_path)}]}}
    )
    registry = build_tool_registry(
        {"tools": {"briefing": {"enabled": True}}, "agent": {}},
        workspace,
        allow_send=True,
        memory_store=None,
    )
    assert not registry.needs_confirm(
        "agenda", {"action": "sync", "provider": "all"}, confirm_writes=True
    )
    assert registry.needs_confirm(
        "agenda", {"action": "sync", "provider": "ics"}, confirm_writes=True
    )
    assert not registry.needs_confirm(
        "agenda", {"action": "sync", "provider": "ics"}, confirm_writes=False
    )
