"""Open-Meteo helpers for the briefing template.

Same API the model is told to use in TOOL_POLICY, but called here without a
round trip through the chat model.
"""

from __future__ import annotations

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


async def geocode_place(
    name: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 15.0,
) -> tuple[float, float] | None:
    """Resolve a profile place name to coordinates via Open-Meteo geocoding.

    Used when the user named a city but did not paste lat/lon. Never accepts
    model-invented coordinates — only a place string we already trust.
    """
    query = " ".join((name or "").split())
    if not query:
        return None
    url = "https://geocoding-api.open-meteo.com/v1/search"
    owns = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=timeout_s)
    try:
        response = await client.get(url, params={"name": query, "count": 1})
        response.raise_for_status()
        data = response.json()
    finally:
        if owns:
            await client.aclose()
    results = data.get("results") or []
    if not results:
        return None
    first = results[0] or {}
    try:
        lat = float(first["latitude"])
        lon = float(first["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    return lat, lon


async def fetch_forecast(
    latitude: float,
    longitude: float,
    *,
    days: int = 3,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    """Current conditions plus daily rows for the next ``days`` (1-7)."""
    days = max(1, min(7, int(days)))
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        "&timezone=auto&temperature_unit=fahrenheit&wind_speed_unit=mph"
        f"&forecast_days={days}"
        "&current=temperature_2m,apparent_temperature,precipitation,weather_code"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max"
    )
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
    return {"current": current, "daily": daily, "url": url}


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
