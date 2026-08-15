"""Reservation search URLs — fill party / date / time, never click Book."""

from __future__ import annotations

import re
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
    text = str(raw or "").strip()
    match = re.search(r"\d+", text)
    if not match:
        return 2
    try:
        n = int(match.group(0))
    except ValueError:
        return 2
    return max(1, min(20, n))


def normalize_date(raw: str) -> str | None:
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
    return None


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
) -> str:
    """Search URL with party/date/time in the query when the site allows it."""
    q = (place or "").strip()
    kind = normalize_reserve_site(site)
    covers = normalize_party(party)
    day = normalize_date(date)
    clock = normalize_time(time)
    if kind == "resy":
        params: dict[str, str] = {"seats": str(covers)}
        if day:
            params["date"] = day
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
