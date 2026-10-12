"""Create still lands. A different event on that hour is named in the result."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from arelis.calendar.models import CachedEvent
from arelis.tools.agenda import AgendaTool


class _Store:
    def __init__(self, events: list[CachedEvent]) -> None:
        self._events = events

    def list_range(self, *_args, **_kwargs) -> list[CachedEvent]:
        return list(self._events)

    def close(self) -> None:
        return None


class _Service:
    def __init__(self, *_args, **_kwargs) -> None:
        return None

    async def create(self, **kwargs):
        start = kwargs["starts_at"]
        return SimpleNamespace(
            summary=kwargs["summary"],
            starts_at=start,
            provider="local",
            sync_state="pending",
            as_dict=lambda: {
                "summary": kwargs["summary"],
                "starts_at": start.isoformat(),
            },
        )


@pytest.mark.asyncio
async def test_create_names_a_different_event_on_the_same_hour(monkeypatch) -> None:
    existing = CachedEvent(
        id="local:1",
        provider="local",
        calendar_id="local",
        summary="Standup",
        starts_at=datetime(2026, 9, 26, 15, 0),
        ends_at=datetime(2026, 9, 26, 15, 30),
        all_day=False,
    )
    monkeypatch.setattr(
        "arelis.tools.agenda.CalendarStore",
        lambda: _Store([existing]),
    )
    monkeypatch.setattr("arelis.tools.agenda.CalendarService", _Service)
    tool = AgendaTool({})

    result = await tool.run(
        action="create",
        summary="Dentist",
        start="2026-09-26T15:00:00",
        end="2026-09-26T16:00:00",
        provider="local",
    )

    assert result.ok, result.output
    assert "your Arelis calendar" in result.output
    assert "Dentist" in result.output
    assert "Google" not in result.output
    assert "Standup" in result.output
    assert result.data["overlaps"][0]["summary"] == "Standup"


def _event(**kwargs):
    start = kwargs["starts_at"]
    provider = kwargs.get("provider") or "local"
    summary = kwargs["summary"]
    return SimpleNamespace(
        summary=summary,
        starts_at=start,
        provider=provider,
        sync_state="pending" if provider == "local" else "synced",
        id=f"{provider}:1",
        as_dict=lambda: {
            "summary": summary,
            "starts_at": start.isoformat(),
            "provider": provider,
        },
    )


class _DestinationService:
    def __init__(self, provider: str) -> None:
        self._provider = provider

    async def create(self, **kwargs):
        kwargs["provider"] = self._provider
        return _event(**kwargs)

    async def update(self, event_id, **kwargs):
        summary = kwargs.get("summary") or "Lunch"
        start = datetime(2026, 9, 26, 15, 0)
        return SimpleNamespace(
            summary=summary,
            starts_at=start,
            provider=self._provider,
            sync_state="pending" if self._provider == "local" else "synced",
            id=event_id,
            as_dict=lambda: {"summary": summary, "provider": self._provider},
        )


@pytest.mark.asyncio
async def test_create_and_update_name_the_calendar_they_actually_used(
    monkeypatch,
) -> None:
    """The result names the calendar the event landed on.

    A local save used to say it would sync to Google, and the model told
    a profile with no Google calendar that the event was added there.
    """
    monkeypatch.setattr(
        "arelis.tools.agenda.CalendarStore",
        lambda: _Store([]),
    )

    def _use(provider: str):
        monkeypatch.setattr(
            "arelis.tools.agenda.CalendarService",
            lambda *args, **kwargs: _DestinationService(provider),
        )

    tool = AgendaTool({})
    _use("local")
    created = await tool.run(
        action="create",
        summary="Lunch",
        start="2026-09-26T15:00:00",
        provider="google",
    )
    assert created.ok, created.output
    assert "your Arelis calendar" in created.output
    assert "Google" not in created.output
    assert "Lunch" in created.output

    updated = await tool.run(
        action="update",
        event_id="local:1",
        summary="Lunch",
        provider="local",
    )
    assert updated.ok, updated.output
    assert "your Arelis calendar" in updated.output
    assert "Google" not in updated.output

    _use("google")
    on_google = await tool.run(
        action="create",
        summary="Lunch",
        start="2026-09-26T16:00:00",
        provider="google",
    )
    assert on_google.ok, on_google.output
    assert "your Google calendar" in on_google.output
    assert "Arelis calendar" not in on_google.output

    moved = await tool.run(
        action="update",
        event_id="google:1",
        summary="Lunch",
        provider="google",
    )
    assert moved.ok, moved.output
    assert "your Google calendar" in moved.output
    assert "Arelis calendar" not in moved.output
