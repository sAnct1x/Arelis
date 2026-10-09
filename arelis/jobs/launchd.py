"""Register jobs with launchd on Mac.

Each job is a LaunchAgent under ~/Library/LaunchAgents. The label is
app.arelis.job.<id>. Tests point ARELIS_LAUNCH_AGENTS at a temp folder and
mock launchctl, so nothing here should touch a real home Library during a run.
"""

from __future__ import annotations

import logging
import os
import plistlib
import re
import subprocess
from pathlib import Path

from arelis.hidden_proc import hidden_run
from arelis.jobs.schedule import ScheduleError
from arelis.jobs.store import Job

log = logging.getLogger(__name__)

LABEL_PREFIX = "app.arelis."
JOB_PREFIX = "app.arelis.job."
_TIMEOUT_S = 30
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
_WEEKDAY = {
    "monday": 1,
    "tuesday": 2,
    "wednesday": 3,
    "thursday": 4,
    "friday": 5,
    "saturday": 6,
    "sunday": 0,
}


def agents_dir() -> Path:
    override = os.environ.get("ARELIS_LAUNCH_AGENTS", "").strip()
    if override:
        return Path(override)
    return Path.home() / "Library" / "LaunchAgents"


def gui_domain() -> str:
    getuid = getattr(os, "getuid", None)
    uid = int(getuid()) if getuid is not None else 0
    return f"gui/{uid}"


def job_label(job_id: str) -> str:
    safe = _SAFE.sub("-", job_id.strip()).strip("-.")
    if not safe:
        raise ScheduleError("That job needs a name before it can be scheduled.")
    return f"{JOB_PREFIX}{safe}"


def program_arguments(job_id: str) -> list[str]:
    from arelis.jobs.schedule import runner_command

    executable, prefix = runner_command()
    args = [executable]
    if prefix.strip():
        args.extend(prefix.split())
    args.extend(["--run-job", job_id])
    return args


def calendar_intervals(job: Job) -> list[dict[str, int]]:
    slots = _clock_slots(job.times, job.every_minutes)
    if job.one_off:
        month, day = _month_day(job.date)
        return [
            {"Month": month, "Day": day, "Hour": hour, "Minute": minute}
            for hour, minute in slots
        ]
    if job.repeat == "monthly":
        days = list(job.days_of_month) or [1]
        return [
            {"Day": int(day), "Hour": hour, "Minute": minute}
            for day in days
            for hour, minute in slots
        ]
    names = [name for name in job.days if name in _WEEKDAY]
    every_day = len(set(names)) >= 7
    intervals: list[dict[str, int]] = []
    for hour, minute in slots:
        if every_day:
            intervals.append({"Hour": hour, "Minute": minute})
            continue
        for name in names:
            intervals.append(
                {"Weekday": _WEEKDAY[name], "Hour": hour, "Minute": minute}
            )
    return intervals


def register_job(job: Job) -> str:
    path = _write_job_plist(job)
    if job.enabled:
        _load(path)
    else:
        _unload(path)
    return job_label(job.id)


def unregister_job(job_id: str) -> bool:
    path = _plist_path(job_label(job_id))
    if not path.is_file():
        return False
    _unload(path)
    path.unlink(missing_ok=True)
    return True


def run_job_now(job_id: str) -> None:
    path = _plist_path(job_label(job_id))
    if not path.is_file():
        raise ScheduleError("That scheduled job is not set up on this Mac.")
    target = f"{gui_domain()}/{job_label(job_id)}"
    started = _launchctl("kickstart", "-p", target)
    if started.returncode == 0:
        return
    _load(path)
    again = _launchctl("kickstart", "-p", target)
    if again.returncode != 0:
        raise ScheduleError("Could not run that job right now.")


def registered_job_ids() -> set[str]:
    try:
        completed = _launchctl("list")
    except ScheduleError:
        return set()
    if completed.returncode != 0:
        return set()
    found: set[str] = set()
    for line in (completed.stdout or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        label = parts[-1]
        if label.startswith(JOB_PREFIX):
            found.add(label[len(JOB_PREFIX) :])
    return found


def install_agent(label: str, arguments: list[str], *, run_at_load: bool) -> Path:
    path = _plist_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": label,
        "ProgramArguments": list(arguments),
        "RunAtLoad": bool(run_at_load),
    }
    _dump(path, payload)
    _load(path)
    return path


def remove_agent(label: str) -> bool:
    path = _plist_path(label)
    if not path.is_file():
        return False
    _unload(path)
    path.unlink(missing_ok=True)
    return True


def remove_all_agents() -> list[str]:
    """Remove LaunchAgents whose label starts with app.arelis. Never raises."""
    removed: list[str] = []
    root = agents_dir()
    if not root.is_dir():
        return removed
    for path in sorted(root.glob("*.plist")):
        label = _read_label(path)
        if not label.startswith(LABEL_PREFIX):
            continue
        _unload(path)
        try:
            path.unlink()
        except OSError as exc:
            log.warning("could not remove launch agent %s: %s", label, exc)
            continue
        if label.startswith(JOB_PREFIX):
            removed.append(label[len(JOB_PREFIX) :])
        else:
            removed.append(label)
    return removed


def _write_job_plist(job: Job) -> Path:
    from arelis.jobs.schedule import working_directory

    label = job_label(job.id)
    path = _plist_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": label,
        "ProgramArguments": program_arguments(job.id),
        "WorkingDirectory": str(working_directory()),
        "StartCalendarInterval": calendar_intervals(job),
        "RunAtLoad": False,
    }
    _dump(path, payload)
    return path


def _plist_path(label: str) -> Path:
    return agents_dir() / f"{label}.plist"


def _dump(path: Path, payload: dict) -> None:
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)


def _read_label(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException, ValueError) as exc:
        log.warning("could not read launch agent %s: %s", path.name, exc)
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("Label") or "")


def _clock_slots(times: list[str], every_minutes: int) -> list[tuple[int, int]]:
    slots: list[tuple[int, int]] = []
    step = int(every_minutes or 0)
    for when in times:
        hour_text, minute_text = when.split(":")
        start = int(hour_text) * 60 + int(minute_text)
        if step <= 0:
            slots.append((start // 60, start % 60))
            continue
        cursor = start
        while cursor < 24 * 60:
            slots.append((cursor // 60, cursor % 60))
            cursor += step
    return slots


def _month_day(iso_date: str) -> tuple[int, int]:
    parts = (iso_date or "").split("-")
    if len(parts) != 3:
        raise ScheduleError("That one time job needs a date.")
    try:
        month = int(parts[1])
        day = int(parts[2])
    except ValueError as exc:
        raise ScheduleError("That one time job needs a date.") from exc
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        raise ScheduleError("That one time job needs a date.")
    return month, day


def _load(path: Path) -> None:
    domain = gui_domain()
    first = _launchctl("bootstrap", domain, str(path))
    if first.returncode == 0:
        return
    second = _launchctl("load", "-w", str(path))
    if second.returncode != 0:
        detail = (second.stderr or second.stdout or first.stderr or first.stdout or "").strip()
        raise ScheduleError(detail or "Could not turn on that scheduled job.")


def _unload(path: Path) -> None:
    domain = gui_domain()
    first = _launchctl("bootout", domain, str(path))
    if first.returncode == 0:
        return
    _launchctl("unload", "-w", str(path))


def _launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return hidden_run(
            ["launchctl", *args],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ScheduleError("Could not schedule that job on this Mac.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ScheduleError("Scheduling did not answer in time.") from exc
