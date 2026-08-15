"""Registering jobs with Windows Task Scheduler.

Task XML rather than the simple `schtasks /Create /SC DAILY /ST 19:00` form,
because the flags cannot express StartWhenAvailable. Without it a 7pm job on a
machine that was asleep at 7pm is simply skipped, and "it works unless the PC
was off" is not what a daily digest means.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from arelis.config import PROJECT_ROOT
from arelis.jobs.store import DAY_NAMES, MONTH_NAMES, Job

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
    """The executable and arguments Task Scheduler should run.

    pythonw rather than python: the console build flashes a black window on
    screen at 7pm every day, which is exactly the kind of thing that makes
    someone turn a feature off.
    """
    venv = PROJECT_ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if venv.exists():
        return str(venv), ""
    interpreter = Path(sys.executable)
    windowless = interpreter.with_name("pythonw.exe")
    if windowless.exists():
        return str(windowless), ""
    return str(interpreter), ""


def build_task_xml(job: Job, *, command: str = "", now: date | None = None) -> str:
    """Task Scheduler 1.2 XML for one job.

    One trigger per time of day, so "8am and 6pm" is a single task with two
    triggers rather than two tasks that could drift apart.
    """
    executable = command or runner_command()[0]
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
      <Arguments>-m arelis --run-job {escape(job.id)}</Arguments>
      <WorkingDirectory>{escape(str(PROJECT_ROOT))}</WorkingDirectory>
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
    "run_now",
    "runner_command",
    "supported",
    "task_name",
    "unregister",
]
