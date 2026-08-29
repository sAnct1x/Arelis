"""OSM-tagged public webcams. Mapper catalog. Positions only.

camera:type=webcam nodes/ways. No still, no stream URL in meta.
© OpenStreetMap contributors, ODbL. Failures return None.
Hosts pinned in tests/test_egress.py.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef
from arelis.earth.viewshed import attach_viewshed

OVERPASS = "https://overpass-api.de/api/interpreter"
OVERPASS_HOST = "overpass-api.de"
OVERPASS_FALLBACK = "https://overpass.kumi.systems/api/interpreter"
OVERPASS_FALLBACK_HOST = "overpass.kumi.systems"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 18.0
_CAP = 4000
_PER_BOX = 200
# Denser inhabited boxes. Mapper catalog, not a surveillance scrape.
# south, west, north, east. Split continents so the per-box cap does not
# starve cities. Public city/region extents, not a house.
_BOXES: tuple[tuple[float, float, float, float], ...] = (
    (24.0, -125.0, 42.0, -100.0),
    (24.0, -100.0, 42.0, -80.0),
    (24.0, -80.0, 42.0, -66.0),
    (42.0, -125.0, 50.0, -95.0),
    (42.0, -95.0, 50.0, -66.0),
    (48.0, -140.0, 72.0, -95.0),
    (48.0, -95.0, 72.0, -52.0),
    (18.0, -161.0, 23.0, -154.0),
    (14.0, -118.0, 33.0, -102.0),
    (14.0, -102.0, 33.0, -86.0),
    (7.0, -93.0, 27.0, -77.0),
    (7.0, -77.0, 27.0, -59.0),
    (-56.0, -82.0, -20.0, -60.0),
    (-20.0, -82.0, 13.0, -60.0),
    (-35.0, -60.0, 5.0, -34.0),
    (36.0, -12.0, 54.0, 10.0),
    (36.0, 10.0, 54.0, 32.0),
    (54.0, -12.0, 72.0, 32.0),
    (30.0, -10.0, 44.0, 20.0),
    (-35.0, -18.0, 5.0, 20.0),
    (5.0, -18.0, 38.0, 20.0),
    (-35.0, 20.0, 5.0, 52.0),
    (5.0, 20.0, 38.0, 52.0),
    (12.0, 32.0, 42.0, 48.0),
    (12.0, 48.0, 42.0, 63.0),
    (41.0, 27.0, 72.0, 45.0),
    (41.0, 45.0, 72.0, 60.0),
    (50.0, 60.0, 75.0, 90.0),
    (50.0, 90.0, 75.0, 120.0),
    (50.0, 120.0, 75.0, 150.0),
    (50.0, 150.0, 75.0, 180.0),
    (35.0, 50.0, 55.0, 70.0),
    (35.0, 70.0, 55.0, 87.0),
    (5.0, 60.0, 25.0, 80.0),
    (25.0, 60.0, 37.0, 80.0),
    (5.0, 80.0, 37.0, 97.0),
    (-11.0, 95.0, 8.0, 120.0),
    (8.0, 95.0, 28.0, 120.0),
    (-11.0, 120.0, 28.0, 141.0),
    (20.0, 100.0, 35.0, 123.0),
    (35.0, 100.0, 50.0, 123.0),
    (20.0, 123.0, 50.0, 146.0),
    (24.0, 122.0, 46.0, 146.0),
    (33.0, 124.0, 43.0, 132.0),
    (21.0, 119.0, 26.0, 123.0),
    (-45.0, 112.0, -26.0, 135.0),
    (-45.0, 135.0, -26.0, 155.0),
    (-26.0, 112.0, -10.0, 155.0),
    (-48.0, 165.0, -33.0, 179.0),
    (-47.0, 166.0, -34.0, 179.0),
    (1.0, 103.0, 7.0, 105.0),
    (14.0, 120.0, 19.0, 122.0),
    (63.0, -25.0, 67.0, -13.0),
    (-26.0, 43.0, -12.0, 51.0),
    (-21.0, 176.0, -15.0, 180.0),
    (-21.0, -180.0, -15.0, -170.0),
    (59.0, -54.0, 72.0, -42.0),
    (36.5, -32.0, 40.0, -24.0),
    (27.5, -19.0, 29.5, -13.0),
    (-22.0, 55.0, -19.5, 58.0),
    (4.0, 114.0, 8.0, 127.0),
    (-18.0, 145.0, -10.0, 168.0),
    (12.0, -70.0, 19.0, -59.0),
    (50.0, -11.0, 60.0, 2.0),
    (35.0, 24.0, 42.0, 30.0),
    (-35.0, 17.5, -28.0, 27.0),
    (21.0, 39.0, 32.0, 55.0),
    (-45.0, -76.0, -32.0, -68.0),
)
_CITE = (
    "OpenStreetMap camera:type=webcam. © OpenStreetMap contributors (ODbL). "
    "Worldwide mapper catalog, not a crawl. Position only. No still, no stream."
)


def fetch_osm_webcams() -> list[Entity] | None:
    chunks: list[dict[str, Any]] = []
    any_ok = False
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_query_box, box) for box in _BOXES]
        for fut in as_completed(futs):
            payload = fut.result()
            if payload is None:
                continue
            any_ok = True
            chunks.append(payload)
    if not any_ok:
        return None
    rows: list[dict[str, Any]] = []
    for payload in chunks:
        els = payload.get("elements")
        if isinstance(els, list):
            rows.extend(el for el in els if isinstance(el, dict))
    return entities_from_elements(rows)


def entities_from_elements(rows: list[dict[str, Any]]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        entity = _entity_from_el(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(attach_viewshed(entity))
        if len(out) >= _CAP:
            break
    return out


def _entity_from_el(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("lat"))
    lon = _num(row.get("lon"))
    center = row.get("center") if isinstance(row.get("center"), dict) else {}
    if lat is None:
        lat = _num(center.get("lat"))
    if lon is None:
        lon = _num(center.get("lon"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    kind = str(row.get("type") or "node")
    oid = str(row.get("id") or "").strip()
    if not oid:
        return None
    tags = row.get("tags") if isinstance(row.get("tags"), dict) else {}
    name = str(tags.get("name") or tags.get("webcam") or "webcam").strip()
    pos = lla_to_ecef(lat, lon, 12.0)
    return Entity(
        id=f"osm:{kind}:{oid}",
        cls="camera",
        layer="cameras",
        label=name[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="OpenStreetMap",
        freshness="reconstructed",
        confidence=0.55,
        cite=_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "pin",
            "OSM webcam tag. No video. Pose unknown unless a prior exists.",
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


def _host_pinned(host: str | None, pin: str) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == pin or name.endswith("." + pin)


def _query_box(box: tuple[float, float, float, float]) -> dict[str, Any] | None:
    south, west, north, east = box
    query = (
        f'[out:json][timeout:15];'
        f'nwr["camera:type"="webcam"]({south},{west},{north},{east});'
        f"out center {_PER_BOX};"
    )
    return _post(OVERPASS, OVERPASS_HOST, query) or _post(
        OVERPASS_FALLBACK, OVERPASS_FALLBACK_HOST, query
    )


def _post(url: str, pin: str, query: str) -> dict[str, Any] | None:
    if not _host_pinned(urlparse(url).hostname, pin):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.post(
                url,
                data={"data": query},
                headers={"User-Agent": _UA},
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, pin):
                return None
            payload = resp.json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None
