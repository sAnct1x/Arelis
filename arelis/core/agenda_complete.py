"""Fill agenda create args from the current turn when title+time are known.

Mirrors SMS/email draft locks so the confirm card shows the event the user
asked for, not a model rewrite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from arelis.core.complete_protocol import (
    CREATE_ALLOW_CLOSER,
    unfinished_call_notice,
)
from arelis.history_view import history_pairs
from arelis.jobs.store import JobError, normalize_date, normalize_time

_CREATE = re.compile(
    r"(?i)\b(?:"
    r"add\s+(?:to\s+)?(?:my\s+)?calendar|"
    r"add\s+(?:an?\s+)?(?:calendar\s+)?(?:event|meeting|appointment|reminder)|"
    r"create\s+(?:an?\s+)?(?:calendar\s+)?(?:event|meeting|appointment|reminder)|"
    r"schedule\s+(?:an?\s+)?(?:calendar\s+)?(?:event|meeting|appointment|reminder)|"
    r"put\s+(?:this\s+)?on\s+(?:my\s+)?calendar|"
    r"put\s+.+\s+on\s+(?:my\s+)?calendar|"
    r"add\s+.+\s+to\s+(?:my\s+)?calendar|"
    r"calendar\s+event\s+for|"
    r"set\s+(?:an?\s+)?(?:calendar\s+)?reminder|"
    # Whisper often hears "add an event for" as "at an event for".
    r"at\s+an?\s+event\s+for"
    r")\b"
)

_DELETE = re.compile(
    r"(?i)\b("
    r"(?:delete|remove|cancel|delight|delate)\s+"
    r"(?:that\s+|the\s+|this\s+|my\s+)?"
    r"(?:anniversary\s+)?"
    r"(?:[\w'+\-]+\s+){0,8}"
    r"(?:calendar\s+)?(?:event|meeting|appointment|reminder)s?|"
    r"delete\s+(?:two|three|\d+)\s+of\s+them|"
    r"delete\s+(?:the\s+)?(?:extra|duplicate)s?|"
    r"you created \d+ events"
    r")\b"
)
_GOOGLE_EVENT_ID = re.compile(r"\bgoogle:[A-Za-z0-9_\-.:]+")

_PUT_ON_CALENDAR = re.compile(
    r"(?i)\bput\s+"
    r"(?:['\"](?P<quoted>[^'\"]+)['\"]|(?P<plain>.+?))\s+"
    r"on\s+(?:my\s+)?calendar"
)
_ADD_TO_CALENDAR = re.compile(
    r"(?i)\badd\s+"
    r"(?:['\"](?P<quoted>[^'\"]+)['\"]|(?P<plain>.+?))\s+"
    r"to\s+(?:my\s+)?calendar"
)
# "called X" / "titled X" / "named X" / "about X"
# Stop at a period so "titled Foo. i want this event…" does not eat the rest.
_TITLE = re.compile(
    r"(?i)\b(?:called|titled|named|about)\s+"
    r"[\"']?(?P<title>[^\"'\n,.]{2,80})[\"']?"
)
_TITLE_WHEN = re.compile(
    r"(?i)\s+(?:(?:in\s+)?(?:a|one|two|three|four|\d+)\s+weeks?\s+from|"
    r"i\s+want\s+this\s+event)\b"
)
_DURATION = re.compile(
    r"(?i)\b(?:for|lasting|last(?:s|ing)?\s+for)\s+"
    r"(?:an?\s+|one\s+)?(?:1\s+)?hours?\b"
    r"|\bfor\s+1\s+hour\b"
)
_WORD_WEEKS = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4}

# Reminder phrasing is the title when they did not use called/titled.
_REMINDER_TITLE = re.compile(
    r"(?i)\b(?:(?:to\s+be\s+(?:a\s+)?)?reminder\s+to|remind\s+me\s+to)\s+"
    r"(?P<title>[^.\n]{3,100})"
)

# Rough ISO, relative days, or "August 13th at 7am" / "on Aug 13 at 7:00 am"
_MONTH = (
    r"january|february|march|april|may|june|july|august|september|october|"
    r"november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
_WHEN = re.compile(
    r"(?i)\b(?:"
    r"(?P<iso>\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?)"
    r"|"
    r"(?:on\s+)?(?P<md>(?:"
    + _MONTH
    + r")\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?)"
    r"(?:\s+at\s+(?P<md_time>\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?"
    r"|"
    r"(?P<rel>"
    r"(?:in\s+)?(?P<weeks>a|one|two|three|four|\d+)\s+weeks?\s+from\s+(?:today|now)"
    r"(?:\s+at\s+(?P<weeks_time>\d{1,2}(?::\d{2})?\s*(?:am|pm)?))?"
    r"|"
    r"(?:today|tonight|tomorrow|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|next\s+\w+)"
    r"(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?"
    r"|"
    r"at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)"
    r")"
    r")\b"
)

_MONTH_NUM = {
    "january": 1,
    "jan": 1,
    "february": 2,
    "feb": 2,
    "march": 3,
    "mar": 3,
    "april": 4,
    "apr": 4,
    "may": 5,
    "june": 6,
    "jun": 6,
    "july": 7,
    "jul": 7,
    "august": 8,
    "aug": 8,
    "september": 9,
    "sep": 9,
    "sept": 9,
    "october": 10,
    "oct": 10,
    "november": 11,
    "nov": 11,
    "december": 12,
    "dec": 12,
}

_PROVIDER = re.compile(r"(?i)\b(?:provider\s*=\s*|on\s+)(?P<p>google|outlook)\b")

_REL_AT = re.compile(
    r"(?i)^\s*(?P<day>today|tonight|tomorrow|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday|next\s+\w+)\s+at\s+(?P<time>.+?)\s*$"
)
_BARE_AT = re.compile(r"(?i)^\s*at\s+(?P<time>\d{1,2}(?::\d{2})?\s*(?:am|pm))\s*$")

_EXPLICIT_SMS_VERB = re.compile(
    r"(?i)^\s*(?:text|sms|txt|send\s+(?:a\s+)?(?:text|sms|message))\b"
)

_SPOKEN_HOURS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
}


def normalize_calendar_speech(text: str) -> str:
    """Fold common calendar ASR splits ('to morrow', 'eleven a m')."""
    raw = (text or "").strip()
    if not raw:
        return raw
    raw = re.sub(r"(?i)\bto[\s-]+morrow\b", "tomorrow", raw)
    raw = re.sub(r"(?i)\bto[\s-]+night\b", "tonight", raw)
    raw = re.sub(r"(?i)\b([ap])(?:\s*\.?\s*|\s+)m\.?\b", r"\1m", raw)

    def _hour(match: re.Match[str]) -> str:
        word = (match.group("h") or "").lower()
        digit = match.group("d")
        ap = (match.group("ap") or "").lower()
        n = digit or _SPOKEN_HOURS.get(word) or word
        return f"{n}{ap}"

    return re.sub(
        r"(?i)\b(?:(?P<h>one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve)|(?P<d>\d{1,2}))\s+(?P<ap>am|pm)\b",
        _hour,
        raw,
    )


_SEND_CONFIRM = re.compile(
    r"(?i)^\s*("
    r"(?:yes|yep|yeah|ok|okay|go\s+ahead|do\s+it|please)"
    r"[,.]?\s*(?:please)?|"
    r"yes\s*,?\s*please|"
    r"please\s+(?:do|proceed|create)|"
    r"proceed(?:\s+with\s+(?:creating|it))?"
    r")\s*[.!]?\s*$"
)

_PROCEED_ASK = re.compile(
    r"(?i)\b("
    r"would\s+you\s+like\s+(?:me\s+)?to\s+(?:proceed|create)|"
    r"shall\s+i\s+create|"
    r"want\s+me\s+to\s+(?:create|proceed)|"
    r"proceed\s+with\s+creating"
    r")\b"
)


@dataclass(frozen=True)
class AgendaDraft:
    summary: str
    start: str
    end: str = ""
    provider: str = "google"
    description: str = ""
    source: str = "current"

    @property
    def complete(self) -> bool:
        return bool(self.summary.strip() and self.start.strip())


def looks_like_calendar_create(text: str) -> bool:
    """True when the utterance asks to add/create a calendar event (not SMS)."""
    raw = normalize_calendar_speech(text)
    if not raw:
        return False
    if _EXPLICIT_SMS_VERB.match(raw):
        return False
    if looks_like_calendar_delete(raw):
        return False
    return bool(_CREATE.search(raw))


def looks_like_calendar_delete(text: str) -> bool:
    """True when the utterance asks to delete/cancel a calendar event."""
    raw = normalize_calendar_speech(text)
    if not raw:
        return False
    return bool(_DELETE.search(raw)) or bool(_GOOGLE_EVENT_ID.search(raw))


_READ = re.compile(
    r"(?i)\b("
    r"what(?:'s|\s+is|\s+are)\s+on\s+(?:my\s+)?(?:calendar|agenda|schedule)|"
    r"(?:show|list|read|check|look\s+at)\s+(?:me\s+)?(?:my\s+)?"
    r"(?:calendar|agenda|events)|"
    r"(?:my\s+)?(?:calendar|agenda)\s+(?:for\s+)?"
    r"(?:today|tomorrow|this\s+week)|"
    r"meetings?\s+(?:today|tomorrow|this\s+week)|"
    r"calendar\s+today|"
    r"anything\s+on\s+(?:my\s+)?(?:calendar|agenda)|"
    r"(?:do\s+i\s+have|any)\s+(?:any\s+)?"
    r"(?:meetings?|events?|appointments?)\s+"
    r"(?:today|tomorrow|this\s+week|coming\s+up)|"
    r"upcoming\s+(?:events?|meetings?|appointments?)"
    r")\b"
)

_DUP_DELETE = re.compile(
    r"(?i)\b("
    r"delete\s+(?:two|three|\d+)\s+of\s+them|"
    r"delete\s+(?:the\s+)?(?:extra|duplicate)s?|"
    r"they\s+are\s+all\s+the\s+same|"
    r"you created \d+ events"
    r")\b"
)

_CREATED_LINE = re.compile(
    r"(?i)(?:Created|Already) on (?:google|outlook):\s*"
    r"(?P<title>.+?)\s+@"
)

_DELETE_TITLED = re.compile(
    r"(?i)\b(?:delete|delight|delate)\s+(?:the\s+)?(?P<title>.+?)\s+"
    r"(?:calendar\s+)?event\b"
)

_CLOCK = re.compile(
    r"(?i)\b(?:the\s+)?(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>am|pm)\b"
)

# Surface the Arelis calendar tile — not a list of events, not calendar.google.com.
_OPEN = re.compile(
    r"(?i)\b("
    r"(?:open|launch|pop\s+up)\s+"
    r"(?:(?:up|me|the|my|our)\s+)*"
    r"(?:google\s+)?"
    r"(?:calendar|agenda)"
    r"(?:\s+(?:tile|window|panel|app))?"
    r"|"
    r"(?:bring|pull)\s+up\s+"
    r"(?:(?:the|my|our)\s+)*"
    r"(?:google\s+)?"
    r"(?:calendar|agenda)"
    r"(?:\s+(?:tile|window|panel|app))?"
    r"|"
    r"(?:show|display)\s+"
    r"(?:me\s+)?"
    r"(?:(?:the|my|our)\s+)?"
    r"(?:google\s+)?"
    r"(?:calendar|agenda)"
    r"(?:\s+(?:tile|window|panel))?"
    r")\b"
)
_CALENDAR_WEBSITE = re.compile(
    r"(?i)("
    r"calendar\.google|"
    r"google\.com/calendar|"
    r"\bin\s+(?:the\s+|your\s+|my\s+)?browser\b|"
    r"\bin\s+(?:chrome|edge|firefox)\b|"
    r"\bwebsite\b|"
    r"\bweb\s*site\b"
    r")"
)
_OPEN_SCHEDULE_ASK = re.compile(
    r"(?i)\b("
    r"today|tomorrow|tonight|this\s+week|this\s+morning|this\s+afternoon|"
    r"what(?:'s|\s+is|\s+are)\s+on|"
    r"anything\s+on|"
    r"upcoming|"
    r"for\s+(?:today|tomorrow|this\s+week)|"
    r"events?|meetings?|appointments?"
    r")\b"
)
_CLOSE = re.compile(
    r"(?i)\b("
    r"(?:close|hide|dismiss|shut)\s+"
    r"(?:(?:the|my|our)\s+)*"
    r"(?:google\s+)?"
    r"(?:calendar|agenda)"
    r"(?:\s+(?:tile|window|panel|app))?"
    r"|"
    r"put\s+away\s+"
    r"(?:(?:the|my|our)\s+)*"
    r"(?:google\s+)?"
    r"(?:calendar|agenda)"
    r")\b"
)
_CLOSE_EVENT = re.compile(
    r"(?i)\b(?:close|hide|dismiss|shut)\s+"
    r"(?:(?:the|my|our)\s+)*"
    r"(?:google\s+)?"
    r"(?:calendar|agenda)\s+(?:event|meeting|appointment|reminder)\b"
)


def looks_like_calendar_open(text: str) -> bool:
    """True when they want the Arelis calendar tile shown, not a website."""
    raw = normalize_calendar_speech(text)
    if not raw:
        return False
    if looks_like_calendar_create(raw) or looks_like_calendar_delete(raw):
        return False
    if looks_like_calendar_close(raw):
        return False
    if _CALENDAR_WEBSITE.search(raw):
        return False
    if not _OPEN.search(raw):
        return False
    if _OPEN_SCHEDULE_ASK.search(raw):
        return False
    return True


def looks_like_calendar_close(text: str) -> bool:
    """True when they want the Arelis calendar tile hidden."""
    raw = normalize_calendar_speech(text)
    if not raw:
        return False
    if looks_like_calendar_create(raw):
        return False
    if _CLOSE_EVENT.search(raw):
        return False
    return bool(_CLOSE.search(raw))


def looks_like_calendar_read(text: str) -> bool:
    """True when they want events described, not created, deleted, or opened."""
    raw = normalize_calendar_speech(text)
    if not raw:
        return False
    if looks_like_calendar_create(raw) or looks_like_calendar_delete(raw):
        return False
    if looks_like_calendar_open(raw) or looks_like_calendar_close(raw):
        return False
    return bool(_READ.search(raw))


def agenda_read_action(text: str) -> str:
    """today / tomorrow / list (week) from the user's wording."""
    raw = (text or "").casefold()
    if re.search(r"\btomorrow\b", raw) and not re.search(r"\btoday\b", raw):
        return "tomorrow"
    if re.search(r"\b(?:today|tonight|this\s+morning|this\s+afternoon)\b", raw):
        return "today"
    return "list"


