"""Forecast and geocode helpers for the briefing template."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

# WMO weather interpretation codes (subset). Enough for a morning line.
_WMO: dict[int, str] = {
    0: "clear",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}


def describe_weather_code(code: Any) -> str:
    try:
        value = int(code)
    except (TypeError, ValueError):
        return ""
    return _WMO.get(value, f"conditions code {value}")


_GEOCODE_CANDIDATES = 10
_REGION_KEYS = ("admin1", "admin2", "admin3", "admin4", "country", "country_code")

# A typed place can be a street or a saved home address. The debug line is
# the geocoder's city and the HTTP status, and only when a city resolved.
# This logger does not propagate, so the line stays out of the app log
# unless debug logging is turned on for it.
_lookup_log = logging.getLogger("arelis.weather.lookup")
_lookup_log.propagate = False
_lookup_log.addHandler(logging.NullHandler())
_lookup_file_ready = False
_EMAIL = re.compile(r"(?i)\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE = re.compile(
    r"(?<![\d.])(?:\+?1[\s.-]?)?\(?[2-9]\d{2}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
)


@dataclass(frozen=True)
class ResolvedPlace:
    """The place the forecast is for, in words the user can check."""

    label: str
    latitude: float
    longitude: float
    # Empty when one city matched.
    alternatives: tuple[str, ...] = ()


def _folded(value: Any) -> str:
    return " ".join(str(value or "").split())


def _place_query_parts(query: str) -> tuple[str, tuple[str, ...]]:
    """City, then the state or country the user actually wrote.

    A comma splits them. "Springfield, Illinois" is the city Springfield
    and the region Illinois. No word list: the words are theirs.
    """
    parts = [part.strip(" ,") for part in (query or "").split(",") if part.strip(" ,")]
    if len(parts) >= 2:
        return parts[0], tuple(parts[1:])
    return _folded(query), ()


def _region_values(entry: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in _REGION_KEYS:
        value = _folded(entry.get(key))
        if value:
            values.append(value)
    return values


def _region_forms(text: str) -> set[str]:
    folded = _folded(text).casefold()
    if not folded:
        return set()
    forms = {folded}
    # Abbreviation and full name are one region. Imported here so this
    # module can load before the tool module finishes.
    from arelis.tools.weather import (
        _ABBR_TO_NAME,
        _US_STATE_NAME_TO_ABBR,
        _US_STATE_PHRASES,
    )

    expanded = _ABBR_TO_NAME.get(folded)
    if expanded:
        forms.add(expanded.casefold())
    abbr = _US_STATE_NAME_TO_ABBR.get(folded)
    if abbr:
        forms.add(abbr)
    code = _US_STATE_PHRASES.get(tuple(folded.split()))
    if code:
        forms.add(code)
        named = _ABBR_TO_NAME.get(code)
        if named:
            forms.add(named.casefold())
    return forms


def _hit_region_forms(entry: dict[str, Any]) -> set[str]:
    forms: set[str] = set()
    for value in _region_values(entry):
        forms |= _region_forms(value)
    return forms


def place_region_match(place: str, entry: dict[str, Any]) -> bool:
    """True when the place string names this hit's own state or country.

    A comma is the city, then the region words. With no comma, the string
    ends with that hit's admin or country, or is exactly that region.
    """
    if not isinstance(entry, dict):
        return False
    raw = _folded(place)
    if not raw:
        return False
    _city, quals = _place_query_parts(raw)
    regions = _hit_region_forms(entry)
    if not regions:
        return False
    if quals:
        for part in quals:
            wanted = _region_forms(part)
            if not wanted or not (wanted & regions):
                return False
        return True
    city_name = _folded(entry.get("name")).casefold()
    for form in regions:
        if not form or form == city_name:
            continue
        if raw.casefold() == form or raw.casefold().endswith(" " + form):
            return True
    return False


def choose_geocode_hit(
    query: str, results: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Pick the hit that keeps the state or country they named.

    The first hit is only the answer when they named no region. A named
    region that matches nothing is no hit.
    """
    usable = [entry for entry in results if isinstance(entry, dict)]
    if not usable:
        return None
    _city, qualifiers = _place_query_parts(query)
    if qualifiers or any(place_region_match(query, entry) for entry in usable):
        matched = [entry for entry in usable if place_region_match(query, entry)]
        if qualifiers or matched:
            return matched[0] if matched else None
    return usable[0]


def geocode_search_names(query: str) -> list[str]:
    city, qualifiers = _place_query_parts(query)
    names: list[str] = []
    if city:
        names.append(city)
    if not qualifiers:
        tokens = city.split()
        if len(tokens) >= 2:
            shorter = " ".join(tokens[:-1])
            if shorter and shorter not in names:
                names.append(shorter)
    return names


