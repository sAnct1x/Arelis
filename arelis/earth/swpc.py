"""NOAA SWPC aurora oval sample. Public JSON. No key.

Ovation forecast cells above a threshold. Not a photograph of the sky.
Failures return None so Open-Meteo / NWS stay. Host pinned in egress.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

SWPC_OVATION = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
SWPC_HOST = "services.swpc.noaa.gov"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 10.0
_CAP = 240
_MIN = 20.0
_CITE = (
    "NOAA SWPC Ovation aurora forecast. Model cells above threshold. "
    "Not a photograph. Not every glow on Earth."
)


def fetch_swpc() -> list[Entity] | None:
    payload = _get_json()
    if payload is None:
        return None
    pins = entities_from_ovation(payload)
    return pins or None


def entities_from_ovation(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("coordinates")
    if not isinstance(rows, list):
        return []
    scored: list[tuple[float, float, float]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        lon, lat, val = _num(row[0]), _num(row[1]), _num(row[2])
        if lon is None or lat is None or val is None:
            continue
        if val < _MIN:
            continue
        if abs(lat) > 90.0 or abs(lon) > 180.0:
            continue
        scored.append((val, lat, lon))
    scored.sort(reverse=True)
    when = str(
        payload.get("Observation Time")
        or payload.get("Forecast Time")
        or payload.get("observation_time")
        or ""
    ).strip()
    out: list[Entity] = []
    seen: set[str] = set()
    for val, lat, lon in scored:
        key = f"{lat:.1f}:{lon:.1f}"
        if key in seen:
            continue
        seen.add(key)
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=f"aurora:{key}",
                cls="weather",
                layer="weather",
                label=f"Aurora {val:.0f}",
                x=pos[0],
                y=pos[1],
                z=pos[2],
                source="NOAA SWPC Ovation",
                freshness="delayed",
                confidence=0.55,
                cite=_CITE,
                meta={"lat": lat, "lon": lon, "aurora": val, "when": when},
                coverage=Coverage(
                    "model",
                    "Forecast cell. Not a photograph. Polar night still needed.",
                ),
            )
        )
        if len(out) >= _CAP:
            break
    return out


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
    return name == SWPC_HOST or name.endswith("." + SWPC_HOST)


def _get_json() -> dict[str, Any] | None:
    if not _host_pinned(urlparse(SWPC_OVATION).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(SWPC_OVATION, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
