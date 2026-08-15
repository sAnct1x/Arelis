"""Minimal local ICS agenda for morning briefings.

Stdlib only: enough DTSTART / SUMMARY parsing for a hand-maintained
`data/calendar.ics`. No Google OAuth in this pass.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from arelis.paths import user_data_dir

log = logging.getLogger(__name__)

_DT_KEY = re.compile(r"^DTSTART([^:]*):(.*)$", re.IGNORECASE)
_SUMMARY_KEY = re.compile(r"^SUMMARY[^:]*:(.*)$", re.IGNORECASE)
_LOCATION_KEY = re.compile(r"^LOCATION[^:]*:(.*)$", re.IGNORECASE)
_DESC_KEY = re.compile(r"^DESCRIPTION[^:]*:(.*)$", re.IGNORECASE)


@dataclass(frozen=True)
class CalendarEvent:
    starts_at: datetime
    summary: str
    all_day: bool = False
    location: str = ""
    description: str = ""
    event_id: str = ""

    def day(self, tz: timezone | ZoneInfo) -> date:
        return self.starts_at.astimezone(tz).date()


def resolve_calendar_path(config: dict[str, Any] | None = None) -> Path:
    """Absolute path for `tools.briefing.calendar_path` (default data/calendar.ics)."""
    briefing_cfg = ((config or {}).get("tools") or {}).get("briefing") or {}
    raw_path = str(briefing_cfg.get("calendar_path") or "data/calendar.ics").strip()
    path = Path(raw_path)
    if not path.is_absolute():
        path = user_data_dir() / path
    return path


def load_agenda(
    path: Path | str,
    *,
    now: datetime | None = None,
    days: int = 2,
    start_day: date | None = None,
    end_day: date | None = None,
) -> list[CalendarEvent]:
    """Events in a local date window, sorted by start.

    Default window is today through today+(days-1). Pass ``start_day`` /
    ``end_day`` for an explicit inclusive range (``days`` is ignored when
    ``end_day`` is set).
    """
    file_path = Path(path)
    if not file_path.is_file():
        return []
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.info("Calendar unreadable (%s): %s", file_path, exc)
        return []
    local_now = now or datetime.now().astimezone()
    tz = local_now.tzinfo or UTC
    begin = start_day if start_day is not None else local_now.date()
    if end_day is not None:
        finish = end_day
    else:
        finish = begin + timedelta(days=max(1, days) - 1)
    if finish < begin:
        begin, finish = finish, begin
    events = parse_ics_events(text, default_tz=tz)
    kept = [ev for ev in events if begin <= ev.day(tz) <= finish]
    kept.sort(key=lambda ev: (ev.day(tz), ev.all_day, ev.starts_at, ev.summary.lower()))
    return kept


def parse_ics_events(
    text: str,
    *,
    default_tz: timezone | ZoneInfo | None = None,
) -> list[CalendarEvent]:
    """Parse VEVENT blocks; ignore everything else."""
    tz = default_tz or datetime.now().astimezone().tzinfo or UTC
    events: list[CalendarEvent] = []
    in_event = False
    dtstart_raw = ""
    dtstart_params = ""
    summary = ""
    location = ""
    description = ""
    for raw_line in _unfold_lines(text.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            in_event = True
            dtstart_raw = ""
            dtstart_params = ""
            summary = ""
            location = ""
            description = ""
            continue
        if upper == "END:VEVENT":
            if in_event and dtstart_raw:
                parsed = _parse_dtstart(dtstart_raw, dtstart_params, default_tz=tz)
                if parsed is not None:
                    starts_at, all_day = parsed
                    events.append(
                        CalendarEvent(
                            starts_at=starts_at,
                            summary=summary.strip() or "(no title)",
                            all_day=all_day,
                            location=location.strip(),
                            description=description.strip(),
                        )
                    )
            in_event = False
            continue
        if not in_event:
            continue
        m_dt = _DT_KEY.match(line)
        if m_dt:
            dtstart_params = m_dt.group(1) or ""
            dtstart_raw = (m_dt.group(2) or "").strip()
            continue
        m_sum = _SUMMARY_KEY.match(line)
        if m_sum:
            summary = _unescape_text(m_sum.group(1) or "")
            continue
        m_loc = _LOCATION_KEY.match(line)
        if m_loc:
            location = _unescape_text(m_loc.group(1) or "")
            continue
        m_desc = _DESC_KEY.match(line)
        if m_desc:
            description = _unescape_text(m_desc.group(1) or "")
    return events


def format_agenda_section(
    events: Iterable[CalendarEvent],
    *,
    now: datetime | None = None,
) -> str:
    """Markdown for the briefing agenda section."""
    local_now = now or datetime.now().astimezone()
    tz = local_now.tzinfo or UTC
    today = local_now.date()
    tomorrow = today + timedelta(days=1)
    by_day: dict[date, list[CalendarEvent]] = {}
    for ev in events:
        by_day.setdefault(ev.day(tz), []).append(ev)
    if not by_day:
        return "No events in this window."
    lines: list[str] = []
    for day in sorted(by_day):
        if day == today:
            label = "Today"
        elif day == tomorrow:
            label = "Tomorrow"
        else:
            label = day.strftime("%A %d %B").replace(" 0", " ")
        lines.append(f"**{label}**")
        for ev in by_day[day]:
            if ev.all_day:
                when = "all day"
            else:
                when = (
                    ev.starts_at.astimezone(tz)
                    .strftime("%I:%M %p")
                    .lstrip("0")
                )
            lines.append(f"- {when} — {ev.summary}")
            loc = (ev.location or "").strip()
            if loc:
                lines.append(f"  {loc}")
            note = (ev.description or "").replace("\n", " ").strip()
            if note and note.casefold() not in (ev.summary or "").casefold():
                if len(note) > 160:
                    note = note[:157].rstrip() + "…"
                lines.append(f"  {note}")
    return "\n".join(lines)


def _unfold_lines(lines: Iterable[str]) -> list[str]:
    """Join RFC 5545 folded lines (leading space/tab continuation)."""
    out: list[str] = []
    for line in lines:
        if out and line.startswith((" ", "\t")):
            out[-1] += line[1:]
        else:
            out.append(line.rstrip("\r\n"))
    return out


def _unescape_text(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _parse_dtstart(
    value: str,
    params: str,
    *,
    default_tz: timezone | ZoneInfo,
) -> tuple[datetime, bool] | None:
    raw = (value or "").strip()
    if not raw:
        return None
    params_u = (params or "").upper()
    all_day = "VALUE=DATE" in params_u or (len(raw) == 8 and "T" not in raw.upper())
    tz = default_tz
    tzid_m = re.search(r"TZID=([^;:]+)", params or "", re.IGNORECASE)
    if tzid_m:
        try:
            tz = ZoneInfo(tzid_m.group(1).strip())
        except Exception:
            tz = default_tz
    try:
        if all_day:
            day = datetime.strptime(raw[:8], "%Y%m%d").date()
            return datetime(day.year, day.month, day.day, tzinfo=tz), True
        if raw.endswith("Z"):
            dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
            return dt, False
        if "T" in raw:
            body = raw.split(".")[0]
            dt = datetime.strptime(body, "%Y%m%dT%H%M%S").replace(tzinfo=tz)
            return dt, False
    except ValueError:
        log.debug("Skipping unparseable DTSTART %r", raw)
        return None
    return None
