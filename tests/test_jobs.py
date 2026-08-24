from __future__ import annotations

import asyncio
from datetime import date

import pytest

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.jobs import schedule as win
from arelis.jobs.runner import _Collector
from arelis.jobs.store import (
    DAY_NAMES,
    Job,
    JobError,
    delete_job,
    describe_days,
    get_job,
    load_jobs,
    make_job_id,
    normalize_date,
    normalize_days,
    normalize_days_of_month,
    normalize_interval,
    normalize_time,
    normalize_times,
    record_run,
    save_jobs,
    upsert_job,
)


def _job(**kwargs) -> Job:
    base = {"id": "news", "name": "Morning news", "prompt": "Summarise the news"}
    return Job(**{**base, **kwargs})


TODAY = date(2026, 8, 7)  # a Friday


def test_jobs_default_to_fast_not_research() -> None:
    """Research stamps a page warrant. A weather briefing is not a report."""
    assert _job().role == "fast"


# ------------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("19:00", "19:00"),
        ("7pm", "19:00"),
        ("7 PM", "19:00"),
        ("7:30pm", "19:30"),
        ("7:30 a.m.", "07:30"),
        ("12am", "00:00"),
        ("12pm", "12:00"),
        ("09:05", "09:05"),
    ],
)
def test_times_are_parsed_here_not_by_the_model(given: str, expected: str) -> None:
    """A 7B asked for cron produces a wrong one eventually, and it fails at 3am."""
    assert normalize_time(given) == expected


@pytest.mark.parametrize("given", ["", "half past seven", "25:00", "19:70", "tomorrow"])
def test_an_unreadable_time_is_refused_at_the_prompt(given: str) -> None:
    with pytest.raises(JobError):
        normalize_time(given)


def test_day_shorthands() -> None:
    assert normalize_days("daily") == list(DAY_NAMES)
    assert normalize_days(None) == list(DAY_NAMES)
    assert normalize_days("weekdays") == list(DAY_NAMES[:5])
    assert normalize_days("weekends") == ["saturday", "sunday"]


def test_days_are_ordered_and_deduplicated() -> None:
    assert normalize_days("fri,mon,mon") == ["monday", "friday"]
    assert normalize_days(["Wednesday", "tue"]) == ["tuesday", "wednesday"]
    assert normalize_days("mon and wed") == ["monday", "wednesday"]


def test_a_day_that_is_not_a_day_is_refused() -> None:
    with pytest.raises(JobError):
        normalize_days("mon,funday")


def test_days_read_back_the_way_a_person_would_say_them() -> None:
    assert describe_days(list(DAY_NAMES)) == "every day"
    assert describe_days(list(DAY_NAMES[:5])) == "weekdays"
    assert describe_days(["monday", "friday"]) == "Monday, Friday"


# --------------------------------------------------------- more than once a day


def test_twice_a_day_is_one_job_with_two_times() -> None:
    """Otherwise she picks one of the two and you notice when mail stops."""
    assert normalize_times("8am, 6pm") == ["08:00", "18:00"]
    assert normalize_times("8am and 6pm") == ["08:00", "18:00"]
    assert normalize_times(["18:00", "08:00"]) == ["08:00", "18:00"]


def test_the_same_time_twice_is_one_time() -> None:
    assert normalize_times("9am, 09:00") == ["09:00"]


def test_a_job_needs_some_time_of_day() -> None:
    with pytest.raises(JobError):
        normalize_times("")


# ---------------------------------------------------------------------- dates


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("2026-08-15", "2026-08-15"),
        ("today", "2026-08-07"),
        ("tomorrow", "2026-08-08"),
        ("the day after tomorrow", "2026-08-09"),
        ("in 3 days", "2026-08-10"),
        ("in 2 weeks", "2026-08-21"),
        ("aug 15", "2026-08-15"),
        ("August 15th", "2026-08-15"),
        ("15 August", "2026-08-15"),
        ("8/15", "2026-08-15"),
        ("8/15/2026", "2026-08-15"),
    ],
)
def test_dates_are_resolved_here_because_the_model_does_not_know_today(
    given: str, expected: str
) -> None:
    assert normalize_date(given, today=TODAY) == expected


