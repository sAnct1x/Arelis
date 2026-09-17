"""Open-Meteo helpers for the briefing template.

Same API the model is told to use in TOOL_POLICY, but called here without a
round trip through the chat model.
"""

from __future__ import annotations

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


_GEOCODE_CANDIDATES = 5


@dataclass(frozen=True)
class ResolvedPlace:
    """Where the forecast is actually for, in words the user can check.

    The point of the label is that a wrong city becomes *visible*. Returning a
    bare `(lat, lon)` meant "Springfield" resolved to one of thirty and the
    answer echoed the user's own string back, so there was no signal anywhere
    that the forecast was for the wrong state.
    """

    label: str
    latitude: float
    longitude: float
    # Other cities the same name matched, already formatted. Empty when the
    # name was unambiguous — worth distinguishing, because a disambiguation
    # note on every single forecast is noise that gets ignored.
    alternatives: tuple[str, ...] = ()


def _place_label(entry: dict[str, Any]) -> str:
    """ "Springfield, Canterbury, New Zealand" — name, region, country."""
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
    """Geocode a place name and keep enough of the answer to state it.

    Asks for several candidates rather than one, which is what makes ambiguity
    detectable at all: with `count=1` there is no way to tell "the only
    Springfield" from "the first of thirty".
    """
    query = " ".join((name or "").split())
    if not query:
        return None
    url = "https://geocoding-api.open-meteo.com/v1/search"
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await client.get(url, params={"name": query, "count": _GEOCODE_CANDIDATES})
        response.raise_for_status()
        data = response.json()
    finally:
        if owns:
            await client.aclose()
    results = [r for r in (data.get("results") or []) if isinstance(r, dict)]
    if not results:
        return None
    first = results[0]
    try:
        lat = float(first["latitude"])
        lon = float(first["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    chosen = _place_label(first)
    others: list[str] = []
    for entry in results[1:]:
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

    ``hours`` answers "will it rain at three" — a daily row cannot, because
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
    lexicographically, so this needs no date parsing — which also means a
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
