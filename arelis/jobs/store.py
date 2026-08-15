"""Saved jobs: a prompt, a time, and where to mail the answer.

Stored as YAML under data/ for the same reasons the location cache is. There
are a handful of these, they want to be readable and hand-editable when
something goes wrong at 7am, and the repo has no database layer to reuse.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from arelis.paths import state_dir

log = logging.getLogger(__name__)

JOBS_PATH = state_dir() / "jobs.yaml"

DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_WEEKDAYS = DAY_NAMES[:5]
_WEEKENDS = DAY_NAMES[5:]

MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)

# How a job recurs. Every mode can also carry every_minutes, which repeats it
# within the day, so "every two hours on weekdays" is weekly plus a repetition
# rather than a fourth mode.
REPEAT_MODES = ("once", "weekly", "monthly")

_TIME_24 = re.compile(r"^(\d{1,2}):(\d{2})$")
_TIME_12 = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?$", re.IGNORECASE)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?$")
_IN_N = re.compile(r"^in\s+(\d+)\s*(day|days|week|weeks)$")
_MONTH_DAY = re.compile(r"^([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?$")
_DAY_MONTH = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,9})\.?$")
_EVERY = re.compile(r"^(?:every\s+)?(?:(\d+)\s*)?(minute|minutes|min|hour|hours|hr|hrs)$")
_SLUG = re.compile(r"[^a-z0-9]+")


class JobError(ValueError):
    """A job could not be built from what the caller supplied."""


@dataclass
class Job:
    """One saved prompt and when it should run.

    The shape of the schedule is carried by `repeat` plus whichever fields that
    mode uses, rather than by a cron string. Cron would be one field instead of
    four, but nothing about it survives being read back by a person at 7am, and
    the model would have to generate it.
    """

    id: str
    name: str
    prompt: str
    recipient: str = ""
    role: str = "research"
    repeat: str = "weekly"
    # One or more HH:MM. Two entries is "twice a day".
    times: list[str] = field(default_factory=lambda: ["19:00"])
    # repeat=weekly
    days: list[str] = field(default_factory=lambda: list(DAY_NAMES))
    # repeat=once: the single YYYY-MM-DD it fires on, then deletes itself.
    date: str = ""
    # repeat=monthly
    days_of_month: list[int] = field(default_factory=list)
    # Optional for any mode: repeat within the day, e.g. 120 for every 2 hours.
    every_minutes: int = 0
    enabled: bool = True
    last_run: str = ""
    last_status: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def one_off(self) -> bool:
        return self.repeat == "once"

    def schedule_text(self) -> str:
        at = describe_times(self.times)
        if self.every_minutes:
            span = describe_interval(self.every_minutes)
            if self.repeat == "once":
                return f"{describe_date(self.date)}, {span} from {at}"
            return f"{describe_days(self.days)}, {span} from {at}"
        if self.repeat == "once":
            return f"once on {describe_date(self.date)} at {at}"
        if self.repeat == "monthly":
            return f"{describe_days_of_month(self.days_of_month)} at {at}"
        return f"{describe_days(self.days)} at {at}"

    def describe(self) -> str:
        state = "" if self.enabled else "  (disabled)"
        lines = [f"[{self.id}] {self.name}{state}", f"      {self.schedule_text()}"]
        if self.recipient:
            lines.append(f"      to {self.recipient}")
        if self.last_run:
            lines.append(f"      last run {self.last_run}: {self.last_status or 'unknown'}")
        return "\n".join(lines)


def load_jobs(path: Path | None = None) -> list[Job]:
    path = path or JOBS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return []
    except (OSError, yaml.YAMLError) as exc:
        log.warning("Could not read %s: %s", path, exc)
        return []

    entries = raw.get("jobs") if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        return []
    jobs: list[Job] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        # A job with a corrupt field is skipped rather than crashing the load.
        # One bad entry must not take the other schedules down with it.
        try:
            jobs.append(_job_from_dict(entry))
        except (JobError, KeyError, TypeError, ValueError) as exc:
            log.warning("Skipping malformed job %r: %s", entry.get("id"), exc)
    return jobs


def _job_from_dict(entry: dict[str, Any]) -> Job:
    # `time` singular is accepted as well as `times`, so a file written by hand
    # the obvious way still loads.
    raw_times = entry.get("times")
    if raw_times is None:
        raw_times = entry.get("time") or "19:00"
    repeat = str(entry.get("repeat") or "weekly").strip().lower()
    if repeat not in REPEAT_MODES:
        raise JobError(f"repeat must be one of {', '.join(REPEAT_MODES)}, not {repeat!r}")
    when = normalize_date(str(entry.get("date") or "")) if repeat == "once" else ""
    if repeat == "once" and not when:
        raise JobError("a one-off job needs a date")
    return Job(
        id=str(entry["id"]).strip(),
        name=str(entry.get("name") or entry["id"]).strip(),
        prompt=str(entry.get("prompt") or "").strip(),
        recipient=str(entry.get("recipient") or "").strip(),
        role=str(entry.get("role") or "research").strip(),
        repeat=repeat,
        times=normalize_times(raw_times),
        days=normalize_days(entry.get("days")),
        date=when,
        days_of_month=normalize_days_of_month(entry.get("days_of_month")),
        every_minutes=normalize_interval(entry.get("every_minutes")),
        enabled=bool(entry.get("enabled", True)),
        last_run=str(entry.get("last_run") or ""),
        last_status=str(entry.get("last_status") or ""),
    )


def save_jobs(jobs: list[Job], path: Path | None = None) -> None:
    path = path or JOBS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"jobs": [job.as_dict() for job in jobs]}
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def get_job(job_id: str, path: Path | None = None) -> Job | None:
    wanted = job_id.strip().lower()
    for job in load_jobs(path):
        if job.id.lower() == wanted:
            return job
    return None


def upsert_job(job: Job, path: Path | None = None) -> None:
    jobs = [j for j in load_jobs(path) if j.id.lower() != job.id.lower()]
    jobs.append(job)
    save_jobs(jobs, path)


def delete_job(job_id: str, path: Path | None = None) -> bool:
    jobs = load_jobs(path)
    remaining = [j for j in jobs if j.id.lower() != job_id.strip().lower()]
    if len(remaining) == len(jobs):
        return False
    save_jobs(remaining, path)
    return True


def record_run(job_id: str, status: str, path: Path | None = None) -> None:
    """Stamp the outcome so a job that quietly stopped working is visible.

    A digest that stops arriving looks exactly like a quiet week, so the last
    result has to be written down somewhere the user can go and look.
    """
    jobs = load_jobs(path)
    for job in jobs:
        if job.id.lower() == job_id.strip().lower():
            job.last_run = datetime.now().strftime("%Y-%m-%d %H:%M")
            job.last_status = status
            save_jobs(jobs, path)
            return


def make_job_id(name: str, existing: list[str]) -> str:
    """A readable, unique slug. It ends up in a Windows task name."""
    base = _SLUG.sub("-", name.strip().lower()).strip("-") or "job"
    base = base[:40]
    taken = {e.lower() for e in existing}
    if base not in taken:
        return base
    for n in range(2, 100):
        candidate = f"{base}-{n}"
        if candidate not in taken:
            return candidate
    raise JobError(f"Could not find a free id for {name!r}")


def normalize_time(value: str) -> str:
    """Accept 19:00, 7pm, 7:30 PM. Always return HH:MM.

    Parsed here rather than in the model. A 7B asked for a cron expression will
    eventually produce a wrong one, and a wrong schedule fails silently at 3am
    instead of loudly at the prompt.
    """
    text = value.strip()
    match = _TIME_24.match(text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
    else:
        match = _TIME_12.match(text)
        if not match:
            raise JobError(f"Could not read {value!r} as a time. Use 19:00 or 7pm.")
        hour = int(match.group(1)) % 12
        minute = int(match.group(2) or 0)
        if match.group(3).lower() == "p":
            hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise JobError(f"{value!r} is not a real time of day.")
    return f"{hour:02d}:{minute:02d}"


def normalize_times(value: Any) -> list[str]:
    """One or more times of day, in order, deduplicated.

    Two entries is what "twice a day" means. Accepting a list here rather than
    forcing a second job is the difference between "email me at 8 and 6"
    working and her silently picking one of the two.
    """
    if value is None or value == "":
        raise JobError("No time of day was given.")
    parts = value if isinstance(value, list) else str(value).replace(" and ", ",").split(",")
    times: list[str] = []
    for part in parts:
        text = str(part).strip()
        if not text:
            continue
        when = normalize_time(text)
        if when not in times:
            times.append(when)
    if not times:
        raise JobError("No time of day was given.")
    return sorted(times)


def normalize_date(value: str, *, today: date | None = None) -> str:
    """Resolve a date to YYYY-MM-DD, relative words included.

    Done here rather than by the model for a specific reason: the model is told
    it does not know today's date, and it genuinely does not. Asking it to turn
    "tomorrow" into a date would get a confident guess at the wrong day, and a
    one-off reminder that fires on the wrong day is worse than one that fails.
    """
    text = value.strip().lower().rstrip(",")
    if not text:
        return ""
    now = today or date.today()

    match = _ISO_DATE.match(text)
    if match:
        return _build_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))

    if text in {"today", "tonight"}:
        return now.isoformat()
    if text == "tomorrow":
        return (now + timedelta(days=1)).isoformat()
    if text in {"day after tomorrow", "the day after tomorrow", "overmorrow"}:
        return (now + timedelta(days=2)).isoformat()

    match = _IN_N.match(text)
    if match:
        count = int(match.group(1))
        step = 7 if match.group(2).startswith("week") else 1
        return (now + timedelta(days=count * step)).isoformat()

    weekday = _weekday_index(text.removeprefix("next ").removeprefix("this ").strip())
    if weekday is not None:
        # "monday" means the next one, never today: someone saying it on a
        # Monday morning about an evening job is the rarer reading.
        ahead = (weekday - now.weekday()) % 7 or 7
        return (now + timedelta(days=ahead)).isoformat()

    match = _MONTH_DAY.match(text) or _DAY_MONTH.match(text)
    if match:
        first, second = match.group(1), match.group(2)
        month_text, day_text = (first, second) if first.isalpha() else (second, first)
        month = _month_index(month_text)
        if month is not None:
            return _roll_forward(now, month, int(day_text))

    match = _NUMERIC_DATE.match(text)
    if match:
        month, day = int(match.group(1)), int(match.group(2))
        raw_year = match.group(3)
        if raw_year:
            year = int(raw_year)
            year += 2000 if year < 100 else 0
            return _build_date(year, month, day)
        return _roll_forward(now, month, day)

    raise JobError(
        f"Could not read {value!r} as a date. Use 2026-08-15, tomorrow, "
        "in 3 days, next Friday, or Aug 15."
    )


def normalize_days_of_month(value: Any) -> list[int]:
    """Days of the month for a monthly job. 31 is allowed; short months skip it."""
    if value is None or value == "":
        return []
    parts = value if isinstance(value, list) else str(value).replace(" and ", ",").split(",")
    days: list[int] = []
    for part in parts:
        text = str(part).strip().lower()
        if not text:
            continue
        if text in {"last", "end", "eom"}:
            raise JobError(
                "'last day of the month' is not supported; name a number. "
                "28 fires in every month."
            )
        # 1st, 22nd, 3rd, 4th. A character set rather than a suffix list
        # because only those six letters can appear here.
        text = text.rstrip("stndrh")
        try:
            number = int(text)
        except ValueError:
            raise JobError(f"{part!r} is not a day of the month.") from None
        if not 1 <= number <= 31:
            raise JobError(f"{number} is not a day of the month.")
        if number not in days:
            days.append(number)
    return sorted(days)


def normalize_interval(value: Any) -> int:
    """Minutes between repeats within a day. 0 means it runs once per trigger."""
    if value is None or value == "":
        return 0
    if isinstance(value, int):
        minutes = value
    else:
        text = str(value).strip().lower()
        if not text or text in {"0", "none", "no"}:
            return 0
        match = _EVERY.match(text)
        if not match:
            try:
                minutes = int(text)
            except ValueError:
                raise JobError(
                    f"Could not read {value!r} as an interval. Use '2 hours' or '30 minutes'."
                ) from None
        else:
            count = int(match.group(1) or 1)
            minutes = count * 60 if match.group(2).startswith(("hour", "hr")) else count
    if minutes == 0:
        return 0
    # Task Scheduler will not accept a repetition under a minute, and anything
    # under a quarter hour would mean a model call every few minutes all day.
    if minutes < 15:
        raise JobError("The shortest interval is 15 minutes.")
    if minutes > 12 * 60:
        raise JobError("For anything over 12 hours, use a daily or weekly schedule.")
    return minutes


def normalize_days(value: Any) -> list[str]:
    """Accept daily, weekdays, weekends, or a list or comma-separated names."""
    if value is None or value == "":
        return list(DAY_NAMES)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"daily", "every day", "everyday", "all"}:
            return list(DAY_NAMES)
        if text in {"weekdays", "weekday"}:
            return list(_WEEKDAYS)
        if text in {"weekends", "weekend"}:
            return list(_WEEKENDS)
        parts = [p.strip() for p in text.replace(" and ", ",").split(",")]
    elif isinstance(value, list):
        parts = [str(p).strip().lower() for p in value]
    else:
        raise JobError(f"Could not read {value!r} as days of the week.")

    days: list[str] = []
    for part in parts:
        if not part:
            continue
        match = [d for d in DAY_NAMES if d.startswith(part[:3])]
        if not match:
            raise JobError(f"{part!r} is not a day of the week.")
        if match[0] not in days:
            days.append(match[0])
    if not days:
        raise JobError("No days of the week were given.")
    return sorted(days, key=DAY_NAMES.index)


def describe_days(days: list[str]) -> str:
    if len(days) == 7:
        return "every day"
    if days == list(_WEEKDAYS):
        return "weekdays"
    if days == list(_WEEKENDS):
        return "weekends"
    return ", ".join(d.capitalize() for d in days)


def describe_times(times: list[str]) -> str:
    if not times:
        return "(no time)"
    if len(times) == 1:
        return times[0]
    return f"{', '.join(times[:-1])} and {times[-1]}"


def describe_days_of_month(days: list[int]) -> str:
    if not days:
        return "monthly"
    return "the " + ", ".join(_ordinal(d) for d in days) + " of each month"


def describe_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return value or "(no date)"
    return parsed.strftime("%A %d %B %Y").replace(" 0", " ")


def describe_interval(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return "every hour" if hours == 1 else f"every {hours} hours"
    return f"every {minutes} minutes"


def _ordinal(number: int) -> str:
    if 11 <= number % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _weekday_index(text: str) -> int | None:
    if len(text) < 3:
        return None
    for index, name in enumerate(DAY_NAMES):
        if name.startswith(text[:3]) and name.startswith(text):
            return index
    return None


def _month_index(text: str) -> int | None:
    if len(text) < 3:
        return None
    for index, name in enumerate(MONTH_NAMES):
        if name.startswith(text):
            return index + 1
    return None


def _build_date(year: int, month: int, day: int) -> str:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        raise JobError(f"{year}-{month:02d}-{day:02d} is not a real date.") from None


def _roll_forward(today: date, month: int, day: int) -> str:
    """A bare month and day means the next one, not one in the past.

    "Email me on the 3rd" said on the 10th means next month, and a task
    registered with a start date behind it would fire immediately.
    """
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue
        if candidate >= today:
            return candidate.isoformat()
    raise JobError(f"Could not place {month}/{day} on the calendar.")