def looks_like_duplicate_delete(text: str) -> bool:
    return bool(_DUP_DELETE.search(text or ""))


def last_agenda_create_summary(
    *,
    receipts: list[Any] | None = None,
    history: list[Any] | None = None,
) -> str:
    """Title of the most recent agenda.create in this session."""
    for rec in reversed(receipts or []):
        if not isinstance(rec, dict):
            continue
        action = str(rec.get("action") or "")
        tool = str(rec.get("tool") or "")
        if tool == "agenda" or action.startswith("agenda."):
            summary = str(rec.get("summary") or "").strip()
            if summary:
                return summary
    pairs: list[str] = []
    for item in history or []:
        if hasattr(item, "content"):
            pairs.append(str(item.content or ""))
        elif isinstance(item, dict):
            pairs.append(str(item.get("content") or ""))
        else:
            pairs.append(str(item or ""))
    for blob in reversed(pairs):
        m = _CREATED_LINE.search(blob)
        if m:
            return (m.group("title") or "").strip()
    return ""


def draft_agenda_delete_args(
    text: str,
    *,
    receipts: list[Any] | None = None,
    history: list[Any] | None = None,
) -> dict[str, Any]:
    """Delete by title/time. Only include event_id when the user pasted one."""
    raw = normalize_calendar_speech(text)
    out: dict[str, Any] = {"action": "delete", "provider": "google"}
    eid = event_id_from_text(raw)
    if eid:
        out["event_id"] = eid
        return out
    titled = _DELETE_TITLED.search(raw)
    if titled and not looks_like_duplicate_delete(raw):
        out["summary"] = titled.group("title").strip()
    else:
        summary = last_agenda_create_summary(receipts=receipts, history=history)
        if summary:
            out["summary"] = summary
    if looks_like_duplicate_delete(raw):
        out["keep"] = 1
    else:
        out["keep"] = 0
    clock = _CLOCK.search(raw)
    if clock:
        hour = int(clock.group("h"))
        minute = int(clock.group("m") or 0)
        ap = (clock.group("ap") or "").lower()
        if ap == "pm" and hour < 12:
            hour += 12
        if ap == "am" and hour == 12:
            hour = 0
        wall = datetime.now().astimezone()
        when = wall.replace(hour=hour, minute=minute, second=0, microsecond=0)
        out["start"] = when.isoformat()
    return out


