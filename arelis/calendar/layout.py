"""Date-grid helpers for the calendar tile. No Qt."""

from __future__ import annotations

from calendar import Calendar
from datetime import date, timedelta
from typing import Any

from arelis.calendar.models import CachedEvent

# Google Calendar (US) leads with Sunday.
WEEK_START_SUNDAY = 6
WEEKDAY_LABELS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def month_cells(
    year: int,
    month: int,
    *,
    week_start: int = WEEK_START_SUNDAY,
) -> list[date]:
    """Exactly 42 cells covering the month, padded with neighbouring days."""
    cal = Calendar(firstweekday=week_start)
    cells: list[date] = []
    for week in cal.monthdatescalendar(year, month):
        cells.extend(week)
    while len(cells) < 42:
        cells.append(cells[-1] + timedelta(days=1))
    return cells[:42]


def week_cells(anchor: date, *, week_start: int = WEEK_START_SUNDAY) -> list[date]:
    """Seven dates for the week containing `anchor`."""
    # Python weekday(): Mon=0 .. Sun=6. Convert to offset from week_start.
    delta = (anchor.weekday() - week_start) % 7
    start = anchor - timedelta(days=delta)
    return [start + timedelta(days=i) for i in range(7)]


def event_spans_day(ev: CachedEvent, day: date) -> bool:
    start = ev.starts_at.date()
    if ev.all_day and ev.ends_at is not None:
        # Google all-day end is exclusive; the parser stores that date as-is.
        end_excl = ev.ends_at.date()
        if end_excl <= start:
            end_excl = start + timedelta(days=1)
        return start <= day < end_excl
    end = (ev.ends_at or ev.starts_at).date()
    return start <= day <= end


def events_on_day(events: list[CachedEvent], day: date) -> list[CachedEvent]:
    hits = [ev for ev in events if event_spans_day(ev, day)]
    hits.sort(key=lambda ev: (not ev.all_day, ev.starts_at, ev.summary.lower()))
    return hits


def parse_task_due(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def tasks_due_on_day(tasks: list[dict[str, Any]], day: date) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in tasks:
        due = parse_task_due(row.get("due"))
        if due == day:
            out.append(row)
    return out


def month_title(anchor: date) -> str:
    return anchor.strftime("%B %Y").lower()


def format_event_time(ev: CachedEvent) -> str:
    if ev.all_day:
        return "all day"
    local = ev.starts_at.astimezone() if ev.starts_at.tzinfo else ev.starts_at
    return local.strftime("%I:%M %p").lstrip("0").replace("  ", " ")
