"""Tide / sea-level station catalogs. Public JSON. No key.

NOAA CO-OPS water-level stations plus IOC-UNESCO gauge pins.
Published gauges only. Open ocean between them is a hole.
Failures return None. Hosts pinned in tests/test_egress.py.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

COOPS = (
    "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/"
    "stations.json?type=tidepredictions"
)
COOPS_HOST = "api.tidesandcurrents.noaa.gov"
IOC = "https://www.ioc-sealevelmonitoring.org/service.php?query=stationlist&format=json"
IOC_HOST = "www.ioc-sealevelmonitoring.org"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 12.0
_CAP = 400
_COOPS_CITE = (
    "NOAA CO-OPS tide-prediction stations. Published gauges. "
    "Coastal / territorial. Open ocean is a hole. Not a hull."
)
_IOC_CITE = (
    "IOC-UNESCO sea-level station list. Published gauges. "
    "Open ocean between stations is a hole. Not altimetry everywhere."
)


def fetch_tides() -> list[Entity] | None:
    chunks: list[list[Entity] | None] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(_fetch_coops), pool.submit(_fetch_ioc)]
        for fut in as_completed(futs):
            chunks.append(fut.result())
    if all(chunk is None for chunk in chunks):
        return None
    out: list[Entity] = []
    seen: set[str] = set()
    for chunk in chunks:
        for entity in chunk or []:
            if entity.id in seen:
                continue
            seen.add(entity.id)
            out.append(entity)
            if len(out) >= _CAP:
                return out
    return out or None


def entities_from_coops(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("stations")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_coops(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def entities_from_ioc(rows: list[Any]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_ioc(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_coops(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("lat") or row.get("latitude"))
    lon = _num(row.get("lng") or row.get("lon") or row.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    sid = str(row.get("id") or row.get("stationId") or "").strip()
    name = str(row.get("name") or sid).strip()
    if not sid:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"coops:{sid}",
        cls="weather",
        layer="weather",
        label=name[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="NOAA CO-OPS",
        freshness="reconstructed",
        confidence=0.7,
        cite=_COOPS_CITE,
        meta={"lat": lat, "lon": lon, "station": sid},
        coverage=Coverage(
            "station",
            "Published tide gauge. Open ocean between stations is a hole.",
        ),
    )


def _entity_from_ioc(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("Lat") or row.get("lat") or row.get("latitude"))
    lon = _num(row.get("Lon") or row.get("lon") or row.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    sid = str(row.get("Code") or row.get("code") or row.get("id") or "").strip()
    name = str(row.get("Location") or row.get("location") or row.get("name") or sid).strip()
    if not sid:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"ioc:{sid.casefold()}",
        cls="weather",
        layer="weather",
        label=name[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="IOC sea level",
        freshness="reconstructed",
        confidence=0.65,
        cite=_IOC_CITE,
        meta={"lat": lat, "lon": lon, "station": sid},
        coverage=Coverage(
            "station",
            "Published sea-level gauge. Not altimetry. Mid-ocean is a hole.",
        ),
    )


def _fetch_coops() -> list[Entity] | None:
    payload = _get_json(COOPS, COOPS_HOST)
    if not isinstance(payload, dict):
        return None
    return entities_from_coops(payload) or None


def _fetch_ioc() -> list[Entity] | None:
    payload = _get_json(IOC, IOC_HOST)
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        raw = payload.get("stations") or payload.get("data") or []
        rows = raw if isinstance(raw, list) else []
    else:
        return None
    return entities_from_ioc(rows) or None


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
            resp = client.get(url, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, pin):
                return None
            return resp.json()
    except Exception:
        return None
