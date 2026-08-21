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
async def test_asking_twice_for_the_same_job_does_not_make_two(jobs_path) -> None:
    """Found on a real machine: two identical nightly jobs, ids differing by a "-2".

    Both had been running for days, a minute apart, each succeeding, so nothing surfaced
    as broken -- the work simply happened twice every night. The model calling this tool
    twice for one request is ordinary, whether from a retry or from the user saying it
    again, so creating a job has to be idempotent rather than merely unique.
    """
    tool = ScheduleTool()
    first = await tool.run(
        action="create",
        name="Push and commit work on Arelis at 23:00",
        prompt="Push and commit work on Arelis at 23:00 tonight.",
        time="23:00",
        days="daily",
    )
    second = await tool.run(
        action="create",
        name="Push and commit work on Arelis at 23:00",
        prompt="Push and commit work on Arelis at 23:00 tonight.",
        time="23:00",
        days="daily",
    )

    assert first.ok and second.ok
    assert second.data["already_existed"] is True
    assert second.data["id"] == first.data["id"]
    assert [j.id for j in store_mod.load_jobs()] == [first.data["id"]]


@pytest.mark.asyncio
async def test_the_same_work_at_a_different_time_is_a_second_job(jobs_path) -> None:
    """The non-vacuity half. Deduplicating on the prompt alone would silently refuse a
    second run of the same report at a different hour, which is a thing people want."""
    tool = ScheduleTool()
    evening = await tool.run(
        action="create", name="Digest", prompt="Summarise the day", time="19:00", days="daily"
    )
    morning = await tool.run(
        action="create", name="Digest", prompt="Summarise the day", time="7am", days="daily"
    )

    assert evening.data["id"] != morning.data["id"]
    assert len(store_mod.load_jobs()) == 2


@pytest.mark.asyncio
async def test_a_duplicate_named_differently_is_still_a_duplicate(jobs_path) -> None:
    """Names are cosmetic; two jobs doing the same work at the same time are one job."""
    tool = ScheduleTool()
    first = await tool.run(
        action="create", name="Nightly push", prompt="Push the work", time="23:00", days="daily"
    )
    again = await tool.run(
        action="create", name="Commit at 11pm", prompt="Push the work", time="23:00", days="daily"
    )

    assert again.data["id"] == first.data["id"]
    assert len(store_mod.load_jobs()) == 1


@pytest.mark.asyncio
async def test_asking_again_switches_a_disabled_job_back_on(jobs_path) -> None:
    """Asking for something that already exists reads as "this should be running"."""
    tool = ScheduleTool()
    created = await tool.run(
        action="create", name="Digest", prompt="Summarise the day", time="19:00", days="daily"
    )
    jobs = store_mod.load_jobs()
    jobs[0].enabled = False
    store_mod.save_jobs(jobs)

    again = await tool.run(
        action="create", name="Digest", prompt="Summarise the day", time="19:00", days="daily"
    )

    assert again.data["id"] == created.data["id"]
    assert store_mod.load_jobs()[0].enabled is True


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


@pytest.mark.asyncio
async def test_save_job_from_payload_updates_prompt(jobs_path) -> None:
    from arelis.tools.schedule_jobs import save_job_from_payload

    tool = ScheduleTool()
    created = await tool.run(
        action="create",
        name="Morning weather email",
        prompt="Weather for Springfield.",
        time="9am",
        days="daily",
        recipient="you@example.com",
    )
    assert created.ok
    job_id = created.data["id"]
    updated = save_job_from_payload(
        {
            "id": job_id,
            "name": "Morning weather email",
            "prompt": "Weather for Springfield IL and Metropolis IL.",
            "time": "9am",
            "days": "daily",
            "recipient": "you@example.com",
            "enabled": True,
        }
    )
    assert updated.ok
    assert "Updated" in updated.output
    job = store_mod.get_job(job_id)
    assert job is not None
    assert "Metropolis" in job.prompt


def test_schedule_list_does_not_need_confirm() -> None:
    from arelis.tools.base import ToolRegistry

    registry = ToolRegistry()
    registry.register(ScheduleTool())
    assert not registry.needs_confirm("schedule", {"action": "list"})
    for action in ("create", "create_briefing", "delete", "run_now"):
        assert registry.needs_confirm("schedule", {"action": action})