def agenda_force_read_notice(action: str) -> str:
    act = action if action in {"today", "tomorrow", "list", "range"} else "list"
    return (
        f"Call agenda now with action={act}. Summarize the tool output "
        "(time, title, place, one-line notes). Never invent meetings. "
        "Never ask the user for a Google event id."
    )


def agenda_force_open_notice() -> str:
    return (
        "Call agenda now with action=open. That opens the Arelis calendar "
        "tile. Do not call browser with the calendar alias unless they asked "
        "for calendar.google.com or to open it in Chrome/the browser."
    )


def agenda_force_close_notice() -> str:
    return (
        "Call agenda now with action=close. That hides the Arelis calendar "
        "tile. Do not delete events. Do not call browser."
    )


def agenda_force_delete_notice() -> str:
    return (
        "Call agenda now with action=delete, keep=0, and the event title "
        "(and time if you know it). The tool resolves the id. keep=0 removes "
        "every matching copy. Only pass keep=1 when they asked to delete "
        "extra duplicates and keep one. Do not web_search. Do not ask the "
        "user to paste a Google event id."
    )


def lock_agenda_delete_args(
    args: dict[str, Any],
    text: str,
    *,
    receipts: list[Any] | None = None,
    history: list[Any] | None = None,
) -> dict[str, Any]:
    """Force keep=0 on a titled delete so the 7B cannot leave the event."""
    out = dict(args)
    drafted = draft_agenda_delete_args(
        text, receipts=receipts, history=history
    )
    if not str(out.get("summary") or "").strip() and drafted.get("summary"):
        out["summary"] = drafted["summary"]
    if looks_like_duplicate_delete(text):
        out["keep"] = 1
    elif looks_like_calendar_delete(text):
        out["keep"] = 0
    return out


