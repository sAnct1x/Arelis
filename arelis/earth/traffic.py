"""Lane closures and published road disruptions. Not individual cars.

Caltrans LCS plus TfL Road Disruption. Operator catalogs, not VINs.
Failures return None so the simulated flow sketch stays.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

CALTRANS_HOST = "cwwp2.dot.ca.gov"
CALTRANS_LCS = tuple(
    f"https://cwwp2.dot.ca.gov/data/d{d}/lcs/lcsStatusD{d:02d}.json"
    for d in range(1, 13)
)
TFL_ROAD = "https://api.tfl.gov.uk/Road/all/Disruption"
TFL_HOST = "api.tfl.gov.uk"
FI_TRAFFIC = "https://tie.digitraffic.fi/api/traffic-message/v1/messages"
FI_HOST = "tie.digitraffic.fi"

_TIMEOUT = 8.0
_CAP = 1200
_CITE = (
    "Caltrans lane-closure / work-zone catalog. Operator JSON, not a VIN "
    "index. Individual cars are not in this feed."
)
_TFL_CITE = (
    "TfL Road Disruption. Operator catalog, not a VIN index. "
    "Individual cars are not in this feed."
)
_FI_CITE = (
    "Fintraffic traffic messages. Finnish roads. CC BY 4.0. "
    "Not a VIN index. Individual cars are not in this feed."
)


def fetch_traffic() -> list[Entity] | None:
    cal = _fetch_caltrans()
    tfl = _fetch_tfl()
    finland = _fetch_finland()
    if cal is None and tfl is None and finland is None:
        return None
    out: list[Entity] = []
    seen: set[str] = set()
    for entity in (cal or []) + (tfl or []) + (finland or []):
        if entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _fetch_caltrans() -> list[Entity] | None:
    out: list[Entity] = []
    seen: set[str] = set()
    any_ok = False
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(_get_json, url, CALTRANS_HOST) for url in CALTRANS_LCS]
        for fut in as_completed(futs):
            payload = fut.result()
            if not isinstance(payload, dict):
                continue
            any_ok = True
            for entity in entities_from_lcs(payload):
                if entity.id in seen:
                    continue
                seen.add(entity.id)
                out.append(entity)
                if len(out) >= _CAP:
                    return out
    if not any_ok:
        return None
    return out


def entities_from_lcs(payload: dict[str, Any]) -> list[Entity]:
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
    block = row.get("lcs") if isinstance(row.get("lcs"), dict) else row
    loc = block.get("location") if isinstance(block.get("location"), dict) else {}
    lat = _num(loc.get("latitude"))
    lon = _num(loc.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    idx = str(block.get("index") or loc.get("locationName") or "").strip()
    name = str(loc.get("locationName") or idx).strip()
    route = str(loc.get("route") or loc.get("freewayBegin") or "").strip()
    district = str(loc.get("district") or "").strip()
    if not idx and not name:
        return None
    label = name if not route else f"{name} {route}"
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"lcs:{district or 'x'}:{idx or name.casefold()[:32]}",
        cls="traffic",
        layer="traffic",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Caltrans LCS",
        freshness="delayed",
        confidence=0.7,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "route": route},
        coverage=Coverage(
            "incident",
            "Published closure / work zone. Not a car. Not a plate.",
        ),
    )


def _fetch_tfl() -> list[Entity] | None:
    payload = _get_json(TFL_ROAD, TFL_HOST)
    if not isinstance(payload, list):
        return None
    return entities_from_tfl([row for row in payload if isinstance(row, dict)])


def entities_from_tfl(rows: list[dict[str, Any]]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        entity = _entity_from_tfl(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _fetch_finland() -> list[Entity] | None:
    payload = _get_json(FI_TRAFFIC, FI_HOST)
    if not isinstance(payload, dict):
        return None
    pins = entities_from_finland(payload)
    return pins or None


def entities_from_finland(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_fi(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_fi(feat: dict[str, Any]) -> Entity | None:
    props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
    geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
    lat, lon = _geom_ll(geom)
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    cid = str(props.get("situationId") or feat.get("id") or "").strip()
    title = str(props.get("title") or props.get("situationType") or cid).strip()
    if not cid and not title:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"fi-road:{cid or title.casefold()[:40]}",
        cls="traffic",
        layer="traffic",
        label=title[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Fintraffic traffic-message",
        freshness="delayed",
        confidence=0.7,
        cite=_FI_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "incident",
            "Published traffic message. Not a car. Not a plate.",
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
    if isinstance(first, (list, tuple)) and len(first) >= 2:
        if isinstance(first[0], (list, tuple)):
            return _num(first[0][1]), _num(first[0][0])
        return _num(first[1]), _num(first[0])
    return None, None


def _entity_from_tfl(row: dict[str, Any]) -> Entity | None:
    lat, lon = _tfl_ll(row)
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    eid = str(row.get("id") or row.get("guid") or "").strip()
    loc = str(row.get("location") or row.get("commonName") or "").strip()
    cat = str(row.get("category") or row.get("severity") or "").strip()
    if not eid and not loc:
        return None
    label = loc or eid
    if cat and cat.casefold() not in label.casefold():
        label = f"{cat} {label}"
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"tfl-road:{eid or loc.casefold()[:40]}",
        cls="traffic",
        layer="traffic",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="TfL Road Disruption",
        freshness="delayed",
        confidence=0.7,
        cite=_TFL_CITE,
        meta={"lat": lat, "lon": lon},
        coverage=Coverage(
            "incident",
            "Published disruption. Not a car. Not a plate.",
        ),
    )


def _tfl_ll(row: dict[str, Any]) -> tuple[float | None, float | None]:
    lat = _num(row.get("latitude") or row.get("lat"))
    lon = _num(row.get("longitude") or row.get("lon") or row.get("lng"))
    if lat is not None and lon is not None:
        return lat, lon
    for key in ("geography", "geometry", "point"):
        geom = row.get(key)
        if not isinstance(geom, dict):
            continue
        coords = geom.get("coordinates")
        if isinstance(coords, list) and coords:
            first = coords[0]
            if geom.get("type") == "Point" and len(coords) >= 2:
                return _num(coords[1]), _num(coords[0])
            if isinstance(first, (list, tuple)) and len(first) >= 2:
                return _num(first[1]), _num(first[0])
    return None, None


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


def _get_json(url: str, pin: str) -> Any:
    if not _host_pinned(urlparse(url).hostname, pin):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "ArelisEarth/0.2"})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, pin):
                return None
            return resp.json()
    except Exception:
        return None