def test_a_weekday_name_means_the_next_one() -> None:
    # TODAY is a Friday.
    assert normalize_date("monday", today=TODAY) == "2026-08-10"
    assert normalize_date("next Monday", today=TODAY) == "2026-08-10"
    # Never today, even when the name matches today.
    assert normalize_date("friday", today=TODAY) == "2026-08-14"


def test_a_date_that_has_passed_rolls_to_next_year() -> None:
    """A start date in the past makes Task Scheduler fire immediately."""
    assert normalize_date("jan 5", today=TODAY) == "2027-01-05"
    assert normalize_date("1/5", today=TODAY) == "2027-01-05"


def test_no_date_means_no_date() -> None:
    assert normalize_date("") == ""


@pytest.mark.parametrize("given", ["someday", "the usual time", "2026-02-30", "13/45"])
def test_an_unreadable_date_is_refused(given: str) -> None:
    with pytest.raises(JobError):
        normalize_date(given, today=TODAY)


# -------------------------------------------------------------------- monthly


def test_days_of_the_month() -> None:
    assert normalize_days_of_month("1,15") == [1, 15]
    assert normalize_days_of_month("1st and 15th") == [1, 15]
    assert normalize_days_of_month([22, 3]) == [3, 22]
    assert normalize_days_of_month("") == []


def test_month_end_is_refused_with_something_useful_to_do_instead() -> None:
    with pytest.raises(JobError, match="28"):
        normalize_days_of_month("last")


def test_a_day_that_is_not_in_any_month_is_refused() -> None:
    with pytest.raises(JobError):
        normalize_days_of_month("32")


# ------------------------------------------------------------------- intervals


def test_intervals_are_read_as_people_say_them() -> None:
    assert normalize_interval("2 hours") == 120
    assert normalize_interval("every 2 hours") == 120
    assert normalize_interval("30 minutes") == 30
    assert normalize_interval("hourly".replace("ly", "")) == 60
    assert normalize_interval(90) == 90
    assert normalize_interval("") == 0


def test_an_interval_that_would_hammer_the_model_is_refused() -> None:
    with pytest.raises(JobError, match="15 minutes"):
        normalize_interval("5 minutes")


def test_an_interval_longer_than_half_a_day_should_be_a_schedule() -> None:
    with pytest.raises(JobError):
        normalize_interval("20 hours")


# --------------------------------------------------------- reading it back out


def test_each_shape_reads_back_in_plain_english() -> None:
    assert _job().schedule_text() == "every day at 19:00"
    assert _job(times=["08:00", "18:00"]).schedule_text() == "every day at 08:00 and 18:00"
    assert (
        _job(repeat="once", date="2026-08-15", times=["15:00"]).schedule_text()
        == "once on Saturday 15 August 2026 at 15:00"
    )
    assert (
        _job(repeat="monthly", days_of_month=[1, 15], times=["09:00"]).schedule_text()
        == "the 1st, 15th of each month at 09:00"
    )
    assert (
        _job(days=list(DAY_NAMES[:5]), every_minutes=120, times=["09:00"]).schedule_text()
        == "weekdays, every 2 hours from 09:00"
    )


# --------------------------------------------------------------------- store


def test_a_job_survives_a_round_trip(tmp_path) -> None:
    path = tmp_path / "jobs.yaml"
    job = _job(
        recipient="me@example.com",
        times=["08:00", "18:00"],
        days=["monday", "friday"],
    )
    save_jobs([job], path)

    loaded = load_jobs(path)
    assert len(loaded) == 1
    assert loaded[0] == job


def test_a_one_off_survives_a_round_trip(tmp_path) -> None:
    path = tmp_path / "jobs.yaml"
    job = _job(repeat="once", date="2026-08-15", times=["15:00"])
    save_jobs([job], path)
    assert load_jobs(path)[0] == job


def test_a_hand_edited_file_is_normalised_on_load(tmp_path) -> None:
    """data/jobs.yaml is meant to be editable when something goes wrong at 7am."""
    path = tmp_path / "jobs.yaml"
    path.write_text(
        "jobs:\n  - id: news\n    name: News\n    prompt: go\n"
        "    time: '7pm'\n    days: weekdays\n",
        encoding="utf-8",
    )
    job = load_jobs(path)[0]
    # `time` singular is accepted as well as `times`, since that is what a
    # person writes when editing by hand.
    assert job.times == ["19:00"]
    assert job.days == list(DAY_NAMES[:5])
    assert job.repeat == "weekly"


