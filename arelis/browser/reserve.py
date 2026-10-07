"""Reservation search URLs, fill party / date / time, never click Book."""

from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import quote_plus, urlencode

_SITES = {
    "opentable": "opentable",
    "ot": "opentable",
    "resy": "resy",
    "google": "google",
    "maps": "google",
}

_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_DATE_US = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$")
_TIME_24 = re.compile(r"^(\d{1,2}):(\d{2})$")
_TIME_12 = re.compile(
    r"^(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)$",
    re.I,
)


def normalize_reserve_site(site: str) -> str:
    key = (site or "opentable").strip().lower()
    return _SITES.get(key, "opentable")


def normalize_party(raw: object) -> int:
    text = "" if raw is None else str(raw).strip()
    match = re.search(r"\d+", text)
    if not match:
        return 2
    try:
        n = int(match.group(0))
    except ValueError:
        return 2
    return max(1, min(20, n))


def resolve_party(*candidates: object) -> int:
    """The first party size that was actually given; 0 is a value, not 'missing'."""
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, str) and not candidate.strip():
            continue
        return normalize_party(candidate)
    return 2


_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _today() -> date:
    return date.today()


def _weekday_index(name: str) -> int | None:
    key = (name or "").strip().lower()
    if len(key) < 3:
        return None
    for index, weekday in enumerate(_WEEKDAYS):
        if weekday.startswith(key):
            return index
    return None


def normalize_date(raw: str, *, today: date | None = None) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    hit = _DATE.match(text)
    if hit:
        y, m, d = (int(hit.group(1)), int(hit.group(2)), int(hit.group(3)))
        return f"{y:04d}-{m:02d}-{d:02d}"
    hit = _DATE_US.match(text)
    if hit:
        m, d, y = (int(hit.group(1)), int(hit.group(2)), int(hit.group(3)))
        return f"{y:04d}-{m:02d}-{d:02d}"
    folded = re.sub(r"\s+", " ", text.lower()).strip(" .")
    now = today or _today()
    if folded in {"today", "tonight"}:
        return now.isoformat()
    if folded == "tomorrow":
        return (now + timedelta(days=1)).isoformat()
    if folded in {"day after tomorrow", "the day after tomorrow"}:
        return (now + timedelta(days=2)).isoformat()
    prefix = ""
    name = folded
    if folded.startswith("next "):
        prefix = "next"
        name = folded[5:].strip()
    elif folded.startswith("this "):
        prefix = "this"
        name = folded[5:].strip()
    weekday = _weekday_index(name)
    if weekday is None:
        return None
    ahead = (weekday - now.weekday()) % 7
    # "next Friday" skips today. A bare weekday on that same day means next week.
    if prefix == "next" or (prefix != "this" and ahead == 0):
        if ahead == 0:
            ahead = 7
    return (now + timedelta(days=ahead)).isoformat()


def party_cap_note(*candidates: object) -> str:
    """Plain sentence when the group was larger than online booking allows."""
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, str) and not candidate.strip():
            continue
        if isinstance(candidate, bool):
            return ""
        number: int | None
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            number = int(candidate)
        else:
            match = re.search(r"\d+", str(candidate))
            number = int(match.group(0)) if match else None
        if number is not None and number > 20:
            return (
                "Online booking takes up to 20. "
                "For a bigger group, call the restaurant."
            )
        return ""
    return ""


def normalize_time(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    hit = _TIME_24.match(text)
    if hit:
        h, minute = int(hit.group(1)), int(hit.group(2))
        if 0 <= h <= 23 and 0 <= minute <= 59:
            return f"{h:02d}:{minute:02d}"
        return None
    hit = _TIME_12.match(text)
    if hit:
        h = int(hit.group(1))
        minute = int(hit.group(2) or 0)
        ampm = hit.group(3).lower().replace(".", "")
        if h == 12:
            h = 0
        if ampm.startswith("p"):
            h += 12
        if 0 <= h <= 23 and 0 <= minute <= 59:
            return f"{h:02d}:{minute:02d}"
    return None


def opentable_datetime(date: str | None, time: str | None) -> str | None:
    if not date:
        return None
    clock = time or "19:00"
    return f"{date}T{clock}"


def reserve_url(
    place: str,
    *,
    site: str = "opentable",
    party: object = 2,
    date: str = "",
    time: str = "",
    today: date | None = None,
) -> str:
    """Search URL with party/date/time in the query when the site allows it."""
    q = (place or "").strip()
    kind = normalize_reserve_site(site)
    covers = normalize_party(party)
    day = normalize_date(date, today=today)
    clock = normalize_time(time)
    if kind == "resy":
        params: dict[str, str] = {"seats": str(covers)}
        if day:
            params["date"] = day
        if clock:
            params["time"] = clock
        if q:
            params["query"] = q
        return "https://resy.com/?" + urlencode(params, quote_via=quote_plus)
    if kind == "google":
        bits = ["Reserve a table", q]
        if day:
            bits.append(day)
        if clock:
            bits.append(clock)
        if covers != 2:
            bits.append(f"party of {covers}")
        return "https://www.google.com/search?q=" + quote_plus(
            " ".join(b for b in bits if b)
        )
    params = {"term": q, "covers": str(covers)}
    stamp = opentable_datetime(day, clock)
    if stamp:
        params["dateTime"] = stamp
    return "https://www.opentable.com/s?" + urlencode(params, quote_via=quote_plus)