def event_id_from_text(text: str) -> str:
    m = _GOOGLE_EVENT_ID.search(text or "")
    return m.group(0) if m else ""


def _parse_month_day(text: str, *, wall: datetime) -> datetime | None:
    """Parse 'August 13th' / 'Aug 13, 2026' optionally with trailing time already stripped."""
    m = re.match(
        r"(?i)^\s*(?P<mon>"
        + _MONTH
        + r")\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?"
        r"(?:\s*,?\s*(?P<year>\d{4}))?\s*$",
        text.strip(),
    )
    if not m:
        return None
    mon = _MONTH_NUM.get(m.group("mon").lower())
    if not mon:
        return None
    day = int(m.group("day"))
    year = int(m.group("year") or wall.year)
    # Model invents 2023 when the user said August 13th — clamp to current year
    # when the named year is clearly stale (more than ~1 year in the past).
    if year < wall.year - 1:
        year = wall.year
    try:
        return datetime(year, mon, day, tzinfo=wall.tzinfo)
    except ValueError:
        return None


def normalize_agenda_start(start: str, *, now: datetime | None = None) -> str:
    """Turn relative/local phrases into ISO datetime with local offset.

    Locked draft starts like `today at 11pm` must become real timestamps before
    agenda.create — otherwise the model invents a naive UTC ISO and the event
    lands at the wrong hour (S11).
    """
    text = (start or "").strip()
    if not text:
        return text
    wall = now or datetime.now().astimezone()
    today = wall.date()
    weeks_m = re.match(
        r"(?i)^\s*(?:in\s+)?(?P<n>a|one|two|three|four|\d+)\s+weeks?\s+"
        r"from\s+(?:today|now)(?:\s+at\s+(?P<time>.+))?\s*$",
        text,
    )
    if weeks_m:
        token = (weeks_m.group("n") or "").lower()
        n = _WORD_WEEKS.get(token)
        if n is None:
            try:
                n = int(token)
            except ValueError:
                n = 2
        day = (wall + timedelta(weeks=n)).date()
        time_raw = (weeks_m.group("time") or "").strip()
        if time_raw:
            try:
                hhmm = normalize_time(time_raw)
                hour, minute = (int(x) for x in hhmm.split(":"))
                return datetime(
                    day.year,
                    day.month,
                    day.day,
                    hour,
                    minute,
                    tzinfo=wall.tzinfo,
                ).isoformat()
            except JobError:
                return day.isoformat()
        return day.isoformat()

    # Already ISO date or datetime — attach local tz when naive; clamp stale years.
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        try:
            if len(text) == 10:
                dt = datetime(
                    int(text[0:4]),
                    int(text[5:7]),
                    int(text[8:10]),
                    tzinfo=wall.tzinfo,
                )
            else:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=wall.tzinfo)
            if dt.year < wall.year - 1:
                dt = dt.replace(year=wall.year)
            return dt.isoformat()
        except ValueError:
            return text

    # "August 13th at 7am" (full phrase) or month-day alone.
    md = re.match(
        r"(?i)^\s*(?:on\s+)?(?P<md>(?:"
        + _MONTH
        + r")\s+\d{1,2}(?:st|nd|rd|th)?(?:\s*,?\s*\d{4})?)"
        r"(?:\s+at\s+(?P<time>.+))?\s*$",
        text,
    )
    if md:
        base = _parse_month_day(md.group("md"), wall=wall)
        if base is not None:
            time_raw = (md.group("time") or "").strip()
            if time_raw:
                try:
                    hhmm = normalize_time(time_raw)
                    hour, minute = (int(x) for x in hhmm.split(":"))
                    base = base.replace(hour=hour, minute=minute)
                except JobError:
                    pass
            return base.isoformat()

    day_key = "today"
    time_raw = ""
    m = _REL_AT.match(text)
    if m:
        day_key = m.group("day")
        time_raw = m.group("time")
    else:
        m = _BARE_AT.match(text)
        if m:
            day_key = "today"
            time_raw = m.group("time")
        elif " at " in text.lower():
            # Fallback split for odd spacing.
            left, _, right = text.partition(" at ")
            day_key = left.strip() or "today"
            time_raw = right.strip()
        else:
            return text

    try:
        day = normalize_date(day_key if day_key != "tonight" else "today", today=today)
        hhmm = normalize_time(time_raw)
    except JobError:
        return text
    hour, minute = (int(x) for x in hhmm.split(":"))
    combined = datetime(
        int(day[0:4]),
        int(day[5:7]),
        int(day[8:10]),
        hour,
        minute,
        tzinfo=wall.tzinfo,
    )
    return combined.isoformat()

