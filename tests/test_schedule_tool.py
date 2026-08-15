"""ScheduleTool: the surface the model actually calls for jobs."""

from __future__ import annotations

import pytest

from arelis.jobs import schedule as win
from arelis.jobs import store as store_mod
from arelis.tools.schedule_jobs import ScheduleTool


@pytest.fixture
def jobs_path(tmp_path, monkeypatch):
    path = tmp_path / "jobs.yaml"
    monkeypatch.setattr(store_mod, "JOBS_PATH", path)
    monkeypatch.setattr(win, "supported", lambda: True)
    monkeypatch.setattr(win, "registered_ids", lambda: set())
    monkeypatch.setattr(win, "register", lambda job: None)
    monkeypatch.setattr(win, "unregister", lambda job_id: None)
    monkeypatch.setattr(win, "run_now", lambda job_id: None)
    return path


@pytest.mark.asyncio
async def test_create_list_delete_round_trip(jobs_path) -> None:
    tool = ScheduleTool()
    created = await tool.run(
        action="create",
        name="Morning news",
        prompt="Summarise overnight news",
        time="7am",
        days="weekdays",
    )
    assert created.ok
    assert created.data["id"]
    job_id = created.data["id"]

    listed = await tool.run(action="list")
    assert listed.ok
    assert job_id in listed.output
    assert "Morning news" in listed.output

    deleted = await tool.run(action="delete", id=job_id)
    assert deleted.ok
    assert store_mod.load_jobs() == []


@pytest.mark.asyncio
async def test_create_refuses_a_bad_recipient(jobs_path) -> None:
    tool = ScheduleTool()
    result = await tool.run(
        action="create",
        name="Bad",
        prompt="do a thing",
        time="8am",
        recipient="not-an-email",
    )
    assert not result.ok
    assert "email" in result.output.lower()


@pytest.mark.asyncio
async def test_create_parses_natural_times_itself(jobs_path) -> None:
    """The model must not invent cron; the tool owns the clock words."""
    tool = ScheduleTool()
    result = await tool.run(
        action="create",
        name="Twice",
        prompt="check the lab",
        time="8am, 6pm",
        days="mon,wed,fri",
    )
    assert result.ok
    assert result.data["times"] == ["08:00", "18:00"]
    assert result.data["days"] == ["monday", "wednesday", "friday"]


@pytest.mark.asyncio
async def test_run_now_needs_a_real_id(jobs_path) -> None:
    tool = ScheduleTool()
    result = await tool.run(action="run_now", id="nope")
    assert not result.ok
    assert "No job" in result.output


@pytest.mark.asyncio
async def test_unknown_action_is_rejected(jobs_path) -> None:
    tool = ScheduleTool()
    result = await tool.run(action="pause")
    assert not result.ok
    assert "create_briefing" in result.output
    assert "run_now" in result.output


@pytest.mark.asyncio
async def test_saved_but_unregistered_is_still_ok(jobs_path, monkeypatch) -> None:
    def boom(job):
        raise win.ScheduleError("Task Scheduler said no")

    monkeypatch.setattr(win, "register", boom)
    tool = ScheduleTool()
    result = await tool.run(
        action="create",
        name="Orphan",
        prompt="still useful",
        time="9am",
    )
    assert result.ok
    assert result.data["registered"] is False
    assert "could not be registered" in result.output
    assert store_mod.get_job(result.data["id"]) is not None