def test_a_one_off_with_no_date_is_rejected_rather_than_firing_today(tmp_path) -> None:
    path = tmp_path / "jobs.yaml"
    path.write_text(
        "jobs:\n  - id: broken\n    name: Broken\n    prompt: go\n    repeat: once\n",
        encoding="utf-8",
    )
    assert load_jobs(path) == []


def test_loading_an_absent_file_is_not_an_error(tmp_path) -> None:
    assert load_jobs(tmp_path / "nothing.yaml") == []


def test_one_corrupt_job_does_not_take_the_others_down(tmp_path) -> None:
    """A bad entry must not silently unschedule everything else."""
    path = tmp_path / "jobs.yaml"
    path.write_text(
        "jobs:\n"
        "  - id: broken\n    name: Broken\n    time: 'half past'\n"
        "  - id: fine\n    name: Fine\n    prompt: do it\n    time: '08:00'\n",
        encoding="utf-8",
    )
    loaded = load_jobs(path)
    assert [j.id for j in loaded] == ["fine"]


def test_upsert_replaces_rather_than_duplicates(tmp_path) -> None:
    path = tmp_path / "jobs.yaml"
    upsert_job(_job(), path)
    upsert_job(_job(name="Renamed"), path)

    jobs = load_jobs(path)
    assert len(jobs) == 1
    assert jobs[0].name == "Renamed"


def test_delete_reports_whether_anything_went(tmp_path) -> None:
    path = tmp_path / "jobs.yaml"
    upsert_job(_job(), path)
    assert delete_job("news", path) is True
    assert delete_job("news", path) is False
    assert load_jobs(path) == []


def test_lookup_ignores_case(tmp_path) -> None:
    path = tmp_path / "jobs.yaml"
    upsert_job(_job(), path)
    assert get_job("NEWS", path) is not None


def test_the_last_outcome_is_written_down(tmp_path) -> None:
    """A digest that stopped arriving looks exactly like a quiet week."""
    path = tmp_path / "jobs.yaml"
    upsert_job(_job(), path)
    record_run("news", "failed: no network", path)

    job = get_job("news", path)
    assert job is not None
    assert job.last_status == "failed: no network"
    assert job.last_run


def test_ids_are_readable_slugs_and_never_collide() -> None:
    assert make_job_id("Morning News!", []) == "morning-news"
    assert make_job_id("Morning News!", ["morning-news"]) == "morning-news-2"


# ------------------------------------------------------------ windows task xml


def test_the_task_catches_up_after_the_machine_was_asleep() -> None:
    """Without StartWhenAvailable a 7pm job is simply skipped if the PC was off."""
    xml = win.build_task_xml(_job(), command=r"C:\py\pythonw.exe")
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml


def test_the_task_runs_the_job_windowlessly() -> None:
    xml = win.build_task_xml(_job(), command=r"C:\py\pythonw.exe")
    assert "<Command>C:\\py\\pythonw.exe</Command>" in xml
    assert "<Arguments>-m arelis --run-job news</Arguments>" in xml
    assert "<RunLevel>LeastPrivilege</RunLevel>" in xml


def test_the_start_time_is_the_time_that_was_asked_for() -> None:
    xml = win.build_task_xml(_job(times=["07:05"]), now=date(2026, 8, 6))
    assert "<StartBoundary>2026-08-06T07:05:00</StartBoundary>" in xml


def test_every_day_uses_a_daily_trigger() -> None:
    xml = win.build_task_xml(_job())
    assert "<ScheduleByDay>" in xml
    assert "ScheduleByWeek" not in xml


def test_chosen_days_use_a_weekly_trigger() -> None:
    xml = win.build_task_xml(_job(days=["monday", "friday"]))
    assert "<ScheduleByWeek>" in xml
    assert "<Monday/>" in xml
    assert "<Friday/>" in xml
    assert "<Tuesday/>" not in xml