def _title_from_put_or_add(raw: str) -> str:
    """Quoted or plain title from 'put X on my calendar' / 'add X to my calendar'."""
    skip = {"this", "that", "it", "an event", "a event", "the event"}
    for pat in (_PUT_ON_CALENDAR, _ADD_TO_CALENDAR):
        match = pat.search(raw)
        if not match:
            continue
        title = (match.group("quoted") or match.group("plain") or "").strip()
        title = title.strip("'\"").strip()
        if title and title.lower() not in skip:
            return title
    return ""


def _extract_title(raw: str) -> tuple[str, str]:
    """Return (summary, description) from titled/reminder phrasing."""
    title_m = _TITLE.search(raw)
    if title_m:
        summary = (title_m.group("title") or "").strip().rstrip(".,!;:")
        summary = _TITLE_WHEN.split(summary, maxsplit=1)[0].strip().rstrip(".,!;:")
        return summary, ""
    rem_m = _REMINDER_TITLE.search(raw)
    if rem_m:
        clause = (rem_m.group("title") or "").strip().rstrip(".,!;:")
        # "text my wife and tell her I love her" → short title + notes.
        tell = re.search(
            r"(?i)^(?P<head>.+?)\s+and\s+tell\s+(?:her|him|them)\s+(?P<body>.+)$",
            clause,
        )
        if tell:
            head = (tell.group("head") or "").strip()
            body = (tell.group("body") or "").strip().rstrip(".,!;:")
            # Drop leading "my " in titles for brevity ("text my wife" → "text wife").
            head_l = re.sub(r"(?i)\bmy\s+", "", head).strip()
            summary = head_l[:1].upper() + head_l[1:] if head_l else clause
            if len(summary) > 80:
                summary = summary[:77].rstrip() + "…"
            return summary, body
        summary = clause[:1].upper() + clause[1:] if clause else ""
        if not summary.lower().startswith("reminder"):
            summary = f"Reminder: {summary}"
        if len(summary) > 80:
            summary = summary[:77].rstrip() + "…"
        return summary, clause
    put_title = _title_from_put_or_add(raw)
    if put_title:
        return put_title, ""
    to_m = re.search(r"(?i)(?:[ap]m)\s+to\s+(?P<title>.+)$", raw)
    if to_m:
        title = (to_m.group("title") or "").strip().rstrip(".,!;:")
        if title:
            return title[:1].upper() + title[1:], ""
    return "", ""


