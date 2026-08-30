"""WAQI / AQICN map pins. Free token. Not a VIN.

Token from earth.waqi_token or ARELIS_WAQI_TOKEN. Their ToS: free,
local observer only, not sold, not republished as a cache. Attribution
to the World Air Quality Index Project and the originating EPA is
required. Bounds pins name the station; we do not archive the feed.
Unvalidated live reading. Failures return None. Host pinned in egress.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef
from arelis.earth.secrets import earth_secret

WAQI_BOUNDS = "https://api.waqi.info/v2/map/bounds"
WAQI_HOST = "api.waqi.info"
WAQI_ENV = "ARELIS_WAQI_TOKEN"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 10.0
_CAP = 400
_CITE = (
    "World Air Quality Index Project (https://waqi.info/) and the "
    "originating EPA. Free token. Local observer only. Unvalidated "
    "live reading. Do not sell. Do not republish the dump. "
    "A published monitor, not a car and not a face."
)


def waqi_token(path=None) -> str:
    return earth_secret("waqi_token", WAQI_ENV, path)


def fetch_waqi() -> list[Entity] | None:
    token = waqi_token()
    if not token:
        return None
    payload = _get_json(token)
    if payload is None:
        return None
    return entities_from_map(payload) or None


def entities_from_map(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_row(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_row(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("lat"))
    lon = _num(row.get("lon"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    uid = str(row.get("uid") or row.get("idx") or "").strip()
    station = row.get("station") if isinstance(row.get("station"), dict) else {}
    name = str(station.get("name") or uid or "AQI").strip()
    aqi = _num(row.get("aqi"))
    if aqi is None:
        raw = row.get("aqi")
        if isinstance(raw, str) and raw.strip().isdigit():
            aqi = float(raw.strip())
    if not uid and not name:
        return None
    label = f"{name} AQI {aqi:.0f}" if aqi is not None else name
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"waqi:{uid or name.casefold()[:32]}",
        cls="weather",
        layer="weather",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="WAQI",
        freshness="delayed",
        confidence=0.65,
        cite=f"{name}. {_CITE}" if name else _CITE,
        meta={"lat": lat, "lon": lon, "aqi": aqi},
        coverage=Coverage(
            "station",
            "Published air monitor. Not a car. Not every city.",
        ),
    )


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
    return name == WAQI_HOST or name.endswith("." + WAQI_HOST)


def _get_json(token: str) -> dict[str, Any] | None:
    url = f"{WAQI_BOUNDS}?latlng=-60,-180,70,180&token={token}"
    if not _host_pinned(urlparse(WAQI_BOUNDS).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": _UA},
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
