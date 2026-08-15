"""Deterministic briefing template — on demand and as a scheduled job."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from arelis.briefing import BRIEFING_PROMPT, build_briefing, is_briefing_job
from arelis.briefing.weather import describe_weather_code
from arelis.core.memory import SessionMemory
from arelis.jobs.store import Job
from arelis.location import UserLocation
from arelis.memory import MemoryStore
from arelis.tools.base import ToolResult


class _FakeLocation:
    def __init__(self, loc: UserLocation) -> None:
        self._loc = loc

    def snapshot(self) -> UserLocation:
        return self._loc


class _FakeInbox:
    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        self.calls.append(kwargs)
        return self.result


@pytest.mark.asyncio
async def test_briefing_assembles_weather_mail_facts_and_sessions(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    memory = SessionMemory(sink=store)
    memory.add("user", "Lab notes about the interferometer")
    store.add_fact("Prefer Fahrenheit", source="explicit", status="active")

    inbox = _FakeInbox(
        ToolResult(
            ok=True,
            output="mail",
            data={
                "messages": [
                    {
                        "id": "1",
                        "from": "bank@example.com",
                        "subject": "Statement ready",
                        "date": "2026-08-07",
                        "unread": True,
                    }
                ],
                "matched": 1,
                "total": 20,
                "unread": 1,
            },
        )
    )
    location = _FakeLocation(
        UserLocation(
            city="Springfield",
            region="Illinois",
            latitude=39.7817,
            longitude=-89.6501,
            sources={"city": "test", "latitude": "test", "longitude": "test"},
        )
    )

    weather_json = {
        "current": {
            "temperature_2m": 72.0,
            "apparent_temperature": 70.0,
            "weather_code": 1,
        },
        "daily": {
            "temperature_2m_max": [80.0],
            "temperature_2m_min": [60.0],
            "precipitation_probability_max": [10],
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "open-meteo.com" in str(request.url)
        return httpx.Response(200, json=weather_json)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        text = await build_briefing(
            {"tools": {"briefing": {"mail_limit": 5}}},
            store=store,
            inbox=inbox,  # type: ignore[arg-type]
            location=location,  # type: ignore[arg-type]
            http_client=client,
        )

    assert "# Briefing" in text
    assert "Springfield" in text
    assert "72°F" in text
    assert "mainly clear" in text
    assert "Statement ready" in text
    assert "Prefer Fahrenheit" in text
    assert "Lab notes" in text
    assert "## Agenda" in text
    # Local data/calendar.ics may exist on operator machines; accept empty,
    # example-path footer, or a real agenda section with events.
    assert (
        "calendar.example.ics" in text
        or "No local calendar" in text
        or "No events" in text
        or "**Today**" in text
        or "**Tomorrow**" in text
    )
    assert inbox.calls[0]["unread_only"] is True
    store.close()


@pytest.mark.asyncio
async def test_briefing_includes_local_ics_agenda(tmp_path, monkeypatch) -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    ics = tmp_path / "calendar.ics"
    ics.write_text(
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\n"
        "DTSTART:20260808T100000\nSUMMARY:Dentist\n"
        "END:VEVENT\nEND:VCALENDAR\n",
        encoding="utf-8",
    )
    store = MemoryStore(tmp_path / "memory.db")
    inbox = _FakeInbox(
        ToolResult(ok=True, output="mail", data={"messages": [], "matched": 0})
    )
    location = _FakeLocation(
        UserLocation(
            city="Springfield",
            region="Illinois",
            latitude=39.7817,
            longitude=-89.6501,
            sources={"city": "test", "latitude": "test", "longitude": "test"},
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "current": {
                    "temperature_2m": 70.0,
                    "apparent_temperature": 70.0,
                    "weather_code": 0,
                },
                "daily": {
                    "temperature_2m_max": [75.0],
                    "temperature_2m_min": [55.0],
                    "precipitation_probability_max": [0],
                },
            },
        )

    fixed = datetime(2026, 8, 8, 8, 0, tzinfo=ZoneInfo("America/New_York"))

    class _FixedDateTime:
        @staticmethod
        def now(tz=None):
            if tz is None:
                return fixed
            return fixed.astimezone(tz)

    monkeypatch.setattr("arelis.briefing.builder.datetime", _FixedDateTime)
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        text = await build_briefing(
            {"tools": {"briefing": {"calendar_path": str(ics)}}},
            store=store,
            inbox=inbox,  # type: ignore[arg-type]
            location=location,  # type: ignore[arg-type]
            http_client=client,
        )
    assert "## Agenda" in text
    assert "Dentist" in text
    assert "**Today**" in text
    store.close()


def test_the_scheduled_briefing_survived_losing_the_chat_tool() -> None:
    """The emailed digest is the half worth keeping.

    jobs/runner.py calls build_briefing directly and never asks the model, so
    deleting the chat tool must not reach it. If this import breaks, a scheduled
    7am briefing silently stops arriving.
    """
    from arelis.briefing import build_briefing, is_briefing_job

    assert callable(build_briefing)
    assert callable(is_briefing_job)


def test_the_briefing_tool_is_gone_from_the_model_surface() -> None:
    import arelis.tools as tools_pkg

    assert not hasattr(tools_pkg, "BriefingTool")
    assert not hasattr(tools_pkg, "AttentionTool")


def test_briefing_jobs_are_recognised_by_sentinel_prompt() -> None:
    assert is_briefing_job(Job(id="b", name="Morning", prompt=BRIEFING_PROMPT))
    assert not is_briefing_job(Job(id="n", name="News", prompt="Summarise the news"))


def test_weather_codes_read_as_words() -> None:
    assert describe_weather_code(0) == "clear"
    assert describe_weather_code(63) == "rain"
    assert describe_weather_code("nope") == ""


@pytest.fixture
def jobs_path(tmp_path, monkeypatch):
    from arelis.jobs import schedule as win
    from arelis.jobs import store as store_mod

    path = tmp_path / "jobs.yaml"
    monkeypatch.setattr(store_mod, "JOBS_PATH", path)
    monkeypatch.setattr(win, "supported", lambda: True)
    monkeypatch.setattr(win, "registered_ids", lambda: set())
    monkeypatch.setattr(win, "register", lambda job: None)
    monkeypatch.setattr(win, "unregister", lambda job_id: None)
    monkeypatch.setattr(win, "run_now", lambda job_id: None)
    return path


@pytest.mark.asyncio
async def test_schedule_create_briefing_stores_the_sentinel(jobs_path) -> None:
    from arelis.tools.schedule_jobs import ScheduleTool

    tool = ScheduleTool()
    result = await tool.run(action="create_briefing", time="7am", days="weekdays")
    assert result.ok
    assert result.data["prompt"] == BRIEFING_PROMPT
    assert result.data["kind"] == "briefing"
    assert "fixed briefing" in result.output.lower()