def parse_agenda_utterance(text: str) -> AgendaDraft | None:
    raw = normalize_calendar_speech(text)
    if not raw or not _CREATE.search(raw):
        return None
    summary, description = _extract_title(raw)
    # Anniversary / titled by trailing "It is my X" when no called/titled/reminder.
    if not summary:
        ann = re.search(
            r"(?i)\bit(?:'s|\s+is)\s+my\s+(?P<title>[^.\n]{2,60})\s*[.!]?\s*$",
            raw,
        )
        if ann:
            title = (ann.group("title") or "").strip().rstrip(".,!;:")
            summary = title[:1].upper() + title[1:] if title else ""
    when_m = _WHEN.search(raw)
    if not when_m:
        return None
    if when_m.group("iso"):
        start = when_m.group("iso").strip()
    elif when_m.group("md"):
        md = when_m.group("md").strip()
        md_time = (when_m.group("md_time") or "").strip()
        start = f"{md} at {md_time}" if md_time else md
    elif when_m.group("weeks"):
        token = (when_m.group("weeks") or "").lower()
        n = _WORD_WEEKS.get(token)
        if n is None:
            try:
                n = int(token)
            except ValueError:
                n = 2
        wall = datetime.now().astimezone()
        day = (wall + timedelta(weeks=n)).date()
        time_raw = (when_m.group("weeks_time") or "").strip()
        if time_raw:
            try:
                hhmm = normalize_time(time_raw)
                hour, minute = (int(x) for x in hhmm.split(":"))
                start = datetime(
                    day.year,
                    day.month,
                    day.day,
                    hour,
                    minute,
                    tzinfo=wall.tzinfo,
                ).isoformat()
            except JobError:
                start = day.isoformat()
        else:
            start = day.isoformat()
    else:
        start = (when_m.group("rel") or "").strip()
    if not start:
        return None
    # Title optional for incomplete draft (preflight still expects agenda).
    if not summary:
        return AgendaDraft(
            summary="",
            start=normalize_agenda_start(start),
            provider="google",
            source="current",
        )
    start = normalize_agenda_start(start)
    end = ""
    if _DURATION.search(raw):
        try:
            end = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
        except ValueError:
            end = ""
    prov_m = _PROVIDER.search(raw)
    provider = (prov_m.group("p") if prov_m else "google").lower()
    return AgendaDraft(
        summary=summary,
        start=start,
        end=end,
        provider=provider,
        description=description,
    )

