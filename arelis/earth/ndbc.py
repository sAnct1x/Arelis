"""NOAA NDBC buoy / C-MAN catalog. Public JSON. No key.

Published stations only. Open ocean between buoys is a hole. Not a hull
tracker. Failures return None. Host pinned in tests/test_egress.py.
"""

from __future__ import annotations

from typing import Any

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

NDBC_STATIONS = "https://www.ndbc.noaa.gov/ndbcmapstations.json"
NDBC_HOST = "www.ndbc.noaa.gov"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 12.0
_CAP = 400
_CITE = (
    "NOAA NDBC station catalog. Published buoys / C-MAN / DART. "
    "Open ocean between stations is a hole. Not a hull. Not every wave."
)


def fetch_ndbc() -> list[Entity] | None:
    payload = _get_json()
    if payload is None:
        return None
    return entities_from_stations(payload) or None


def entities_from_stations(payload: dict[str, Any] | list[Any]) -> list[Entity]:
    rows = _station_rows(payload)
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        entity = _entity_from_station(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _station_rows(payload: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("station", "stations", "features"):
        raw = payload.get(key)
        if isinstance(raw, list):
            return [row for row in raw if isinstance(row, dict)]
    return []


def _entity_from_station(row: dict[str, Any]) -> Entity | None:
    props = row.get("properties") if isinstance(row.get("properties"), dict) else row
    geom = row.get("geometry") if isinstance(row.get("geometry"), dict) else {}
    lat = _num(props.get("lat") or props.get("latitude"))
    lon = _num(props.get("lon") or props.get("longitude") or props.get("lng"))
    if lat is None or lon is None:
        coords = geom.get("coordinates") if isinstance(geom.get("coordinates"), list) else []
        if len(coords) >= 2:
            lon = _num(coords[0])
            lat = _num(coords[1])
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    sid = str(props.get("id") or props.get("station") or props.get("name") or "").strip()
    name = str(props.get("name") or props.get("id") or sid).strip()
    if not sid:
        return None
    label = name if name.casefold() != sid.casefold() else sid
    if label.casefold() != sid.casefold():
        label = f"{sid} {label}"
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"ndbc:{sid.casefold()}",
        cls="weather",
        layer="weather",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="NOAA NDBC",
        freshness="reconstructed",
        confidence=0.7,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "station": sid},
        coverage=Coverage(
            "station",
            "Published buoy / C-MAN pin. Open ocean between stations is a hole.",
        ),
    )


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_json() -> dict[str, Any] | list[Any] | None:
    from arelis.earth.http import get_json

    data = get_json(
        NDBC_STATIONS, NDBC_HOST, timeout=_TIMEOUT, headers={"User-Agent": _UA}
    )
    return data if isinstance(data, (dict, list)) else None
