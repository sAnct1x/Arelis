"""NWS active alerts. Public GeoJSON. Not a forecast mesh.

api.weather.gov requires a User-Agent. No key. Failures return None so
the Open-Meteo city pins stay. Host pinned in tests/test_egress.py.
"""

from __future__ import annotations

from typing import Any

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

NWS_ACTIVE = "https://api.weather.gov/alerts/active"
NWS_HOST = "api.weather.gov"
_UA = f"Arelis/{__version__} (+{__source_url__})"

_TIMEOUT = 12.0
_CAP = 400
_CITE = (
    "NWS active alerts (api.weather.gov). CAP GeoJSON. US / territories. "
    "Not a station mesh. Not every warning on Earth."
)


def fetch_nws() -> list[Entity] | None:
    payload = _get_json()
    if payload is None:
        return None
    return entities_from_alerts(payload)


def entities_from_alerts(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_alert(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_alert(feat: dict[str, Any]) -> Entity | None:
    props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
    geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
    lat, lon = _geom_ll(geom)
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    aid = str(props.get("id") or feat.get("id") or "").strip()
    event = str(props.get("event") or props.get("headline") or "").strip()
    area = str(props.get("areaDesc") or "").strip()
    if not aid and not event:
        return None
    label = event or aid
    if area and area.casefold() not in label.casefold():
        label = f"{label} {area.split(';')[0].strip()}"
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"nws:{aid.split('/')[-1] if aid else label.casefold()[:40]}",
        cls="weather",
        layer="weather",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="NWS alerts",
        freshness="delayed",
        confidence=0.75,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "event": event},
        coverage=Coverage(
            "alert",
            "Published CAP alert. A polygon centroid, not a station.",
        ),
    )


def _geom_ll(geom: dict[str, Any]) -> tuple[float | None, float | None]:
    coords = geom.get("coordinates")
    if not isinstance(coords, list) or not coords:
        return None, None
    kind = str(geom.get("type") or "")
    if kind == "Point" and len(coords) >= 2:
        return _num(coords[1]), _num(coords[0])
    first = coords[0]
    if kind == "Polygon" and isinstance(first, list) and first:
        ring = first
        if isinstance(ring[0], (list, tuple)) and len(ring[0]) >= 2:
            return _centroid(ring)
    if isinstance(first, (list, tuple)) and len(first) >= 2:
        if isinstance(first[0], (list, tuple)):
            return _centroid(first) if first else (None, None)
        return _num(first[1]), _num(first[0])
    return None, None


def _centroid(ring: list[Any]) -> tuple[float | None, float | None]:
    pts: list[tuple[float, float]] = []
    for pt in ring:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        lon = _num(pt[0])
        lat = _num(pt[1])
        if lat is None or lon is None:
            continue
        pts.append((lat, lon))
    if len(pts) >= 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return None, None
    return (
        sum(p[0] for p in pts) / len(pts),
        sum(p[1] for p in pts) / len(pts),
    )


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
        NWS_ACTIVE,
        NWS_HOST,
        timeout=_TIMEOUT,
        headers={"User-Agent": _UA, "Accept": "application/geo+json"},
    )
    return data if isinstance(data, dict) else None