def complete_agenda_draft(
    text: str,
    *,
    history: list[Any] | None = None,
) -> AgendaDraft | None:
    """Best-effort draft from this turn, or revive on affirmation."""
    current = parse_agenda_utterance(text)
    if current is not None:
        return current
    if not _SEND_CONFIRM.match(text or ""):
        return None
    pairs = history_pairs(history or [])
    saw_ask = False
    for role, content in reversed(pairs):
        if role == "assistant" and _PROCEED_ASK.search(content or ""):
            saw_ask = True
            continue
        if role == "user":
            prior = parse_agenda_utterance(content)
            if prior is not None and (prior.complete or prior.start):
                return prior
            if saw_ask:
                continue
            break
    return None


def fill_agenda_args(
    args: dict[str, Any],
    draft: AgendaDraft | None,
) -> dict[str, Any]:
    """Lock summary/start (and provider) when the draft is complete.

    When a create draft is complete, list/today/range calls are rewritten to
    create so the 7B cannot burn max_rounds on calendar reads.
    """
    if draft is None or not draft.complete:
        out = dict(args)
        # Still normalize a relative start the model passed through.
        if str(out.get("action") or "").strip().lower() == "create":
            start = str(out.get("start") or "").strip()
            if start:
                out["start"] = normalize_agenda_start(start)
            if not str(out.get("provider") or "").strip():
                out["provider"] = "google"
        return out
    out = dict(args)
    action = str(out.get("action") or "").strip().lower()
    # Rewrite list/today (and empty) into create when we already know the event.
    if action in {"", "create", "today", "list", "range", "get"}:
        out["action"] = "create"
    elif action != "create":
        return out
    out["summary"] = draft.summary
    out["start"] = normalize_agenda_start(draft.start)
    if draft.end and not str(out.get("end") or "").strip():
        out["end"] = draft.end
    if draft.description and not str(out.get("description") or "").strip():
        out["description"] = draft.description
    if not str(out.get("provider") or "").strip():
        out["provider"] = draft.provider or "google"
    return out


