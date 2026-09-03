"""GeoNet New Zealand quakes. Public JSON. No key.

NZ authority catalog. Overlaps USGS/EMSC globally but adds the local
network. Below detection / elsewhere stays empty. Failures return None.
Host pinned in tests/test_egress.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

GEONET_QUAKE = "https://api.geonet.org.nz/quake?MMI=-1"
GEONET_HOST = "api.geonet.org.nz"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 10.0
_CAP = 120
_CITE = (
    "GeoNet New Zealand quakes. Local network. Below detection and the "
    "rest of Earth stay a hole. Delayed."
)


def fetch_geonet() -> list[Entity] | None:
    payload = _get_json()
    if payload is None:
        return None
    return entities_from_geojson(payload) or None


def entities_from_geojson(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_feat(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_feat(feat: dict[str, Any]) -> Entity | None:
    props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
    geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
    coords = geom.get("coordinates") if isinstance(geom.get("coordinates"), list) else []
    lon = _num(coords[0] if len(coords) > 0 else None)
    lat = _num(coords[1] if len(coords) > 1 else None)
    depth = _num(coords[2] if len(coords) > 2 else None)
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    eid = str(props.get("publicID") or feat.get("id") or "").strip()
    mag = _num(props.get("magnitude") or props.get("mag")) or 0.0
    place = str(props.get("locality") or props.get("place") or "").strip()
    label = f"M{mag:.1f} {place}".strip()
    if not eid and not place:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"geonet:{eid or f'{lat:.3f}:{lon:.3f}'}",
        cls="quake",
        layer="quakes",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        when_unix=_unix_from_iso(props.get("time")),
        source="GeoNet NZ",
        freshness="delayed",
        confidence=0.8,
        cite=_CITE,
        meta={"mag": mag, "lat": lat, "lon": lon, "place": place, "depth_km": depth},
        coverage=Coverage(
            "seismic",
            "New Zealand network. Reported event. Elsewhere is a hole.",
        ),
    )


def _unix_from_iso(stamp: Any) -> float:
    if not isinstance(stamp, str) or not stamp.strip():
        return 0.0
    text = stamp.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).astimezone(UTC).timestamp()
    except ValueError:
        return 0.0


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_json() -> dict[str, Any] | None:
    from arelis.earth.http import get_json

    data = get_json(
        GEONET_QUAKE, GEONET_HOST, timeout=_TIMEOUT, headers={"User-Agent": _UA}
    )
    return data if isinstance(data, dict) else None
