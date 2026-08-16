from __future__ import annotations

from typing import Any

from arelis.briefing.builder import BRIEFING_PROMPT
from arelis.jobs import schedule as win
from arelis.jobs.store import (
    Job,
    JobError,
    delete_job,
    get_job,
    load_jobs,
    make_job_id,
    normalize_date,
    normalize_days,
    normalize_days_of_month,
    normalize_interval,
    normalize_times,
    upsert_job,
)
from arelis.mail import valid_address
from arelis.tools.base import ToolResult


class ScheduleTool:
    """Create and manage jobs that run on their own and email the result.

    risk="write" because creating one registers a real Windows scheduled task,
    which is a change to the machine and belongs behind the confirm card. The
    card is also where the user sees the recipient before anything is saved.
    """

    name = "schedule"
    description = (
        "Set up something to run automatically later and email the result: "
        "once at a future date and time, or repeating daily, on chosen "
        "weekdays, monthly, or every few hours. Use create_briefing for the "
        "fixed morning briefing (weather, unread mail, open loops). Also "
        "lists, deletes, and triggers saved jobs. Pass the user's own words "
        "for times and dates; this tool parses them, so never convert them "
        "yourself."
    )
    risk = "write"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "create_briefing", "list", "delete", "run_now"],
            },
            "name": {
                "type": "string",
                "description": "Short name, e.g. 'Morning news'. For create.",
            },
            "prompt": {
                "type": "string",
                "description": (
                    "What to actually do each time, written as if you were "
                    "asking it fresh. It runs with no conversation history, "
                    "so it must stand alone. Not used for create_briefing."
                ),
            },
            "time": {
                "type": "string",
                "description": (
                    "When to run: 19:00, 7pm, 7:30am. For more than once a "
                    "day, separate them: '8am, 6pm'. Default 7am for briefings."
                ),
            },
            "date": {
                "type": "string",
                "description": (
                    "For a one-off. Pass what the user said -- tomorrow, "
                    "next Friday, in 3 days, Aug 15, 2026-08-15. Setting this "
                    "makes it run once and then delete itself."
                ),
            },
            "days": {
                "type": "string",
                "description": "daily, weekdays, weekends, or mon,wed,fri",
            },
            "day_of_month": {
                "type": "string",
                "description": "For monthly, e.g. '1' or '1,15'. Use 28 for month-end.",
            },
            "every": {
                "type": "string",
                "description": (
                    "To repeat through the day: '2 hours', '30 minutes'. "
                    "Combines with days, and `time` becomes the start."
                ),
            },
            "recipient": {
                "type": "string",
                "description": "Where to email it. Omit to send to the user.",
            },
            "id": {"type": "string", "description": "Job id, for delete and run_now"},
        },
        "required": ["action"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action == "list":
            return self._list()
        if action == "create":
            return self._create(kwargs)
        if action == "create_briefing":
            return self._create_briefing(kwargs)
        if action == "delete":
            return self._delete(str(kwargs.get("id") or ""))
        if action == "run_now":
            return self._run_now(str(kwargs.get("id") or ""))
        return ToolResult(
            ok=False,
            output=(
                f"Unknown action {action!r}. Use create, create_briefing, "
                "list, delete, or run_now."
            ),
        )

    # ----------------------------------------------------------------- actions

    def _list(self) -> ToolResult:
        jobs = load_jobs()
        if not jobs:
            return ToolResult(ok=True, output="No scheduled jobs.", data={"jobs": []})
        registered = win.registered_ids()
        lines: list[str] = []
        for job in jobs:
            lines.append(job.describe())
            if job.enabled and job.id not in registered and win.supported():
                # Drift between the store and Task Scheduler is worth surfacing:
                # the job looks scheduled here but will never actually fire.
                lines.append("      NOT registered with Task Scheduler")
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={"jobs": [j.as_dict() for j in jobs]},
        )

    def _create_briefing(self, kwargs: dict[str, Any]) -> ToolResult:
        """Fixed morning digest — no free-form prompt for the model to invent."""
        payload = {
            **kwargs,
            "name": str(kwargs.get("name") or "Morning briefing").strip() or "Morning briefing",
            "prompt": BRIEFING_PROMPT,
            "time": kwargs.get("time") or "7am",
            "days": kwargs.get("days") or "daily",
            "role": "fast",
        }
        result = self._create(payload)
        if result.ok and result.data:
            # Say what arrives, so the user is not surprised by a sentinel prompt.
            result = ToolResult(
                ok=True,
                output=(
                    result.output
                    + " Each run emails the fixed briefing (weather, unread mail, "
                    "open loops, recent chats) — not a free-form research prompt."
                ),
                data={**result.data, "kind": "briefing"},
            )
        return result

    def _create(self, kwargs: dict[str, Any]) -> ToolResult:
        name = str(kwargs.get("name") or "").strip()
        prompt = str(kwargs.get("prompt") or "").strip()
        if not prompt:
            return ToolResult(ok=False, output="Missing prompt: say what it should do each time.")
        if not name:
            name = prompt[:40].strip()

        recipient = str(kwargs.get("recipient") or "").strip()
        if recipient and not valid_address(recipient):
            return ToolResult(ok=False, output=f"{recipient!r} is not a usable email address.")

        raw_date = str(kwargs.get("date") or "").strip()
        raw_month_days = str(kwargs.get("day_of_month") or "").strip()
        try:
            times = normalize_times(kwargs.get("time") or "19:00")
            days = normalize_days(kwargs.get("days"))
            days_of_month = normalize_days_of_month(raw_month_days)
            every = normalize_interval(kwargs.get("every"))
            when = normalize_date(raw_date)
        except JobError as exc:
            return ToolResult(ok=False, output=str(exc))

        # The mode follows from what was supplied, so the model does not have to
        # name it and cannot contradict itself by naming the wrong one.
        if when:
            repeat = "once"
        elif days_of_month:
            repeat = "monthly"
        else:
            repeat = "weekly"

        if repeat == "once" and len(times) > 1:
            return ToolResult(
                ok=False,
                output="A one-off runs at a single time. Give one time, or drop the date.",
            )

        role = str(kwargs.get("role") or "research").strip() or "research"
        job = Job(
            id="",
            name=name,
            prompt=prompt,
            recipient=recipient,
            role=role,
            repeat=repeat,
            times=times,
            days=days,
            date=when,
            days_of_month=days_of_month,
            every_minutes=every,
        )

        existing = load_jobs()
        duplicate = next((j for j in existing if _behaviour(j) == _behaviour(job)), None)
        if duplicate is not None:
            return self._already_scheduled(duplicate)

        job.id = make_job_id(name, [j.id for j in existing])
        upsert_job(job)

        try:
            win.register(job)
        except win.ScheduleError as exc:
            # Saved but not scheduled is a real, recoverable state, and saying
            # so is better than rolling back work the user asked for.
            return ToolResult(
                ok=True,
                output=(
                    f"Saved '{job.name}' as [{job.id}], but it could not be "
                    f"registered with Task Scheduler: {exc}\n"
                    f"Run it by hand with: arelis --run-job {job.id}"
                ),
                data={**job.as_dict(), "registered": False},
            )

        tail = (
            "It runs once and then removes itself."
            if job.one_off
            else "It runs whether or not Arelis is open, and catches up if the "
            "machine was asleep."
        )
        return ToolResult(
            ok=True,
            output=(
                f"Scheduled '{job.name}' [{job.id}] {job.schedule_text()}, "
                f"emailing {job.recipient or 'you'}. {tail}"
            ),
            data={**job.as_dict(), "registered": True},
        )

    def _already_scheduled(self, job: Job) -> ToolResult:
        """Report the job that already does this, instead of making a second one.

        Reported as a success, because from the caller's point of view the thing it asked
        for is true. Returning an error would invite the model to try again with a nudged
        name, which is how you get "digest" and "digest-2".

        Re-registered on the way out for the case that matters: a job whose task went
        missing, or which was turned off. Asking for something that already exists is the
        most natural way for a person to say "this should be running", so making it run is
        the useful reading of the request.
        """
        if not job.enabled:
            job.enabled = True
            upsert_job(job)
        try:
            win.register(job)
        except win.ScheduleError as exc:
            return ToolResult(
                ok=True,
                output=(
                    f"'{job.name}' [{job.id}] is already scheduled {job.schedule_text()}, "
                    f"but Task Scheduler would not take it: {exc}\n"
                    f"Run it by hand with: arelis --run-job {job.id}"
                ),
                data={**job.as_dict(), "registered": False, "already_existed": True},
            )
        return ToolResult(
            ok=True,
            output=(
                f"'{job.name}' [{job.id}] already does exactly this, {job.schedule_text()}, "
                f"emailing {job.recipient or 'you'}. Left as one job rather than two."
            ),
            data={**job.as_dict(), "registered": True, "already_existed": True},
        )

    def _delete(self, job_id: str) -> ToolResult:
        job_id = job_id.strip()
        if not job_id:
            return ToolResult(ok=False, output="Missing id. Use action='list' to see them.")
        # Calendar event ids belong to agenda, not Windows Task Scheduler (R8).
        lower = job_id.lower()
        if lower.startswith(("google:", "outlook:", "ics:")) or (
            len(job_id) >= 16
            and ":" not in job_id
            and all(c.isalnum() or c in "-_=" for c in job_id)
            and get_job(job_id) is None
        ):
            return ToolResult(
                ok=False,
                output=(
                    f"{job_id!r} looks like a calendar event id, not a scheduled "
                    "job. Use agenda(action=delete, event_id=..., "
                    "provider=google|outlook) instead."
                ),
            )
        if get_job(job_id) is None:
            return ToolResult(ok=False, output=f"No job with id {job_id!r}.")
        try:
            win.unregister(job_id)
        except win.ScheduleError as exc:
            return ToolResult(ok=False, output=f"Could not remove the scheduled task: {exc}")
        delete_job(job_id)
        return ToolResult(ok=True, output=f"Deleted job [{job_id}] and its scheduled task.")

    def _run_now(self, job_id: str) -> ToolResult:
        job_id = job_id.strip()
        job = get_job(job_id)
        if job is None:
            return ToolResult(ok=False, output=f"No job with id {job_id!r}.")
        try:
            win.run_now(job_id)
        except win.ScheduleError as exc:
            return ToolResult(
                ok=False,
                output=f"Could not start it: {exc}\nTry: arelis --run-job {job_id}",
            )
        # Deliberately does not wait. A research turn takes minutes and the
        # answer arrives by email, not as a tool result.
        return ToolResult(
            ok=True,
            output=f"Started '{job.name}' now. The result will arrive by email shortly.",
            data={"id": job_id},
        )


def _behaviour(job: Job) -> tuple[object, ...]:
    """Everything about a job that decides what happens, and nothing about how it reads.

    Used to tell "schedule this" apart from "schedule this again". Two jobs with the same
    prompt, recipient, role and schedule do the same work twice, whatever they are called,
    so the name is deliberately absent: a duplicate under a different label is still a
    duplicate. Times, days and days-of-month are compared after normalisation, so 7pm and
    19:00 are recognised as the same instruction rather than as two.

    Written after finding two identical nightly jobs on a real machine, ids differing only
    by a "-2" that make_job_id appended in good faith. They had both been running for days,
    a minute apart, and nothing was wrong enough to notice: each run succeeded.
    """
    return (
        job.prompt.strip().casefold(),
        job.recipient.strip().casefold(),
        job.role,
        job.repeat,
        tuple(job.times),
        tuple(job.days),
        job.date,
        tuple(job.days_of_month),
        job.every_minutes,
    )
