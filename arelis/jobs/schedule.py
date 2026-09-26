"""Registering jobs with Windows Task Scheduler.

Task XML rather than the simple `schtasks /Create /SC DAILY /ST 19:00` form,
because the flags cannot express StartWhenAvailable. Without it a 7pm job on a
machine that was asleep at 7pm is simply skipped, and "it works unless the PC
was off" is not what a daily digest means.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from arelis.jobs.store import DAY_NAMES, MONTH_NAMES, Job, load_jobs
from arelis.paths import INSTALL_PARENT, ensure, state_dir, user_data_dir

log = logging.getLogger(__name__)

TASK_FOLDER = "Arelis"
_TIMEOUT_S = 30


class ScheduleError(RuntimeError):
    """schtasks refused, or is not available on this platform."""


def task_name(job_id: str) -> str:
    # A folder path, so every task Arelis owns is together in the Task
    # Scheduler tree and none of them collide with anything else.
    return f"\\{TASK_FOLDER}\\{job_id}"


def supported() -> bool:
    return sys.platform == "win32"


def runner_command() -> tuple[str, str]:
    """The executable and the argument prefix Task Scheduler should run.

    A pair, because the two halves do not vary together. The prefix is whatever
    turns the executable into a running Arelis: ``-m arelis`` when the executable
    is an interpreter, and nothing at all when the executable *is* Arelis. The
    second element used to be an empty string that build_task_xml ignored in favour
    of a hardcoded ``-m arelis``, which is correct for every packaging that ships
    an interpreter and silently wrong for any that does not, since ``-m`` means
    nothing to a frozen executable. The failure mode would have been every
    scheduled job failing at 7am with nobody watching.

    pythonw rather than python: the console build flashes a black window on
    screen at 7pm every day, which is exactly the kind of thing that makes
    someone turn a feature off.

    Candidates in descending specificity. A frozen build first, because there is
    no interpreter to look for and asking for one would be wrong. Then the
    checkout's own virtualenv, because a developer's dependencies live there and
    the ambient interpreter may not have them. Then the windowless twin of
    whatever is currently running, which is the case that carries an installed
    copy. Then the running interpreter itself, accepting a console flash as the
    price of a job that runs at all.

    Every step after the first is guarded by exists(), so the entry naming a path
    that only exists in a checkout is a preference rather than a requirement —
    worth saying because it reads like a hardcoded dependency on a directory an
    install does not have.
    """
    # The planned packaging ships a real interpreter and never reaches this
    # branch. It is here so that changing that decision is one edit rather than a
    # hunt through the scheduler for an assumption nobody wrote down.
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable)), ""

    module = "-m arelis"
    venv = INSTALL_PARENT / ".venv" / "Scripts" / "pythonw.exe"
    if venv.exists():
        return str(venv), module
    interpreter = Path(sys.executable)
    windowless = interpreter.with_name("pythonw.exe")
    if windowless.exists():
        return str(windowless), module
    return str(interpreter), module


def working_directory() -> Path:
    """Where Task Scheduler should start the job process.

    The data root, not the install directory. Task Scheduler refuses to start an
    action whose working directory is missing, and reports that as 0x8007010B with
    no mention of which path it meant — so pointing this at a directory an update
    replaces is a way to produce a job that ran for months and then stopped for
    reasons nobody can read. The data root is the one directory that definitely
    exists and is definitely writable, because it is where the job's own output is
    going anyway.

    Created on demand for the same reason: the first scheduled run may happen
    before anything else has needed the directory.
    """
    return ensure(user_data_dir())


def build_task_xml(job: Job, *, command: str = "", now: date | None = None) -> str:
    """Task Scheduler 1.2 XML for one job.

    One trigger per time of day, so "8am and 6pm" is a single task with two
    triggers rather than two tasks that could drift apart.
    """
    resolved, prefix = runner_command()
    executable = command or resolved
    # "-m arelis --run-job news" for an interpreter, "--run-job news" for a build
    # that is Arelis itself. Assembled rather than hardcoded so the two cases
    # cannot drift apart.
    arguments = f"{prefix} --run-job {escape(job.id)}".strip()
    today = now or date.today()
    enabled = "true" if job.enabled else "false"
    triggers = "\n".join(_trigger(job, when, today, enabled) for when in job.times)
    # A one-off cleans itself out of Task Scheduler once it has fired and its
    # end boundary has passed. Without this the tree fills with spent reminders.
    expiry = (
        "    <DeleteExpiredTaskAfter>PT10M</DeleteExpiredTaskAfter>\n" if job.one_off else ""
    )

    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Author>Arelis</Author>
    <Description>{escape(job.name)} — {escape(job.schedule_text())}</Description>
  </RegistrationInfo>
  <Triggers>
{triggers}
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
{expiry}    <Enabled>{enabled}</Enabled>
    <Hidden>false</Hidden>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(executable)}</Command>
      <Arguments>{arguments}</Arguments>
      <WorkingDirectory>{escape(str(working_directory()))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _trigger(job: Job, when: str, today: date, enabled: str) -> str:
    """One trigger for one time of day, in whichever recurrence the job uses."""
    hour, minute = when.split(":")
    start_day = job.date if job.one_off else today.isoformat()
    start = f"{start_day}T{hour}:{minute}:00"
    repetition = _repetition(job.every_minutes)

    if job.one_off:
        # TimeTrigger fires once and never again. The end boundary is what makes
        # DeleteExpiredTaskAfter apply, so the task removes itself afterwards.
        end = f"{start_day}T{hour}:{minute}:59"
        return (
            "    <TimeTrigger>\n"
            f"      <StartBoundary>{start}</StartBoundary>\n"
            f"      <EndBoundary>{end}</EndBoundary>\n"
            f"{repetition}"
            f"      <Enabled>{enabled}</Enabled>\n"
            "    </TimeTrigger>"
        )

    if job.repeat == "monthly":
        days = "".join(f"          <Day>{d}</Day>\n" for d in job.days_of_month)
        months = "".join(f"          <{m.capitalize()}/>\n" for m in MONTH_NAMES)
        recurrence = (
            "      <ScheduleByMonth>\n"
            "        <DaysOfMonth>\n"
            f"{days}"
            "        </DaysOfMonth>\n"
            "        <Months>\n"
            f"{months}"
            "        </Months>\n"
            "      </ScheduleByMonth>"
        )
    elif len(job.days) == 7:
        recurrence = (
            "      <ScheduleByDay>\n"
            "        <DaysInterval>1</DaysInterval>\n"
            "      </ScheduleByDay>"
        )
    else:
        chosen = "".join(f"          <{d.capitalize()}/>\n" for d in job.days)
        recurrence = (
            "      <ScheduleByWeek>\n"
            "        <DaysOfWeek>\n"
            f"{chosen}"
            "        </DaysOfWeek>\n"
            "        <WeeksInterval>1</WeeksInterval>\n"
            "      </ScheduleByWeek>"
        )

    return (
        "    <CalendarTrigger>\n"
        f"      <StartBoundary>{start}</StartBoundary>\n"
        f"{repetition}"
        f"      <Enabled>{enabled}</Enabled>\n"
        f"{recurrence}\n"
        "    </CalendarTrigger>"
    )


def _repetition(every_minutes: int) -> str:
    """Repeat within the day, for "every two hours" and friends."""
    if not every_minutes:
        return ""
    return (
        "      <Repetition>\n"
        f"        <Interval>PT{every_minutes}M</Interval>\n"
        "        <Duration>P1D</Duration>\n"
        "        <StopAtDurationEnd>true</StopAtDurationEnd>\n"
        "      </Repetition>\n"
    )


def register(job: Job) -> str:
    """Create or replace the scheduled task for a job."""
    _require_windows()
    xml = build_task_xml(job)
    # UTF-16 to match the declaration. schtasks reads the encoding from the
    # header and rejects the file outright when the two disagree.
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".xml", encoding="utf-16", delete=False, newline="\r\n"
    )
    try:
        handle.write(xml)
        handle.close()
        _schtasks("/Create", "/TN", task_name(job.id), "/XML", handle.name, "/F")
    finally:
        Path(handle.name).unlink(missing_ok=True)
    return task_name(job.id)


def unregister(job_id: str) -> bool:
    """Remove the task. Missing is success: the desired end state is reached."""
    if not supported():
        return False
    try:
        _schtasks("/Delete", "/TN", task_name(job_id), "/F")
    except ScheduleError as exc:
        if "cannot find" in str(exc).lower() or "does not exist" in str(exc).lower():
            return False
        raise
    return True


def run_now(job_id: str) -> None:
    _require_windows()
    _schtasks("/Run", "/TN", task_name(job_id))


def runner_record_path() -> Path:
    """Where the command line these tasks were registered with is remembered."""
    return state_dir() / "schedule-runner.json"


def repoint_tasks_if_runner_moved(jobs: Iterable[Job]) -> list[str]:
    """Re-register jobs when the command that runs them is no longer the one in
    Task Scheduler. Returns the ids that were repointed.

    A task holds an absolute path, frozen at the moment it was created. Everything
    that changes how Arelis is launched therefore strands every existing task:
    installing a packaged build after running from a checkout, moving the checkout,
    rebuilding the virtualenv, upgrading the interpreter. The task keeps its old
    command and either fails or, worse, quietly runs a copy of Arelis the user
    stopped using — and nobody is watching at 7am either way.

    The check is a file read rather than a query, deliberately. Asking Task
    Scheduler what it holds means one subprocess per job, each able to take
    seconds, on a path that runs at every launch; recording what we registered
    with costs one small file. The record living under the data root also means a
    move to a *different* root reads as no record at all, which is exactly right,
    because that move is the migration this most needs to survive.

    Absent Windows there is nothing registered to repoint, so this is a no-op
    rather than an error.
    """
    if not supported():
        return []
    executable, arguments = runner_command()
    current = {"command": executable, "arguments": arguments}
    record = runner_record_path()

    previous: dict[str, str] | None = None
    try:
        previous = json.loads(record.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = None

    if isinstance(previous, dict) and _same_runner(previous, current):
        return []

    repointed: list[str] = []
    failed = False
    for job in jobs:
        if not job.enabled:
            continue
        try:
            register(job)
            repointed.append(job.id)
        except ScheduleError as exc:
            # One bad job must not stop the rest being repaired, and must not let
            # the record be written, or the retry never happens.
            failed = True
            log.warning("Could not repoint scheduled job %s: %s", job.id, exc)

    if not failed:
        try:
            ensure(record.parent)
            record.write_text(json.dumps(current, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not record the scheduled-job runner: %s", exc)
    if repointed:
        log.info("Repointed %d scheduled job(s) at %s", len(repointed), executable)
    return repointed


def repoint_moved_tasks_on_launch() -> list[str]:
    """The launch-path entry point: load the saved jobs and repoint if needed.

    Wrapped in a bare except on purpose. This runs before the window is on screen,
    it is a repair rather than something the user asked for, and there is no
    version of "the scheduler bookkeeping went wrong" that should stop Arelis
    starting. It logs and gets out of the way.
    """
    try:
        return repoint_tasks_if_runner_moved(load_jobs())
    except Exception as exc:
        log.warning("Skipped the scheduled-job runner check: %s", exc)
        return []


def _same_runner(previous: dict[str, str], current: dict[str, str]) -> bool:
    """Compare command lines the way Windows compares paths: case-insensitively."""
    return os.path.normcase(str(previous.get("command", ""))) == os.path.normcase(
        current["command"]
    ) and str(previous.get("arguments", "")) == current["arguments"]


def registered_ids() -> set[str]:
    """Which jobs actually have a task, so drift from jobs.yaml is visible."""
    if not supported():
        return set()
    try:
        output = _schtasks("/Query", "/FO", "LIST")
    except ScheduleError:
        return set()
    prefix = f"\\{TASK_FOLDER}\\"
    found: set[str] = set()
    for line in output.splitlines():
        if not line.lower().startswith("taskname:"):
            continue
        name = line.split(":", 1)[1].strip()
        if name.startswith(prefix):
            found.add(name[len(prefix) :])
    return found


def remove_all_tasks() -> list[str]:
    """Delete every task Arelis registered, and never raise while doing it.

    For uninstall. A scheduled task holds an absolute path to the program, so removing
    the program without removing the tasks leaves Windows waking up on a timer forever
    to run something that is not there. It fails silently -- a scheduled task that
    cannot start shows nobody anything -- and it survives reinstalling somewhere else,
    because the stale task is still registered under the same name and the repointing in
    repoint_tasks_if_runner_moved only ever considers jobs that are still in jobs.yaml.

    Read from Task Scheduler rather than from jobs.yaml, because by uninstall time the
    configuration may be edited, moved or already gone, and what has to be cleaned up is
    what is actually registered.

    Errors are swallowed on purpose. This runs from an uninstaller, where the useful
    outcome is that the uninstall finishes; a task that could not be deleted is worth
    less than a user stuck with a half-removed program and a dialog they cannot action.
    """
    removed: list[str] = []
    try:
        ids = registered_ids()
    except Exception:
        return removed
    for job_id in sorted(ids):
        try:
            if unregister(job_id):
                removed.append(job_id)
        except Exception:
            log.warning("could not remove scheduled task for %s", job_id, exc_info=True)
    return removed


def _require_windows() -> None:
    if not supported():
        raise ScheduleError(
            "Scheduling uses Windows Task Scheduler and this is not Windows. "
            "The job is saved and can still be run with `arelis --run-job`."
        )


def _schtasks(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["schtasks", *args],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        raise ScheduleError("schtasks.exe was not found on this machine.")
    except subprocess.TimeoutExpired:
        raise ScheduleError("schtasks did not respond within 30 seconds.")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise ScheduleError(detail or f"schtasks exited {completed.returncode}")
    return completed.stdout or ""


__all__ = [
    "DAY_NAMES",
    "ScheduleError",
    "build_task_xml",
    "register",
    "registered_ids",
    "repoint_moved_tasks_on_launch",
    "repoint_tasks_if_runner_moved",
    "run_now",
    "runner_command",
    "runner_record_path",
    "supported",
    "task_name",
    "unregister",
    "working_directory",
]
