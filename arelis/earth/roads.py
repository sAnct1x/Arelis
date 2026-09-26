"""Named roads on the planet. Overlay, not a basemap swap.

Overpass highways in the look fabric. Cesium draws them on GIBS /
photoreal. The OSM carto raster stays off the globe — that is a
drawing, not the Earth. Hosts already pinned. Failures leave the disc.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.osm import (
    OVERPASS,
    OVERPASS_FALLBACK,
    OVERPASS_FALLBACK_HOST,
    OVERPASS_HOST,
)
from arelis.paths import state_dir

_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 12.0
_TTL_S = 900.0
_CAP = 600
_FABRIC = {"city": 0.04}
_CACHE = state_dir() / "earth" / "roads"
_inflight: set[str] = set()
_lock = threading.Lock()
_generation = 0
_ways: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_MAJOR = ("motorway", "trunk", "primary", "secondary")
_CITY = (*_MAJOR, "tertiary", "residential", "unclassified")


def road_generation() -> int:
    return _generation


def _grain(alt_m: float) -> str:
    from arelis.earth.lod import STREET_NAME_ALT_M

    return "names" if float(alt_m) <= STREET_NAME_ALT_M else "major"


def cache_key(lat: float, lon: float, band: str, *, alt_m: float = 0.0) -> str:
    return (
        f"{band}_{_grain(alt_m)}_"
        f"{round(float(lat) * 20.0) / 20.0:.2f}_"
        f"{round(float(lon) * 20.0) / 20.0:.2f}"
    )


def ways_from_overpass(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Named or classed highway ways. Tests use a tiny fixture."""
    out: list[dict[str, Any]] = []
    for el in payload.get("elements") or []:
        if not isinstance(el, dict) or str(el.get("type") or "") != "way":
            continue
        tags = el.get("tags") if isinstance(el.get("tags"), dict) else {}
        kind = str(tags.get("highway") or "").strip().lower()
        if not kind:
            continue
        geom = el.get("geometry")
        if not isinstance(geom, list) or len(geom) < 2:
            continue
        pts: list[list[float]] = []
        for pt in geom:
            if not isinstance(pt, dict):
                continue
            try:
                pts.append([float(pt["lat"]), float(pt["lon"])])
            except (KeyError, TypeError, ValueError):
                continue
        if len(pts) < 2:
            continue
        name = str(tags.get("name") or tags.get("ref") or "").strip()
        out.append({"kind": kind, "name": name, "pts": pts})
        if len(out) >= _CAP:
            break
    return out


def roads_for_view(
    lat: float, lon: float, band: str, *, alt_m: float = 0.0
) -> list[dict[str, Any]]:
    from arelis.earth.lod import ROAD_ALT_M

    if band not in _FABRIC:
        return []
    if float(alt_m) > ROAD_ALT_M:
        return []
    key = cache_key(lat, lon, band, alt_m=alt_m)
    hit = _ways.get(key)
    now = time.time()
    if hit is not None and now - hit[0] < _TTL_S:
        return hit[1]
    cached = _read_cache(key)
    if cached is not None:
        _ways[key] = cached
        if now - cached[0] < _TTL_S:
            return cached[1]
    schedule_fetch(key, lat, lon, band, alt_m=alt_m)
    return cached[1] if cached is not None else []


def schedule_fetch(
    key: str, lat: float, lon: float, band: str, *, alt_m: float = 0.0
) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    with _lock:
        if key in _inflight:
            return
        _inflight.add(key)
    threading.Thread(
        target=_fetch_one,
        args=(key, lat, lon, band, alt_m),
        daemon=True,
        name="earth-roads",
    ).start()


def _bbox(lat: float, lon: float, band: str) -> tuple[float, float, float, float]:
    half = _FABRIC.get(band, 0.05)
    lat = max(-90.0, min(90.0, float(lat)))
    lon = ((float(lon) + 180.0) % 360.0) - 180.0
    south = max(-90.0, lat - half)
    north = min(90.0, lat + half)
    west = ((lon - half + 180.0) % 360.0) - 180.0
    east = ((lon + half + 180.0) % 360.0) - 180.0
    return south, west, north, east


def _read_cache(key: str) -> tuple[float, list[dict[str, Any]]] | None:
    path = _CACHE / f"{key}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    try:
        unix = float(raw.get("unix") or 0.0)
    except (TypeError, ValueError):
        return None
    rows = raw.get("ways") or []
    if not isinstance(rows, list):
        return None
    return (unix, [row for row in rows if isinstance(row, dict)])


def _host_pinned(host: str | None, pin: str) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == pin or name.endswith("." + pin)


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


def _fetch_one(key: str, lat: float, lon: float, band: str, alt_m: float) -> None:
    try:
        south, west, north, east = _bbox(lat, lon, band)
        kinds = "|".join(_CITY if _grain(alt_m) == "names" else _MAJOR)
        query = (
            f'[out:json][timeout:10];'
            f'way["highway"~"^({kinds})$"]({south},{west},{north},{east});'
            f"out geom {_CAP};"
        )
        payload = _post(OVERPASS, OVERPASS_HOST, query) or _post(
            OVERPASS_FALLBACK, OVERPASS_FALLBACK_HOST, query
        )
        if payload is None:
            return
        ways = ways_from_overpass(payload)
        dest = _CACHE / f"{key}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        dest.write_text(
            json.dumps({"unix": now, "ways": ways}),
            encoding="utf-8",
        )
        _ways[key] = (now, ways)
        global _generation
        with _lock:
            _generation += 1
    except Exception:
        pass
    finally:
        with _lock:
            _inflight.discard(key)


def _cache_dir_for_tests(path: Path) -> None:
    global _CACHE, _generation
    _CACHE = path
    _ways.clear()
    _generation = 0