def _place_label(entry: dict[str, Any]) -> str:
    """ "Springfield, Canterbury, New Zealand", name, region, country."""
    bits = [str(entry.get("name") or "").strip()]
    for key in ("admin1", "country"):
        value = str(entry.get(key) or "").strip()
        if value and value not in bits:
            bits.append(value)
    return ", ".join(b for b in bits if b)


async def resolve_place(
    name: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 15.0,
) -> ResolvedPlace | None:
    """Geocode a place name and keep the state or country they named.

    Asks for several candidates. When the query names a region, the hit
    whose admin or country matches that region wins. The first hit is used
    only when they named no region. A named region with no match is None.
    """
    query = _folded(name)
    if not query:
        return None
    url = "https://geocoding-api.open-meteo.com/v1/search"
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_s)
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    try:
        for search_name in geocode_search_names(query):
            response = await client.get(
                url, params={"name": search_name, "count": _GEOCODE_CANDIDATES}
            )
            response.raise_for_status()
            data = response.json()
            for entry in data.get("results") or []:
                if not isinstance(entry, dict):
                    continue
                key = (
                    _folded(entry.get("name")).casefold(),
                    _folded(entry.get("admin1")).casefold(),
                    _folded(entry.get("country")).casefold(),
                )
                if key in seen:
                    continue
                seen.add(key)
                results.append(entry)
    finally:
        if owns:
            await client.aclose()
    hinted = [entry for entry in results if place_region_match(query, entry)]
    _city, qualifiers = _place_query_parts(query)
    pool = hinted if hinted or qualifiers else results
    first = choose_geocode_hit(query, results)
    if first is None:
        return None
    try:
        lat = float(first["latitude"])
        lon = float(first["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    chosen = _place_label(first)
    others: list[str] = []
    for entry in pool:
        if entry is first:
            continue
        label = _place_label(entry)
        # A label equal to the chosen one is the API echoing the same city, not
        # a second place the user might have meant.
        if label and label != chosen and label not in others:
            others.append(label)
    return ResolvedPlace(
        label=chosen,
        latitude=lat,
        longitude=lon,
        alternatives=tuple(others),
    )


def _lookup_place(place: str) -> str:
    """Drop an email or a phone number before a debug line is formatted."""
    text = _EMAIL.sub("[redacted]", place or "")
    return _PHONE.sub("[redacted]", text)


def _result_rows(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("results")
    if not isinstance(raw, list):
        return []
    return [row for row in raw if isinstance(row, dict)]


def _city_for_log(query: str, results: list[dict[str, Any]] | None) -> str:
    """Geocoder city name, or empty when the lookup did not resolve.

    The typed query is never the line. A street, a postal code, or a
    coordinate stays off it.
    """
    rows = [row for row in (results or []) if isinstance(row, dict)]
    if not rows:
        return ""
    hit = choose_geocode_hit(query, rows)
    if hit is None:
        named = [row for row in rows if _folded(row.get("name"))]
        if len(named) == 1:
            hit = named[0]
    if hit is None:
        return ""
    return _folded(hit.get("name")).split(",", 1)[0].strip()


def _attach_lookup_file() -> None:
    """Separate debug file. Never a handler on the app log."""
    global _lookup_file_ready
    if _lookup_file_ready:
        return
    _lookup_file_ready = True
    try:
        from arelis.paths import logs_dir

        directory = logs_dir()
        directory.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(directory / "weather-lookup.log", encoding="utf-8")
    except OSError:
        return
    handler.setLevel(logging.DEBUG)
    _lookup_log.addHandler(handler)


def log_lookup(
    place: str,
    status: object,
    results: list[dict[str, Any]] | None = None,
) -> None:
    """Resolved city and HTTP status, debug only.

    A lookup that did not resolve logs the status only. The typed place
    is never written. Off unless this logger or the root logger is at
    debug. The record does not propagate into the normal app log.
    """
    if not _lookup_log.isEnabledFor(logging.DEBUG):
        return
    _attach_lookup_file()
    city = _lookup_place(_city_for_log(place, results))
    if city:
        _lookup_log.debug("lookup place=%s status=%s", city, status)
        return
    _lookup_log.debug("lookup status=%s", status)


async def search_geocode(
    name: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 15.0,
) -> list[dict[str, Any]]:
    """One gazetteer request. The caller filters. No second lookup."""
    query = " ".join((name or "").split())
    if not query:
        return []
    url = "https://geocoding-api.open-meteo.com/v1/search"
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_s)
    try:
        try:
            response = await client.get(
                url, params={"name": query, "count": _GEOCODE_CANDIDATES}
            )
        except httpx.TimeoutException:
            log_lookup(query, "timeout")
            raise
        except httpx.TransportError:
            log_lookup(query, "connection")
            raise
        try:
            payload = response.json()
        except Exception:
            log_lookup(query, response.status_code)
            response.raise_for_status()
            raise
        rows = _result_rows(payload) if response.is_success else None
        log_lookup(query, response.status_code, rows)
        response.raise_for_status()
        data = payload
    finally:
        if owns:
            await client.aclose()
    return [row for row in (data.get("results") or []) if isinstance(row, dict)]


async def geocode_place(
    name: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 15.0,
) -> tuple[float, float] | None:
    """Coordinates only, for callers that do not report a place back.

    Kept as the narrow face of `resolve_place` rather than deleted: the
    briefing template and the profile fallback both want the pair and have
    nowhere to show a label.
    """
    place = await resolve_place(name, client=client, timeout_s=timeout_s)
    return None if place is None else (place.latitude, place.longitude)


MAX_FORECAST_DAYS = 16
MAX_PAST_DAYS = 7
MAX_HOURS = 48


async def fetch_forecast(
    latitude: float,
    longitude: float,
    *,
    days: int = 3,
    hours: int = 0,
    past_days: int = 0,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    """Current conditions, daily rows, and optionally hourly / past days.

    ``hours`` answers "will it rain at three", a daily row cannot, because
    ``precipitation_probability_max`` is the whole day's maximum and says
    nothing about when. ``past_days`` answers "what was it yesterday", which
    had no route at all: forecast rows start today.
    """
    days = max(1, min(MAX_FORECAST_DAYS, int(days)))
    hours = max(0, min(MAX_HOURS, int(hours or 0)))
    past_days = max(0, min(MAX_PAST_DAYS, int(past_days or 0)))
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        "&timezone=auto&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&forecast_days={days}"
        "&current=temperature_2m,apparent_temperature,precipitation,weather_code"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max"
    )
    if past_days:
        url += f"&past_days={past_days}"
    if hours:
        url += "&hourly=temperature_2m,precipitation_probability,weather_code"
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
    finally:
        if owns:
            await client.aclose()

    current = data.get("current") or {}
    daily_raw = data.get("daily") or {}
    dates = daily_raw.get("time") or []
    daily: list[dict[str, Any]] = []
    for i, date in enumerate(dates):
        row: dict[str, Any] = {"date": date}
        for key in (
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
        ):
            values = daily_raw.get(key) or []
            if i < len(values):
                row[key] = values[i]
        daily.append(row)

    hourly: list[dict[str, Any]] = []
    if hours:
        hourly_raw = data.get("hourly") or {}
        stamps = hourly_raw.get("time") or []
        # Open-Meteo returns whole days of hours, and with past_days set the
        # series starts *yesterday*. Trimming to `hours` from now is what makes
        # "the next 6 hours" mean that rather than "some hours, from midnight".
        start = _first_upcoming_hour(stamps, current.get("time"))
        for i in range(start, min(start + hours, len(stamps))):
            entry: dict[str, Any] = {"time": stamps[i]}
            for key in (
                "temperature_2m",
                "precipitation_probability",
                "weather_code",
            ):
                values = hourly_raw.get(key) or []
                if i < len(values):
                    entry[key] = values[i]
            hourly.append(entry)

    return {"current": current, "daily": daily, "hourly": hourly, "url": url}


def _first_upcoming_hour(stamps: list[Any], now: Any) -> int:
    """Index of the first hourly stamp at or after now. 0 when unknown.

    Open-Meteo stamps are local ISO strings ("2026-09-17T15:00") and sort
    lexicographically, so this needs no date parsing, which also means a
    format change degrades to "start at the beginning" rather than raising.
    """
    marker = str(now or "").strip()
    if not marker:
        return 0
    for i, stamp in enumerate(stamps):
        if str(stamp) >= marker:
            return i
    return 0


async def fetch_current_weather(
    latitude: float,
    longitude: float,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    """Current conditions plus today's high/low/precip probability."""
    packed = await fetch_forecast(
        latitude,
        longitude,
        days=1,
        client=client,
        timeout_s=timeout_s,
    )
    out: dict[str, Any] = {}
    current = packed.get("current") or {}
    for key in (
        "temperature_2m",
        "apparent_temperature",
        "precipitation",
        "weather_code",
    ):
        if key in current:
            out[key] = current[key]
    daily = packed.get("daily") or []
    if daily:
        first = daily[0]
        for key in (
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
        ):
            if key in first:
                out[key] = first[key]
    return out
