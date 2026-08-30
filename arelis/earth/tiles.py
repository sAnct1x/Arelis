"""Ground imagery on the Earth disc.

NASA GIBS Blue Marble Next Generation is the nadir fabric once you have
fallen in — a published mosaic, not a live pass and not Cesium ion.
OSM streets stay the Streets chip (ODbL). Hosts pinned in
tests/test_egress.py. Failures leave the NASA albedo sphere.
"""

from __future__ import annotations

import math
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.paths import state_dir

Source = Literal["osm", "gibs"]

OSM_TILE = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_TILE_HOST = "tile.openstreetmap.org"
GIBS_HOST = "gibs.earthdata.nasa.gov"
GIBS_BLUE = (
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
    "BlueMarble_NextGeneration/default/GoogleMapsCompatible_Level8/"
    "{z}/{y}/{x}.jpeg"
)
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 8.0
_MAX_ZOOM = 15
_GIBS_MAX_ZOOM = 8
_MIN_ZOOM = 3
_CACHE = {
    "osm": state_dir() / "earth" / "osm-tiles",
    "gibs": state_dir() / "earth" / "gibs-tiles",
}
_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="earth-tile")
_inflight: set[tuple[str, int, int, int]] = set()
_lock = threading.Lock()
_generation = 0


def tile_generation() -> int:
    """Bumps when a tile lands so the plate can wake without a 30 Hz idle."""
    return _generation


def want_ground(px_r: float, band: str = "") -> bool:
    """True once the albedo is too coarse to be the map."""
    return band in {"approach", "near", "city"} or px_r >= 140.0


def zoom_for_disc(px_r: float, band: str = "") -> int:
    """Street tiles when you have fallen toward land. Coarse from farther out."""
    if band == "city":
        return min(_MAX_ZOOM, 15)
    if band == "near":
        return min(_MAX_ZOOM, 14)
    if px_r < 160.0:
        return _MIN_ZOOM
    if px_r < 280.0:
        return 5
    if px_r < 420.0:
        return 7
    if px_r < 640.0:
        return 9
    return 11


def zoom_for_ground(px_r: float, band: str = "") -> int:
    """GIBS Blue Marble maxes at z8. Match the look box, not street GSD."""
    if band == "city" or px_r >= 640.0:
        return _GIBS_MAX_ZOOM
    if band == "near" or px_r >= 420.0:
        return 7
    if band == "approach" or px_r >= 220.0:
        return 6
    if px_r >= 140.0:
        return 5
    return 4


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
    lat: float,
    lon: float,
    zoom: int,
    *,
    radius: int = 1,
    source: Source = "osm",
) -> list[dict[str, Any]]:
    """Cached tiles around a pin. Misses schedule a fetch and are omitted."""
    if source == "gibs":
        zoom = min(int(zoom), _GIBS_MAX_ZOOM)
    z, cx, cy = latlon_to_tile(lat, lon, zoom)
    n = 1 << z
    out: list[dict[str, Any]] = []
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            tx = (cx + dx) % n
            ty = cy + dy
            if ty < 0 or ty >= n:
                continue
            blob = cached_bytes(source, z, tx, ty)
            if blob is None:
                schedule_fetch(z, tx, ty, source=source)
                continue
            out.append(
                {
                    "z": z,
                    "x": tx,
                    "y": ty,
                    "source": source,
                    "png": blob,
                    "corners": tile_corners(z, tx, ty),
                }
            )
    return out


def cached_png(z: int, x: int, y: int) -> bytes | None:
    return cached_bytes("osm", z, x, y)


def cached_bytes(source: Source, z: int, x: int, y: int) -> bytes | None:
    path = _CACHE[source] / str(z) / str(x) / f"{y}.{_ext(source)}"
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data if len(data) > 32 else None


def schedule_fetch(
    z: int, x: int, y: int, *, source: Source = "osm"
) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    key = (source, z, x, y)
    with _lock:
        if key in _inflight:
            return
        if cached_bytes(source, z, x, y) is not None:
            return
        _inflight.add(key)
    _POOL.submit(_fetch_one, source, z, x, y)


def _ext(source: Source) -> str:
    return "jpeg" if source == "gibs" else "png"


def _fetch_one(source: Source, z: int, x: int, y: int) -> None:
    key = (source, z, x, y)
    try:
        if source == "gibs":
            url = GIBS_BLUE.format(z=z, y=y, x=x)
            pin = GIBS_HOST
        else:
            url = OSM_TILE.format(z=z, x=x, y=y)
            pin = OSM_TILE_HOST
        if not _host_pinned(urlparse(url).hostname, pin):
            return
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, pin):
                return
            ctype = (resp.headers.get("content-type") or "").lower()
            raw = resp.content
            if source == "gibs":
                ok = "jpeg" in ctype or "jpg" in ctype or raw[:2] == b"\xff\xd8"
            else:
                ok = "png" in ctype or raw[:8] == b"\x89PNG\r\n\x1a\n"
            if not ok:
                return
            dest = _CACHE[source] / str(z) / str(x) / f"{y}.{_ext(source)}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            global _generation
            with _lock:
                _generation += 1
        try:
            from arelis.physics.telemetry import emit

            emit("earth_tile", source=source, z=z, x=x, y=y, ok=True, bytes=len(raw))
        except Exception:
            pass
    except Exception as exc:
        try:
            from arelis.physics.telemetry import emit

            emit(
                "earth_tile",
                source=source,
                z=z,
                x=x,
                y=y,
                ok=False,
                err=type(exc).__name__,
            )
        except Exception:
            pass
        return
    finally:
        with _lock:
            _inflight.discard(key)


def _host_pinned(host: str | None, pin: str) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == pin or name.endswith("." + pin)
