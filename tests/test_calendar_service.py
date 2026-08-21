"""Shared calendar service: cache writes and CALENDAR_CHANGED."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from arelis.calendar.models import CachedEvent
from arelis.calendar.service import CalendarService
from arelis.calendar.store import CalendarStore
from arelis.core.bus import EventBus, bind_app_bus, emit_nowait
from arelis.core.events import Event, EventType


def _event(eid: str = "abc", *, summary: str = "Standup") -> CachedEvent:
    start = datetime(2026, 8, 19, 15, 0, tzinfo=UTC)
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


class _FakeClient:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []
        self.deleted: list[str] = []

    async def create_event(self, **kwargs):
        self.created.append(kwargs)
        return _event("new", summary=str(kwargs.get("summary") or "New"))

    async def update_event(self, event_id: str, **kwargs):
        self.updated.append((event_id, kwargs))
        return _event(event_id, summary=str(kwargs.get("summary") or "Updated"))

    async def delete_event(self, event_id: str, calendar_id: str | None = None) -> None:
        self.deleted.append(event_id)


@pytest.mark.asyncio
async def test_create_puts_cache_and_emits(tmp_path: Path) -> None:
    store = CalendarStore(tmp_path / "cal.db")
    fake = _FakeClient()
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(EventType.CALENDAR_CHANGED, seen.append)
    bind_app_bus(bus)
    task = __import__("asyncio").create_task(bus.run())
    await __import__("asyncio").sleep(0)
    try:
        svc = CalendarService({}, store=store, client_factory=lambda _p: fake)
        ev = await svc.create(
            summary="Lab",
            starts_at=datetime(2026, 8, 19, 9, 0, tzinfo=UTC),
            provider="google",
        )
        await bus.drain()
        assert ev.summary == "Lab"
        assert fake.created
        cached = store.get(ev.id)
        assert cached is not None
        assert cached.summary == "Lab"
        assert seen
        assert seen[-1].payload.get("action") == "create"
    finally:
        bind_app_bus(None)
        bus.stop()
        task.cancel()
        store.close()


@pytest.mark.asyncio
async def test_update_and_delete(tmp_path: Path) -> None:
    store = CalendarStore(tmp_path / "cal.db")
    fake = _FakeClient()
    svc = CalendarService({}, store=store, client_factory=lambda _p: fake)
    updated = await svc.update("google:abc", summary="Renamed", provider="google")
    assert updated.summary == "Renamed"
    assert fake.updated[0][0] == "abc"
    await svc.delete("google:abc", provider="google")
    assert fake.deleted == ["abc"]
    assert store.get("google:abc") is None
    store.close()


def test_emit_nowait_is_silent_without_a_bus() -> None:
    bind_app_bus(None)
    emit_nowait(Event(EventType.CALENDAR_CHANGED, {"action": "noop"}))


@pytest.mark.asyncio
async def test_sync_timeout_returns_failed(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    from arelis.calendar import service as cal_service

    async def hung(*_args, **_kwargs):
        await asyncio.sleep(30)
        return {"ok": True, "providers": {}, "errors": []}

    monkeypatch.setattr(cal_service, "sync_calendars", hung)
    monkeypatch.setattr(cal_service, "SYNC_TIMEOUT_S", 0.05)
    store = CalendarStore(tmp_path / "cal.db")
    try:
        svc = CalendarService({}, store=store)
        summary = await svc.sync()
        assert summary["ok"] is False
        assert any("timed out" in str(err).lower() for err in summary["errors"])
    finally:
        store.close()


@pytest.mark.asyncio
async def test_sync_pulls_holiday_calendars(tmp_path: Path, monkeypatch) -> None:
    from arelis.calendar.google_client import GoogleCalendarClient
    from arelis.calendar.secrets import CalendarSecrets, GoogleCalendarCreds
    from arelis.calendar.sync import sync_calendars

    class _FakeGoogle(GoogleCalendarClient):
        def __init__(self, creds) -> None:
            self.creds = creds
            self._access = "token"

        async def access_token(self) -> str:
            return "token"

        async def list_calendar_list(self) -> list[dict]:
            return [
                {"id": "primary", "summary": "Me", "primary": True},
                {
                    "id": "en.usa#holiday@group.v.calendar.google.com",
                    "summary": "Public holidays (en.usa)",
                },
            ]

        async def list_events(self, **kwargs):
            cal = str(kwargs.get("calendar_id") or "primary")
            start = datetime(2026, 8, 19, tzinfo=UTC)
            if "holiday" in cal:
                return [
                    CachedEvent(
                        id="google:labor",
                        provider="google",
                        calendar_id=cal,
                        summary="Labor Day",
                        starts_at=start,
                        ends_at=start + timedelta(days=1),
                        all_day=True,
                        raw_id="labor",
                    )
                ]
            return [
                CachedEvent(
                    id="google:lab",
                    provider="google",
                    calendar_id=cal,
                    summary="go to the lab",
                    starts_at=start.replace(hour=10),
                    ends_at=start.replace(hour=11),
                    all_day=False,
                    raw_id="lab",
                )
            ]

    monkeypatch.setattr("arelis.calendar.sync.GoogleCalendarClient", _FakeGoogle)
    store = CalendarStore(tmp_path / "cal.db")
    secrets = CalendarSecrets(
        google=GoogleCalendarCreds("id", "sec", refresh_token="ref"),
        outlook=None,
    )
    try:
        summary = await sync_calendars(
            {"tools": {"calendar": {"include_holidays": True}}},
            store=store,
            secrets=secrets,
            providers=("google",),
        )
        assert summary["ok"]
        assert summary["providers"]["google"]["count"] == 2
        day = datetime(2026, 8, 19, tzinfo=UTC).date()
        titles = {ev.summary for ev in store.list_range(day, day)}
        assert "Labor Day" in titles
        assert "go to the lab" in titles
    finally:
        store.close()
