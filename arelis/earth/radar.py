"""Sentinel-1 pass footprints over open ocean.

NASA ASF catalog search, no key, no granule download. A frame center is
where radar looked, not a hull name. This is a sample of recent IW scenes
across mid-ocean boxes, not every Sentinel-1 pass. Browse JPEGs are too
coarse to invent ships. VIIRS boat lights stay later; Mines NRT wants a login.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

ASF_SEARCH = "https://api.daac.asf.alaska.edu/services/search/param"
ASF_HOST = "api.daac.asf.alaska.edu"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 12.0
_CAP = 40
_PER_BOX = 8
_LOOKBACK_DAYS = 5

# Mid-ocean rectangles, not a full-Earth dump. ASF search is the sample.
_OCEAN_WKT: tuple[str, ...] = (
    "POLYGON((160 15, 180 15, 180 40, 160 40, 160 15))",
    "POLYGON((-180 15, -130 15, -130 40, -180 40, -180 15))",
    "POLYGON((-50 10, -25 10, -25 35, -50 35, -50 10))",
    "POLYGON((-160 -40, -100 -40, -100 -15, -160 -15, -160 -40))",
    "POLYGON((60 -20, 100 -20, 100 10, 60 10, 60 -20))",
    "POLYGON((-30 -40, 10 -40, 10 -10, -30 -10, -30 -40))",
    "POLYGON((-180 -60, 0 -60, 0 -45, -180 -45, -180 -60))",
    "POLYGON((0 -60, 180 -60, 180 -45, 0 -45, 0 -60))",
)
_CITE = (
    "Sentinel-1 IW GRD frame from the NASA ASF catalog (ESA Copernicus). "
    "A pass footprint, not a ship name. Sample of recent IW frames, not "
    "every Sentinel-1 scene. Public browse is too coarse to resolve hulls. "
    "Not satellite AIS. Not navigation."
)
_COVERAGE = (
    "Radar looked here. Terrestrial AIS did not. Hull identity is a hole."
)


def fetch_radar() -> list[Entity] | None:
    """None = catalog failed. Empty list = no recent gyre passes."""
    end = datetime.now(UTC)
    start = end - timedelta(days=_LOOKBACK_DAYS)
    chunks: list[dict[str, Any]] = []
    any_ok = False
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = [
            pool.submit(_search_box, wkt, start, end) for wkt in _OCEAN_WKT
        ]
        for fut in as_completed(futs):
            payload = fut.result()
            if payload is None:
                continue
            any_ok = True
            chunks.append(payload)
    if not any_ok:
        return None
    features: list[dict[str, Any]] = []
    for payload in chunks:
        rows = payload.get("features")
        if isinstance(rows, list):
            features.extend(row for row in rows if isinstance(row, dict))
    return entities_from_features(features)


def entities_from_features(features: list[dict[str, Any]]) -> list[Entity]:
    """Last scene id wins. Cap the plate, not the ocean."""
    by_id: dict[str, Entity] = {}
    for feat in features:
        entity = _entity_from_feature(feat)
        if entity is None:
            continue
        by_id[entity.id] = entity
        if len(by_id) >= _CAP:
            break
    return list(by_id.values())


def _entity_from_feature(feat: dict[str, Any]) -> Entity | None:
    props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
    lat = _num(props.get("centerLat"))
    lon = _num(props.get("centerLon"))
    ring = _ring_ll(feat.get("geometry"))
    if lat is None or lon is None:
        lat, lon = _centroid(ring)
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    scene = str(props.get("sceneName") or props.get("fileID") or "").strip()
    if not scene:
        return None
    when = _unix_from_iso(props.get("startTime"))
    pos = lla_to_ecef(lat, lon, 0.0)
    platform = str(props.get("platform") or "Sentinel-1").strip()
    stamp = str(props.get("startTime") or "")[:19].replace("T", " ")
    label = f"{platform} pass" if not stamp else f"{platform} {stamp}Z"
    meta: dict[str, Any] = {
        "lat": lat,
        "lon": lon,
        "scene": scene,
        "platform": platform,
    }
    if ring:
        meta["footprint_ll"] = ring
    return Entity(
        id=f"s1:{scene[:80]}",
        cls="site",
        layer="radar",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        when_unix=when,
        source="NASA ASF DAAC",
        freshness="delayed",
        confidence=0.8,
        cite=_CITE,
        meta=meta,
        coverage=Coverage("pass", _COVERAGE),
    )


def _ring_ll(geom: Any) -> list[list[float]]:
    if not isinstance(geom, dict):
        return []
    coords = geom.get("coordinates")
    if geom.get("type") == "Polygon" and isinstance(coords, list) and coords:
        raw = coords[0]
    elif geom.get("type") == "LineString" and isinstance(coords, list):
        raw = coords
    else:
        return []
    out: list[list[float]] = []
    seen: set[tuple[float, float]] = set()
    for pair in raw:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        lon = _num(pair[0])
        lat = _num(pair[1])
        if lat is None or lon is None:
            continue
        key = (round(lat, 5), round(lon, 5))
        if key in seen:
            continue
        seen.add(key)
        out.append([lat, lon])
    return out


def _centroid(ring: list[list[float]]) -> tuple[float | None, float | None]:
    if len(ring) < 3:
        return None, None
    lat = sum(p[0] for p in ring) / len(ring)
    lon = sum(p[1] for p in ring) / len(ring)
    return lat, lon


def _unix_from_iso(stamp: Any) -> float:
    if not isinstance(stamp, str) or not stamp.strip():
        return 0.0
    text = stamp.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


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
    return name == ASF_HOST or name.endswith("." + ASF_HOST)


def _search_box(wkt: str, start: datetime, end: datetime) -> dict[str, Any] | None:
    if not _host_pinned(urlparse(ASF_SEARCH).hostname):
        return None
    params = {
        "platform": "SENTINEL-1",
        "processingLevel": "GRD_HD",
        "beamMode": "IW",
        "intersectsWith": wkt,
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "maxResults": str(_PER_BOX),
        "output": "geojson",
    }
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                ASF_SEARCH,
                params=params,
                headers={"User-Agent": _UA},
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
