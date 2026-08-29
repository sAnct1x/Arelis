"""EMSC / Seismic Portal events. Public FDSN JSON. No key.

Worldwide complement to USGS all_day. Failures return None so USGS
stays. Host pinned in tests/test_egress.py.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

EMSC_QUERY = (
    "https://www.seismicportal.eu/fdsnws/event/1/query"
    "?format=json&limit=200&orderby=time&minmag=2"
)
EMSC_HOST = "www.seismicportal.eu"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 10.0
_CAP = 200
_CITE = (
    "EMSC Seismic Portal FDSN events. Last reports, min M2. "
    "Depth when published. Below network detection stays a hole. Delayed."
)


def fetch_emsc() -> list[Entity] | None:
    payload = _get_json()
    if payload is None:
        return None
    return entities_from_fdsn(payload) or None


def entities_from_fdsn(payload: dict[str, Any]) -> list[Entity]:
    features = payload.get("features")
    if not isinstance(features, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for feat in features:
        if not isinstance(feat, dict):
            continue
        entity = _entity_from_feat(feat)
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
    depth = _num(coords[2] if len(coords) > 2 else props.get("depth"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    eid = str(feat.get("id") or props.get("unid") or "").strip()
    mag = _num(props.get("mag")) or 0.0
    place = str(props.get("flynn_region") or props.get("place") or "").strip()
    label = f"M{mag:.1f} {place}".strip()
    if depth is not None and depth > 0:
        label = f"{label} {depth:.0f}km".strip()
    if not eid and not place:
        return None
    when = _num(props.get("time"))
    unix = (when / 1000.0) if when and when > 1.0e11 else (when or 0.0)
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"emsc:{eid or f'{lat:.3f}:{lon:.3f}'}",
        cls="quake",
        layer="quakes",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        when_unix=float(unix or 0.0),
        source="EMSC Seismic Portal",
        freshness="delayed",
        confidence=0.8,
        cite=_CITE,
        meta={"mag": mag, "lat": lat, "lon": lon, "place": place, "depth_km": depth},
        coverage=Coverage(
            "seismic",
            "Reported event. Below network detection is a hole.",
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
    return name == EMSC_HOST or name.endswith("." + EMSC_HOST)


def _get_json() -> dict[str, Any] | None:
    if not _host_pinned(urlparse(EMSC_QUERY).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(EMSC_QUERY, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
