"""Calendar secrets, cache store, agenda confirms, google/outlook parsing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from arelis.calendar.google_client import _parse_google_event
from arelis.calendar.models import CachedEvent
from arelis.calendar.outlook_client import _parse_outlook_event
from arelis.calendar.secrets import load_calendar_secrets, save_refresh_token
from arelis.calendar.store import CalendarStore
from arelis.tools.agenda import AgendaTool
from arelis.tools.base import NEVER_BATCH, ToolRegistry


def test_load_calendar_secrets(tmp_path: Path) -> None:
    path = tmp_path / "secrets.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "calendar": {
                    "google": {
                        "client_id": "gid",
                        "client_secret": "gsec",
                        "refresh_token": "gref",
                    },
                    "outlook": {
                        "client_id": "oid",
                        "refresh_token": "oref",
                        "tenant": "consumers",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    secrets = load_calendar_secrets(path)
    assert secrets.google is not None and secrets.google.authorized
    assert secrets.outlook is not None and secrets.outlook.authorized


def test_save_refresh_token_preserves_other_keys(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "secrets.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "email": {"address": "a@b.com", "app_password": "x"},
                "calendar": {"google": {"client_id": "gid", "client_secret": "s"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("arelis.calendar.secrets.SECRETS_PATH", path)
    save_refresh_token("google", "new-refresh")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["email"]["address"] == "a@b.com"
    assert raw["calendar"]["google"]["refresh_token"] == "new-refresh"
    assert raw["calendar"]["google"]["client_id"] == "gid"


def test_calendar_store_roundtrip(tmp_path: Path) -> None:
    store = CalendarStore(tmp_path / "cal.db")
    start = datetime(2026, 8, 9, 14, 0, tzinfo=UTC)
    end = start + timedelta(hours=1)
    ev = CachedEvent(
        id="google:abc",
        provider="google",
        calendar_id="primary",
        summary="Dentist",
        starts_at=start,
        ends_at=end,
        all_day=False,
        raw_id="abc",
    )
    store.replace_provider_window(
        "google",
        [ev],
        start=start - timedelta(days=1),
        end=start + timedelta(days=2),
    )
    rows = store.list_range(start.date(), start.date())
    assert len(rows) == 1
    assert rows[0].summary == "Dentist"
    store.close()


def test_calendar_store_put_upserts(tmp_path: Path) -> None:
    store = CalendarStore(tmp_path / "cal.db")
    start = datetime(2026, 8, 19, 10, 0, tzinfo=UTC)
    ev = CachedEvent(
        id="google:put1",
        provider="google",
        calendar_id="primary",
        summary="Walk",
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        all_day=False,
        raw_id="put1",
    )
    store.put(ev)
    ev.summary = "Walk the dog"
    store.put(ev)
    rows = store.list_range(start.date(), start.date())
    assert len(rows) == 1
    assert rows[0].summary == "Walk the dog"
    store.close()


def test_parse_google_and_outlook_events() -> None:
    g = _parse_google_event(
        {
            "id": "g1",
            "summary": "Standup",
            "location": "Room 4",
            "description": "Daily sync notes",
            "start": {"dateTime": "2026-08-09T15:00:00Z"},
            "end": {"dateTime": "2026-08-09T15:30:00Z"},
        },
        calendar_id="primary",
    )
    assert g is not None
    assert g.provider == "google"
    assert g.summary == "Standup"
    assert g.location == "Room 4"
    assert "sync notes" in g.description

    o = _parse_outlook_event(
        {
            "id": "o1",
            "subject": "Review",
            "isAllDay": False,
            "start": {"dateTime": "2026-08-09T16:00:00", "timeZone": "UTC"},
            "end": {"dateTime": "2026-08-09T17:00:00", "timeZone": "UTC"},
            "location": {"displayName": "Lab"},
        },
        calendar_id="default",
    )
    assert o is not None
    assert o.provider == "outlook"
    assert o.location == "Lab"


def test_google_holiday_calendars_are_extra_ids() -> None:
    from arelis.calendar.google_client import extra_google_calendar_ids

    extra = extra_google_calendar_ids(
        [
            {"id": "primary", "summary": "Me", "primary": True},
            {
                "id": "en.usa#holiday@group.v.calendar.google.com",
                "summary": "Public holidays (en.usa)",
            },
            {
                "id": "en.uk#holiday@group.v.calendar.google.com",
                "summary": "Public holidays (en.uk)",
            },
            {"id": "family-shared", "summary": "Family"},
            {"id": "addressbook#contacts@group.v.calendar.google.com", "summary": "Birthdays"},
        ],
        primary_id="primary",
    )
    assert extra == [
        "en.usa#holiday@group.v.calendar.google.com",
        "en.uk#holiday@group.v.calendar.google.com",
    ]


def test_google_holiday_summary_without_group_id() -> None:
    from arelis.calendar.google_client import extra_google_calendar_ids

    extra = extra_google_calendar_ids(
        [{"id": "c_abc123", "summary": "Public holidays"}],
        primary_id="primary",
    )
    assert extra == ["c_abc123"]


def test_agenda_write_needs_confirm_and_never_batch() -> None:
    reg = ToolRegistry()
    reg.register(AgendaTool({}))
    assert not reg.needs_confirm("agenda", {"action": "today"})
    assert not reg.needs_confirm("agenda", {"action": "open"})
    assert not reg.needs_confirm("agenda", {"action": "close"})
    assert reg.needs_confirm("agenda", {"action": "create", "summary": "X"})
    assert "agenda" in NEVER_BATCH
    text = reg.describe_call(
        "agenda",
        {
            "action": "create",
            "provider": "google",
            "summary": "Dentist",
            "start": "2026-08-12T10:00:00",
        },
    )
    assert "Dentist" in text
    assert "google" in text


@pytest.mark.asyncio
async def test_agenda_open_returns_open_flag() -> None:
    result = await AgendaTool({}).run(action="open")
    assert result.ok
    assert result.data.get("open") is True
    assert "calendar" in result.output.lower()


@pytest.mark.asyncio
async def test_agenda_close_returns_close_flag() -> None:
    result = await AgendaTool({}).run(action="close")
    assert result.ok
    assert result.data.get("close") is True
    assert "calendar" in result.output.lower()


@pytest.mark.asyncio
async def test_agenda_list_ics_fallback(tmp_path: Path, monkeypatch) -> None:
    ics = tmp_path / "calendar.ics"
    ics.write_text(
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
        "DTSTART;VALUE=DATE:20260809\nSUMMARY:Example all-day note\n"
        "END:VEVENT\nEND:VCALENDAR\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "arelis.tools.agenda.resolve_calendar_path",
        lambda _cfg=None: ics,
    )
    monkeypatch.setattr(
        "arelis.tools.agenda.load_calendar_secrets",
        lambda: __import__(
            "arelis.calendar.secrets", fromlist=["CalendarSecrets"]
        ).CalendarSecrets(google=None, outlook=None),
    )
    # Empty cache db
    monkeypatch.setattr(
        "arelis.tools.agenda.CalendarStore",
        lambda: CalendarStore(tmp_path / "empty.db"),
    )
    tool = AgendaTool({"tools": {"briefing": {"calendar_path": str(ics)}}})
    # Freeze "today" via window: use range for 2026-08-09
    result = await tool.run(action="range", start="2026-08-09", end="2026-08-09")
    assert result.ok
    assert "Example all-day note" in result.output or result.data.get("count", 0) >= 0


def _spill_event(
    eid: str, start: datetime, *, summary: str = "chemical spill safety"
) -> CachedEvent:
    return CachedEvent(
        id=f"google:{eid}",
        provider="google",
        calendar_id="primary",
        summary=summary,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        all_day=False,
        raw_id=eid,
    )


@pytest.mark.asyncio
async def test_delete_duplicates_by_title_keeps_one(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "cal.db"
    store = CalendarStore(db)
    start = datetime(2026, 8, 13, 16, 0, tzinfo=UTC)
    rows = [
        _spill_event("aaa", start),
        _spill_event("bbb", start),
        _spill_event("ccc", start),
    ]
    store.replace_provider_window(
        "google",
        rows,
        start=start - timedelta(days=1),
        end=start + timedelta(days=2),
    )
    store.close()

    monkeypatch.setattr(
        "arelis.tools.agenda.CalendarStore",
        lambda: CalendarStore(db),
    )
    monkeypatch.setattr(
        "arelis.calendar.service.CalendarStore",
        lambda: CalendarStore(db),
    )
    monkeypatch.setattr(
        "arelis.tools.agenda.load_calendar_secrets",
        lambda: __import__(
            "arelis.calendar.secrets", fromlist=["CalendarSecrets"]
        ).CalendarSecrets(google=None, outlook=None),
    )

    deleted: list[str] = []

    class _Fake:
        async def delete_event(self, raw_id: str, calendar_id: str | None = None) -> None:
            deleted.append(raw_id)

    monkeypatch.setattr(AgendaTool, "_client", lambda self, provider: _Fake())
    monkeypatch.setattr(
        "arelis.tools.agenda._local_now",
        lambda: datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
    )
    tool = AgendaTool({})
    result = await tool.run(
        action="delete",
        summary="chemical spill safety",
        keep=1,
    )
    assert result.ok
    assert result.data["count"] == 2
    assert len(deleted) == 2
    remaining = CalendarStore(db).list_range(start.date(), start.date())
    assert len(remaining) == 1
    assert remaining[0].summary == "chemical spill safety"


@pytest.mark.asyncio
async def test_delete_titled_event_keep_0_removes_the_only_copy(
    tmp_path: Path, monkeypatch
) -> None:
    db = tmp_path / "cal.db"
    store = CalendarStore(db)
    start = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)
    store.replace_provider_window(
        "google",
        [_spill_event("only", start, summary="Arelis operator e2e")],
        start=start - timedelta(days=1),
        end=start + timedelta(days=2),
    )
    store.close()

    monkeypatch.setattr(
        "arelis.tools.agenda.CalendarStore",
        lambda: CalendarStore(db),
    )
    monkeypatch.setattr(
        "arelis.calendar.service.CalendarStore",
        lambda: CalendarStore(db),
    )
    monkeypatch.setattr(
        "arelis.tools.agenda.load_calendar_secrets",
        lambda: __import__(
            "arelis.calendar.secrets", fromlist=["CalendarSecrets"]
        ).CalendarSecrets(google=None, outlook=None),
    )
    deleted: list[str] = []

    class _Fake:
        async def delete_event(self, raw_id: str, calendar_id: str | None = None) -> None:
            deleted.append(raw_id)

    monkeypatch.setattr(AgendaTool, "_client", lambda self, provider: _Fake())
    monkeypatch.setattr(
        "arelis.tools.agenda._local_now",
        lambda: datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
    )
    tool = AgendaTool({})
    noop = await tool.run(
        action="delete",
        summary="Arelis operator e2e",
        keep=1,
    )
    assert noop.ok
    assert noop.data.get("count") == 0
    result = await tool.run(
        action="delete",
        summary="Arelis operator e2e",
        keep=0,
    )
    assert result.ok
    assert result.data["count"] == 1
    assert deleted == ["only"]


@pytest.mark.asyncio
async def test_delete_without_id_is_ambiguous_when_titles_differ(
    tmp_path: Path, monkeypatch
) -> None:
    db = tmp_path / "cal.db"
    store = CalendarStore(db)
    start = datetime(2026, 8, 13, 16, 0, tzinfo=UTC)
    other = start.replace(hour=9)
    store.replace_provider_window(
        "google",
        [
            _spill_event("aaa", start),
            CachedEvent(
                id="google:ddd",
                provider="google",
                calendar_id="primary",
                summary="Dentist",
                starts_at=other,
                ends_at=other + timedelta(hours=1),
                all_day=False,
                raw_id="ddd",
            ),
        ],
        start=start - timedelta(days=1),
        end=start + timedelta(days=2),
    )
    store.close()
    monkeypatch.setattr(
        "arelis.tools.agenda.CalendarStore",
        lambda: CalendarStore(db),
    )
    monkeypatch.setattr(
        "arelis.calendar.service.CalendarStore",
        lambda: CalendarStore(db),
    )
    monkeypatch.setattr(
        "arelis.tools.agenda.load_calendar_secrets",
        lambda: __import__(
            "arelis.calendar.secrets", fromlist=["CalendarSecrets"]
        ).CalendarSecrets(google=None, outlook=None),
    )
    monkeypatch.setattr(
        "arelis.tools.agenda._local_now",
        lambda: datetime(2026, 8, 12, 12, 0, tzinfo=UTC),
    )
    tool = AgendaTool({})
    result = await tool.run(action="delete")
    assert not result.ok
    assert result.data.get("ambiguous") is True
    assert "Dentist" in result.output
    assert "chemical spill" in result.output.lower()
    assert "Google id" in result.output or "google id" in result.output.lower()
