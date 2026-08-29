"""Open-Meteo current conditions on the globe pins. Public. Not a model.

Host api.open-meteo.com is already pinned for the weather tool. One request
covers the sample cities. Failures return None so the simulated climate
sketch stays. This is a few points, not a station mesh.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_HOST = "api.open-meteo.com"

# Same pins as the simulated climate sketch. Public city coordinates.
CITIES: tuple[tuple[str, float, float], ...] = (
    ("London", 51.5, -0.12),
    ("Tokyo", 35.7, 139.7),
    ("New York", 40.7, -74.0),
    ("Nairobi", -1.3, 36.8),
    ("São Paulo", -23.5, -46.6),
    ("Reykjavík", 64.1, -21.9),
    ("Singapore", 1.35, 103.8),
    ("Sydney", -33.9, 151.2),
    ("Cairo", 30.0, 31.2),
    ("Mumbai", 19.1, 72.9),
    ("Mexico City", 19.4, -99.1),
    ("Cape Town", -33.9, 18.4),
    ("Anchorage", 61.2, -149.9),
    ("Honolulu", 21.3, -157.8),
    ("Lagos", 6.5, 3.4),
    ("Istanbul", 41.0, 29.0),
    ("Seoul", 37.6, 127.0),
    ("Jakarta", -6.2, 106.8),
    ("Buenos Aires", -34.6, -58.4),
    ("Moscow", 55.8, 37.6),
    ("Berlin", 52.5, 13.4),
    ("Dubai", 25.2, 55.3),
    ("Lima", -12.0, -77.0),
    ("Bangkok", 13.8, 100.5),
    ("Vancouver", 49.3, -123.1),
)

_TIMEOUT = 8.0
_CITE = (
    "Open-Meteo current temperature. Model grid, not a station. "
    "A few city pins, not a forecast mesh."
)


def fetch_weather() -> list[Entity] | None:
    payload = _get_forecast()
    if payload is None:
        return None
    return entities_from_forecast(payload)


def entities_from_forecast(payload: dict[str, Any] | list[Any]) -> list[Entity]:
    rows = _as_rows(payload)
    out: list[Entity] = []
    for i, ((name, lat, lon), row) in enumerate(zip(CITIES, rows, strict=False)):
        current = row.get("current") if isinstance(row, dict) else None
        if not isinstance(current, dict):
            current = row if isinstance(row, dict) else {}
        temp = _num(current.get("temperature_2m"))
        if temp is None:
            continue
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=f"wx:{name.casefold()}",
                cls="weather",
                layer="weather",
                label=f"{name} {temp:.0f}°C",
                x=pos[0],
                y=pos[1],
                z=pos[2],
                source="Open-Meteo",
                freshness="live",
                confidence=0.7,
                cite=_CITE,
                meta={"place": name, "temp_c": temp, "lat": lat, "lon": lon},
                coverage=Coverage(
                    "grid",
                    "Model point. Not a weather station. Most of Earth is a hole.",
                ),
            )
        )
        if i >= len(CITIES):
            break
    return out


def _as_rows(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict) and "current" in payload:
        return [payload]
    return []


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _host_pinned(host: str | None) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == OPEN_METEO_HOST or name.endswith("." + OPEN_METEO_HOST)


def _get_forecast() -> dict[str, Any] | list[Any] | None:
    lats = ",".join(str(c[1]) for c in CITIES)
    lons = ",".join(str(c[2]) for c in CITIES)
    url = (
        f"{OPEN_METEO}?latitude={lats}&longitude={lons}"
        "&current=temperature_2m,weather_code&temperature_unit=celsius"
    )
    if not _host_pinned(urlparse(OPEN_METEO).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "ArelisEarth/0.2"})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    if isinstance(data, (dict, list)):
        return data
    return None
