"""Moving a briefing to a different time should not mean rebuilding the job.

`schedule` shipped with create / create_briefing / list / delete / run_now.
Changing the time on a standing job meant delete + recreate, which issues a
new id, drops last_run and last_status, and — because Task Scheduler
registration is a separate step that can fail on its own — gives you two ways
to end up with no job at all instead of one job at a new time.

The machinery was already there and unreachable: `save_job_from_payload`
create-or-replaces and is what the calendar jobs tab calls. The tool just had
no action wired to it.

A partial update has to merge with the stored job first, because
`build_job_from_fields` requires a prompt and would reject "just move it to
8am". The merge also has to translate: the payload speaks `time`, `every` and
`day_of_month` while the Job carries `times`, `every_minutes` and
`days_of_month`.

Both the job store and Task Scheduler are stubbed here. A test that registers
a real scheduled task on the machine running it is not a test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.jobs import schedule as win
from arelis.jobs import store as store_mod
from arelis.jobs.store import Job, get_job, upsert_job
from arelis.tools.policy import SCHEDULE_WRITE_ACTIONS, action_is_delete, action_is_write
from arelis.tools.schedule_jobs import ScheduleTool


@pytest.fixture
def scheduled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScheduleTool:
    monkeypatch.setattr(store_mod, "JOBS_PATH", tmp_path / "jobs.yaml")
    # Never touch the real Task Scheduler from a test run.
    monkeypatch.setattr(win, "register", lambda _job: None)
    monkeypatch.setattr(win, "registered_ids", lambda: set())
    monkeypatch.setattr(win, "supported", lambda: False)
    upsert_job(
        Job(
            id="morning-briefing",
            name="Morning briefing",
            prompt="Weather, calendar, and unread mail.",
            recipient="you@example.com",
            times=["07:00"],
            last_run="2026-09-16 07:00",
            last_status="ok",
        )
    )
    return ScheduleTool()


def test_update_is_a_write_but_not_a_delete() -> None:
    assert "update" in SCHEDULE_WRITE_ACTIONS
    assert action_is_write("schedule", {"action": "update"}) is True
    assert action_is_delete("schedule", {"action": "update"}) is False
    assert action_is_delete("schedule", {"action": "delete"}) is True


@pytest.mark.asyncio
async def test_the_time_can_move_without_rewriting_the_prompt(
    scheduled: ScheduleTool,
) -> None:
    result = await scheduled.run(action="update", id="morning-briefing", time="8am")
    assert result.ok, result.output

    job = get_job("morning-briefing")
    assert job is not None, "the id must survive an edit"
    assert job.times == ["08:00"]
    assert job.prompt == "Weather, calendar, and unread mail."
    assert job.recipient == "you@example.com"


@pytest.mark.asyncio
async def test_the_history_survives_an_edit(scheduled: ScheduleTool) -> None:
    """The reason update exists rather than delete + recreate.

    A digest that stops arriving looks exactly like a quiet week, which is why
    the store records last_run at all. Losing it on every reschedule would
    defeat the one signal that says a job quietly stopped working.
    """
    await scheduled.run(action="update", id="morning-briefing", time="8am")

    job = get_job("morning-briefing")
    assert job is not None
    assert job.last_run == "2026-09-16 07:00"
    assert job.last_status == "ok"


@pytest.mark.asyncio
async def test_the_prompt_can_change_without_moving_the_time(
    scheduled: ScheduleTool,
) -> None:
    result = await scheduled.run(action="update", id="morning-briefing", prompt="Just the weather.")
    assert result.ok, result.output

    job = get_job("morning-briefing")
    assert job is not None
    assert job.prompt == "Just the weather."
    assert job.times == ["07:00"], "changing the prompt must not move the time"


@pytest.mark.asyncio
async def test_the_days_can_change(scheduled: ScheduleTool) -> None:
    result = await scheduled.run(action="update", id="morning-briefing", days="weekdays")
    assert result.ok, result.output

    job = get_job("morning-briefing")
    assert job is not None
    assert job.days == ["monday", "tuesday", "wednesday", "thursday", "friday"]


@pytest.mark.asyncio
async def test_update_needs_an_id(scheduled: ScheduleTool) -> None:
    result = await scheduled.run(action="update", time="8am")
    assert not result.ok
    assert "id" in result.output.lower()


@pytest.mark.asyncio
async def test_updating_a_job_that_is_not_there_says_so(
    scheduled: ScheduleTool,
) -> None:
    result = await scheduled.run(action="update", id="no-such-job", time="8am")
    assert not result.ok
    assert "no-such-job" in result.output


@pytest.mark.asyncio
async def test_changing_nothing_is_refused(scheduled: ScheduleTool) -> None:
    """An ok that changed nothing is how she reports a reschedule that never happened."""
    result = await scheduled.run(action="update", id="morning-briefing")
    assert not result.ok
