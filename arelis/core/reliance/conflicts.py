"""Warn when a new agenda block lands on time that is already taken.

Exact same-title duplicates are the caller's job. This only reports a
different event whose half-open window intersects the one being added.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

_DATE_ONLY = 10


@dataclass(frozen=True)
class Overlap:
    summary: str
    starts_at: str  # iso
    ends_at: str


def find_overlaps(
    *,
    start: datetime,
    end: datetime | None,
    events: list[dict],
    ignore_summary: str | None = None,
) -> list[Overlap]:
    """Events that intersect ``[start, end)``.

    A missing ``end`` is ``start + 1 hour``. An event with no ``ends_at``
    lasts one hour, unless it is all-day (``all_day`` or a date-only
    ``starts_at``), in which case it covers that calendar date. Touching
    at an endpoint is not a conflict. ``ignore_summary`` drops a
    case-insensitive exact title. Unparseable rows are skipped. Results
    are chronological by start.
    """
    window_end = end if end is not None else start + timedelta(hours=1)
    ignored = (
        ignore_summary.strip().casefold() if ignore_summary is not None else None
    )
    found: list[tuple[datetime, int, Overlap]] = []
    for index, raw in enumerate(events):
        if not isinstance(raw, dict):
            continue
        summary = str(raw.get("summary") or "").strip()
        if ignored is not None and summary.casefold() == ignored:
            continue
        span = _event_span(raw, start)
        if span is None:
            continue
        ev_start, ev_end, start_iso, end_iso = span
        if start < ev_end and ev_start < window_end:
            found.append(
                (
                    ev_start,
                    index,
                    Overlap(summary=summary, starts_at=start_iso, ends_at=end_iso),
                )
            )
    found.sort(key=lambda row: (row[0], row[1]))
    return [item for _, _, item in found]


def overlap_line(overlaps: list[Overlap]) -> str:
    """Empty string if none. Otherwise one sentence a person can hear."""
    if not overlaps:
        return ""
    bits = [_heard(hit) for hit in overlaps]
    if len(bits) == 1:
        return f"You already have {bits[0]}."
    if len(bits) == 2:
        return f"You already have {bits[0]} and {bits[1]}."
    return f"You already have {', '.join(bits[:-1])}, and {bits[-1]}."


def _heard(hit: Overlap) -> str:
    name = hit.summary or "an untitled event"
    start = _parse_clock(hit.starts_at)
    end = _parse_clock(hit.ends_at)
    if start is None or end is None:
        return name
    if _covers_whole_days(start, end):
        return f"{name} all day"
    return f"{name} from {_clock(start)} to {_clock(end)}"


def _covers_whole_days(start: datetime, end: datetime) -> bool:
    span = end - start
    return (
        start.time() == time.min
        and end.time() == time.min
        and span >= timedelta(days=1)
        and span.seconds == 0
    )


def _clock(moment: datetime) -> str:
    hour = moment.hour % 12 or 12
    suffix = "AM" if moment.hour < 12 else "PM"
    return f"{hour}:{moment.minute:02d} {suffix}"


def _event_span(
    raw: dict,
    ref: datetime,
) -> tuple[datetime, datetime, str, str] | None:
    start_text = _text(raw.get("starts_at"))
    if not start_text:
        return None
    end_text = _text(raw.get("ends_at"))
    all_day = _is_all_day(raw.get("all_day")) or _is_date_only(start_text)
    if all_day:
        return _all_day_span(start_text, end_text, ref)
    start_at = _parse_clock(start_text)
    if start_at is None:
        return None
    if end_text:
        end_at = _parse_clock(end_text)
        if end_at is None:
            return None
        if end_at <= start_at:
            end_at = start_at + timedelta(hours=1)
    else:
        end_at = start_at + timedelta(hours=1)
    compared_start = _align(start_at, ref)
    compared_end = _align(end_at, ref)
    return compared_start, compared_end, start_at.isoformat(), end_at.isoformat()


def _all_day_span(
    start_text: str,
    end_text: str,
    ref: datetime,
) -> tuple[datetime, datetime, str, str] | None:
    start_day = _calendar_day(start_text)
    if start_day is None:
        return None
    if end_text:
        end_day = _exclusive_day(end_text, start_day)
        if end_day is None:
            return None
    else:
        end_day = start_day + timedelta(days=1)
    start_at = _midnight(start_day, ref)
    end_at = _midnight(end_day, ref)
    return start_at, end_at, start_at.isoformat(), end_at.isoformat()


def _exclusive_day(end_text: str, start_day: date) -> date | None:
    if _is_date_only(end_text):
        try:
            end_day = date.fromisoformat(end_text)
        except ValueError:
            return None
    else:
        parsed = _parse_clock(end_text)
        if parsed is None:
            return None
        end_day = parsed.date()
        if parsed.time() != time.min:
            end_day += timedelta(days=1)
    if end_day <= start_day:
        return start_day + timedelta(days=1)
    return end_day


def _calendar_day(text: str) -> date | None:
    if _is_date_only(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    parsed = _parse_clock(text)
    if parsed is None:
        return None
    return parsed.date()


def _midnight(day: date, ref: datetime) -> datetime:
    if ref.tzinfo is None:
        return datetime(day.year, day.month, day.day)
    return datetime(day.year, day.month, day.day, tzinfo=ref.tzinfo)


def _align(moment: datetime, ref: datetime) -> datetime:
    """Compare in ``ref``'s zone. Does not consult the host timezone."""
    if ref.tzinfo is None:
        if moment.tzinfo is None:
            return moment
        return moment.replace(tzinfo=None)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=ref.tzinfo)
    return moment.astimezone(ref.tzinfo)


def _parse_clock(text: str) -> datetime | None:
    if _is_date_only(text):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _text(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return ""
    return str(value).strip()


def _is_date_only(text: str) -> bool:
    if len(text) != _DATE_ONLY or text[4] != "-" or text[7] != "-":
        return False
    return text[:4].isdigit() and text[5:7].isdigit() and text[8:].isdigit()


def _is_all_day(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)