def test_two_times_a_day_is_two_triggers_in_one_task() -> None:
    """Two tasks could drift apart; one task with two triggers cannot."""
    xml = win.build_task_xml(_job(times=["08:00", "18:00"]), now=date(2026, 8, 6))
    assert xml.count("<CalendarTrigger>") == 2
    assert "<StartBoundary>2026-08-06T08:00:00</StartBoundary>" in xml
    assert "<StartBoundary>2026-08-06T18:00:00</StartBoundary>" in xml


def test_a_one_off_fires_once_and_removes_itself() -> None:
    xml = win.build_task_xml(_job(repeat="once", date="2026-08-15", times=["15:00"]))
    assert "<TimeTrigger>" in xml
    assert "CalendarTrigger" not in xml
    assert "<StartBoundary>2026-08-15T15:00:00</StartBoundary>" in xml
    # DeleteExpiredTaskAfter only applies to a trigger that has an end.
    assert "<EndBoundary>2026-08-15T15:00:59</EndBoundary>" in xml
    assert "<DeleteExpiredTaskAfter>PT10M</DeleteExpiredTaskAfter>" in xml


def test_a_recurring_job_never_deletes_itself() -> None:
    assert "DeleteExpiredTaskAfter" not in win.build_task_xml(_job())


def test_monthly_names_the_days_and_every_month() -> None:
    xml = win.build_task_xml(_job(repeat="monthly", days_of_month=[1, 15]))
    assert "<ScheduleByMonth>" in xml
    assert "<Day>1</Day>" in xml
    assert "<Day>15</Day>" in xml
    assert xml.count("<January/>") == 1
    assert "<December/>" in xml


def test_every_few_hours_becomes_a_repetition() -> None:
    xml = win.build_task_xml(_job(every_minutes=120, times=["09:00"]))
    assert "<Interval>PT120M</Interval>" in xml
    assert "<Duration>P1D</Duration>" in xml


def test_a_plain_job_has_no_repetition_block() -> None:
    assert "<Repetition>" not in win.build_task_xml(_job())


def test_a_name_with_markup_in_it_cannot_break_the_xml() -> None:
    xml = win.build_task_xml(_job(name="Bob & <friends>"))
    assert "Bob &amp; &lt;friends&gt;" in xml
    assert "<friends>" not in xml


def test_tasks_live_together_in_one_folder() -> None:
    assert win.task_name("news") == "\\Arelis\\news"


# -------------------------------------------------------------------- runner


@pytest.mark.asyncio
async def test_an_unattended_turn_refuses_everything_that_asks() -> None:
    """Nobody is there to read a confirm card, so nothing that needs one runs."""
    bus = EventBus()
    collector = _Collector(bus)
    replies: list[dict] = []
    bus.subscribe(
        EventType.TOOL_CONFIRM_REPLY, lambda event: replies.append(event.payload)
    )

    task = asyncio.create_task(bus.run())
    await bus.publish(
        Event(EventType.TOOL_CONFIRM, {"id": "abc", "summary": "workspace(action=write)"})
    )
    await bus.drain()
    bus.stop()
    task.cancel()

    assert replies == [{"id": "abc", "decision": "skip", "allow_turn": False}]
    assert collector.refused == ["workspace(action=write)"]


@pytest.mark.asyncio
async def test_the_answer_ends_the_wait() -> None:
    bus = EventBus()
    collector = _Collector(bus)
    task = asyncio.create_task(bus.run())

    await bus.publish(Event(EventType.ASSISTANT_DONE, {"text": "Here is the news."}))
    await asyncio.wait_for(collector.done.wait(), timeout=2)
    bus.stop()
    task.cancel()

    assert collector.answer == "Here is the news."
    assert not collector.error


@pytest.mark.asyncio
async def test_a_failure_also_ends_the_wait() -> None:
    """A job that dies silently is worse than one that mails you the error."""
    bus = EventBus()
    collector = _Collector(bus)
    task = asyncio.create_task(bus.run())

    await bus.publish(Event(EventType.ERROR, {"message": "model unreachable"}))
    await asyncio.wait_for(collector.done.wait(), timeout=2)
    bus.stop()
    task.cancel()

    assert collector.error == "model unreachable"


def test_running_an_unknown_job_fails_loudly(monkeypatch) -> None:
    from arelis.jobs import runner

    monkeypatch.setattr(runner, "get_job", lambda job_id: None)
    assert runner.run_job("does-not-exist") == 2
