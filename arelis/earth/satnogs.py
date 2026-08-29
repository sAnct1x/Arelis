"""SatNOGS ground stations. Public network API. No key.

Amateur radio observers that published a pin. Not a transmitter viewshed
and not audio. Failures return None. Host pinned in egress.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

SATNOGS_STATIONS = "https://network.satnogs.org/api/stations/?format=json"
SATNOGS_HOST = "network.satnogs.org"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 12.0
_CAP = 400
_CITE = (
    "SatNOGS Network ground stations. Libre Space amateur observers. "
    "Position only. No audio ingest. Not a viewshed."
)


def fetch_satnogs() -> list[Entity] | None:
    rows = _get_json()
    if rows is None:
        return None
    return entities_from_stations(rows) or None


def entities_from_stations(rows: list[Any]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_station(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_station(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("lat") or row.get("latitude"))
    lon = _num(row.get("lng") or row.get("lon") or row.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    sid = str(row.get("id") or "").strip()
    name = str(row.get("name") or sid).strip()
    if not sid and not name:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"satnogs:{sid or name.casefold()[:32]}",
        cls="rf",
        layer="radio",
        label=name[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="SatNOGS Network",
        freshness="reconstructed",
        confidence=0.7,
        cite=_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "pin",
            "Published observer pin. No audio. Pose unknown.",
        ),
        pii="none",
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
    return name == SATNOGS_HOST or name.endswith("." + SATNOGS_HOST)


def _get_json() -> list[Any] | None:
    if not _host_pinned(urlparse(SATNOGS_STATIONS).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(SATNOGS_STATIONS, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get("results") or data.get("stations") or []
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else None
    return None
