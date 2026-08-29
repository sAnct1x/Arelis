"""OpenStreetMap raster tiles on the Earth disc. Optional. ODbL.

tile.openstreetmap.org, cached under state/earth/osm-tiles. User-Agent
required. At most two in-flight fetches. Failures leave the NASA albedo.
Never required to see coverage holes. Host pinned in tests/test_egress.py.
"""

from __future__ import annotations

import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.paths import state_dir

OSM_TILE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_TILE_HOST = "tile.openstreetmap.org"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 8.0
_MAX_ZOOM = 12
_MIN_ZOOM = 3
_CACHE = state_dir() / "earth" / "osm-tiles"
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="earth-osm")
_inflight: set[tuple[int, int, int]] = set()
_lock = threading.Lock()


def zoom_for_disc(px_r: float) -> int:
    """Street tiles only when the globe is large on the plate."""
    if px_r < 220.0:
        return _MIN_ZOOM
    if px_r < 360.0:
        return 5
    if px_r < 520.0:
        return 7
    if px_r < 760.0:
        return 9
    return min(_MAX_ZOOM, 11)


def latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int, int]:
    lat = max(-85.0511, min(85.0511, lat))
    lon = ((lon + 180.0) % 360.0) - 180.0
    n = 2.0 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(lat)
    y = int(
        (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi)
        / 2.0
        * n
    )
    n_i = 1 << zoom
    return (zoom, x % n_i, max(0, min(n_i - 1, y)))


def tile_corners(z: int, x: int, y: int) -> list[tuple[float, float]]:
    """NW, NE, SE, SW as (lat, lon)."""
    n = 2.0 ** z
    def lon_of(tx: int) -> float:
        return tx / n * 360.0 - 180.0

    def lat_of(ty: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * ty / n))))

    west, east = lon_of(x), lon_of(x + 1)
    north, south = lat_of(y), lat_of(y + 1)
    return [(north, west), (north, east), (south, east), (south, west)]


def tiles_for_view(
    lat: float, lon: float, zoom: int, *, radius: int = 1
) -> list[dict[str, Any]]:
    """Cached tiles around a pin. Misses schedule a fetch and are omitted."""
    z, cx, cy = latlon_to_tile(lat, lon, zoom)
    n = 1 << z
    out: list[dict[str, Any]] = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            tx = (cx + dx) % n
            ty = cy + dy
            if ty < 0 or ty >= n:
                continue
            png = cached_png(z, tx, ty)
            if png is None:
                schedule_fetch(z, tx, ty)
                continue
            out.append(
                {
                    "z": z,
                    "x": tx,
                    "y": ty,
                    "png": png,
                    "corners": tile_corners(z, tx, ty),
                }
            )
    return out


def cached_png(z: int, x: int, y: int) -> bytes | None:
    path = _CACHE / str(z) / str(x) / f"{y}.png"
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data if len(data) > 32 else None


def schedule_fetch(z: int, x: int, y: int) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    key = (z, x, y)
    with _lock:
        if key in _inflight:
            return
        if cached_png(z, x, y) is not None:
            return
        _inflight.add(key)
    _POOL.submit(_fetch_one, z, x, y)


def _fetch_one(z: int, x: int, y: int) -> None:
    key = (z, x, y)
    try:
        url = OSM_TILE.format(z=z, x=x, y=y)
        if not _host_pinned(urlparse(url).hostname, OSM_TILE_HOST):
            return
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, OSM_TILE_HOST):
                return
            ctype = (resp.headers.get("content-type") or "").lower()
            png_ok = "png" in ctype or resp.content[:8] == b"\x89PNG\r\n\x1a\n"
            if not png_ok:
                return
            dest = _CACHE / str(z) / str(x) / f"{y}.png"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
    except Exception:
        return
    finally:
        with _lock:
            _inflight.discard(key)


def _host_pinned(host: str | None, pin: str) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == pin or name.endswith("." + pin)
