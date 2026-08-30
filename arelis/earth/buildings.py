"""City-band building footprints. Not a live feed. Not a house index.

Overpass ways tagged building, boxed to a tight fabric around the look
pin (~0.04°). Cached under state/earth/buildings. Chip off = no fetch.
Birds-eye outlines only — no labels, no extrusion, no Zillow.

Hosts already pinned in tests/test_egress.py. Failures leave the disc.
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
_CAP = 2000
_FABRIC_HALF = 0.04
_CACHE = state_dir() / "earth" / "buildings"
_inflight: set[str] = set()
_lock = threading.Lock()
_rings: dict[str, tuple[float, list[list[tuple[float, float]]]]] = {}


def fabric_bbox(lat: float, lon: float) -> tuple[float, float, float, float]:
    """Tight look-pin box. Not the 1.2° city live box."""
    lat = max(-90.0, min(90.0, float(lat)))
    lon = ((float(lon) + 180.0) % 360.0) - 180.0
    south = max(-90.0, lat - _FABRIC_HALF)
    north = min(90.0, lat + _FABRIC_HALF)
    west = ((lon - _FABRIC_HALF + 180.0) % 360.0) - 180.0
    east = ((lon + _FABRIC_HALF + 180.0) % 360.0) - 180.0
    return south, west, north, east


def cache_key(lat: float, lon: float) -> str:
    return f"{round(float(lat), 2):.2f}_{round(float(lon), 2):.2f}"


def rings_from_overpass(payload: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Lat/lon rings from an Overpass JSON dump. Tests use a tiny fixture."""
    out: list[list[tuple[float, float]]] = []
    for el in payload.get("elements") or []:
        if not isinstance(el, dict):
            continue
        if str(el.get("type") or "") != "way":
            continue
        geom = el.get("geometry")
        if not isinstance(geom, list) or len(geom) < 3:
            continue
        ring: list[tuple[float, float]] = []
        for pt in geom:
            if not isinstance(pt, dict):
                continue
            try:
                lat = float(pt["lat"])
                lon = float(pt["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            ring.append((lat, lon))
        if len(ring) >= 3:
            out.append(ring)
        if len(out) >= _CAP:
            break
    return out


def footprints_for_view(
    lat: float, lon: float, band: str
) -> list[list[tuple[float, float]]]:
    """Cached footprints at the look pin. Misses schedule a fetch."""
    if band != "city":
        return []
    key = cache_key(lat, lon)
    hit = _rings.get(key)
    now = time.time()
    if hit is not None and now - hit[0] < _TTL_S:
        return hit[1]
    cached = _read_cache(key)
    if cached is not None:
        _rings[key] = cached
        if now - cached[0] < _TTL_S:
            return cached[1]
    schedule_fetch(key, lat, lon)
    return cached[1] if cached is not None else []


def schedule_fetch(key: str, lat: float, lon: float) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    with _lock:
        if key in _inflight:
            return
        _inflight.add(key)
    threading.Thread(
        target=_fetch_one,
        args=(key, lat, lon),
        daemon=True,
        name="earth-buildings",
    ).start()


def _read_cache(key: str) -> tuple[float, list[list[tuple[float, float]]]] | None:
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
    rings: list[list[tuple[float, float]]] = []
    for item in raw.get("rings") or []:
        if not isinstance(item, list) or len(item) < 3:
            continue
        ring: list[tuple[float, float]] = []
        for pair in item:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                ring.append((float(pair[0]), float(pair[1])))
            except (TypeError, ValueError):
                continue
        if len(ring) >= 3:
            rings.append(ring)
    return (unix, rings) if rings else None


def _fetch_one(key: str, lat: float, lon: float) -> None:
    try:
        south, west, north, east = fabric_bbox(lat, lon)
        query = (
            f'[out:json][timeout:10];'
            f'way["building"]({south},{west},{north},{east});'
            f"out geom {_CAP};"
        )
        payload = _post(OVERPASS, OVERPASS_HOST, query) or _post(
            OVERPASS_FALLBACK, OVERPASS_FALLBACK_HOST, query
        )
        if payload is None:
            try:
                from arelis.physics.telemetry import emit

                emit("buildings_fetch", ok=False, n=0, band="city")
            except Exception:
                pass
            return
        rings = rings_from_overpass(payload)
        dest = _CACHE / f"{key}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        dest.write_text(
            json.dumps({"unix": now, "rings": rings}),
            encoding="utf-8",
        )
        _rings[key] = (now, rings)
        try:
            from arelis.physics.telemetry import emit

            emit("buildings_fetch", ok=True, n=len(rings), band="city")
        except Exception:
            pass
    except Exception as exc:
        try:
            from arelis.physics.telemetry import emit

            emit("buildings_fetch", ok=False, err=type(exc).__name__, band="city")
        except Exception:
            pass
    finally:
        with _lock:
            _inflight.discard(key)


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


def _cache_dir_for_tests(path: Path) -> None:
    """Test hook. Do not use from adapters."""
    global _CACHE
    _CACHE = path
    _rings.clear()
