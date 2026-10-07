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
    assert "Created on local: Dentist" in result.output
    assert "Standup" in result.output
    assert result.data["overlaps"][0]["summary"] == "Standup"