def draft_agenda_create_args(draft: AgendaDraft) -> dict[str, Any]:
    """Concrete agenda.create kwargs from a complete draft (for inject)."""
    return fill_agenda_args({}, draft)

def agenda_preflight_nudge(draft: AgendaDraft | None) -> str:
    """System nudge with concrete agenda.create args (still requires Allow)."""
    if draft is not None and draft.complete:
        desc = ""
        if draft.description:
            desc = f' description="{draft.description[:200]}"'
        return (
            "Intent preflight: create a calendar event now. Call agenda "
            f'immediately with action=create provider="{draft.provider}" '
            f'summary="{draft.summary[:120]}" start="{draft.start}"{desc}. '
            "Do not send_sms for a calendar reminder about texting someone — "
            "put that in the event title/description. Do not only give manual "
            "calendar steps. The confirm card is the Allow step."
        )
    if draft is not None and draft.start:
        return (
            "Intent preflight: create a calendar event now. Call agenda with "
            f'action=create provider="google" start="{draft.start}" and a short '
            "summary from the user's reminder wording. Do not send_sms unless "
            "they asked to text someone right now. Do not web_search. "
            "The confirm card is the Allow step."
        )
    return (
        "Intent preflight: the user asked to create a calendar event. Call "
        "agenda with action=create (provider=google unless they named Outlook). "
        "Do not send_sms for a reminder-about-texting. Do not web_search. "
        "Do not only instruct them to open their calendar app. "
        "The confirm card is the Allow step."
    )


def agenda_force_call_notice(draft: AgendaDraft) -> str:
    """User-role nudge when the model tried to finish without calling agenda."""
    desc = ""
    if draft.description:
        desc = f' description="{draft.description[:200]}"'
    return unfinished_call_notice(
        "creating the calendar event",
        (
            f'Call agenda now with action=create provider="{draft.provider}" '
            f'summary="{draft.summary[:120]}" start="{draft.start}"{desc}'
        ),
        after=CREATE_ALLOW_CLOSER,
    )
