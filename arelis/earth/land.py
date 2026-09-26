"""Political geography for landfall. Not a live feed.

Natural Earth 110m countries (fill + strokes) and admin-1 lines,
plus 50m admin-1 centroids for spoken go-to, cached under
state/earth/ne. Public domain. Fetched once, then painted
as projected polygons and polylines so continents read from space —
the NASA albedo alone is too coarse once you fall toward land.

Hosts pinned in tests/test_egress.py. Failures leave the albedo.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.paths import state_dir

NE_HOST = "raw.githubusercontent.com"
NE_COUNTRIES = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_admin_0_countries.geojson"
)
NE_STATES = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_admin_1_states_provinces_lines.geojson"
)
NE_PLACES = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_110m_populated_places.geojson"
)
NE_PLACES_50M = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_populated_places.geojson"
)
NE_ADMIN1 = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
    "master/geojson/ne_50m_admin_1_states_provinces.geojson"
)
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 20.0
_CACHE = state_dir() / "earth" / "ne"
_inflight: set[str] = set()
_lock = threading.Lock()
_rings: dict[str, list[list[tuple[float, float]]]] = {}
_ecef: dict[str, tuple[object, list[list[tuple[float, float, float]]]]] = {}
_boxes: dict[str, tuple[object, list[tuple[float, float, float, float]]]] = {}
_names: dict[str, list[str]] = {}
_places: list[tuple[str, float, float]] | None = None
_places_dense: list[tuple[str, float, float]] | None = None
_admin1: list[tuple[str, float, float]] | None = None


def country_rings() -> list[list[tuple[float, float]]]:
    return _load("countries", NE_COUNTRIES)


def country_fills() -> list[list[tuple[float, float]]]:
    """Exterior rings only. Lakes stay ocean."""
    return _load("fills", NE_COUNTRIES)


def state_rings() -> list[list[tuple[float, float]]]:
    return _load("states", NE_STATES)


def rings_from_geojson(payload: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """Lat/lon rings from a FeatureCollection. Tests use a tiny fixture."""
    out: list[list[tuple[float, float]]] = []
    for feat in payload.get("features") or []:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
        kind = str(geom.get("type") or "")
        coords = geom.get("coordinates")
        if kind == "Polygon":
            out.extend(_polygon_rings(coords))
        elif kind == "MultiPolygon":
            if not isinstance(coords, list):
                continue
            for poly in coords:
                out.extend(_polygon_rings(poly))
        elif kind == "LineString":
            ring = _line_ring(coords)
            if ring:
                out.append(ring)
        elif kind == "MultiLineString":
            if not isinstance(coords, list):
                continue
            for line in coords:
                ring = _line_ring(line)
                if ring:
                    out.append(ring)
    return out


def exteriors_from_geojson(payload: dict[str, Any]) -> list[list[tuple[float, float]]]:
    """First ring of each polygon. Tests use a tiny fixture. Holes stay ocean."""
    out: list[list[tuple[float, float]]] = []
    for feat in payload.get("features") or []:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
        kind = str(geom.get("type") or "")
        coords = geom.get("coordinates")
        if kind == "Polygon":
            ring = _exterior_ring(coords)
            if ring:
                out.append(ring)
        elif kind == "MultiPolygon":
            if not isinstance(coords, list):
                continue
            for poly in coords:
                ring = _exterior_ring(poly)
                if ring:
                    out.append(ring)
    return out


def ecef_rings(
    name: str, rings: list[list[tuple[float, float]]]
) -> list[list[tuple[float, float, float]]]:
    """Unit-sphere ECEF for a named ring set. Scale by the globe radius to paint."""
    hit = _ecef.get(name)
    if hit is not None and hit[0] is rings:
        return hit[1]
    from arelis.earth.frames import lla_to_sphere

    out = [[lla_to_sphere(lat, lon, 1.0) for lat, lon in ring] for ring in rings]
    _ecef[name] = (rings, out)
    return out


def ring_boxes(
    name: str, rings: list[list[tuple[float, float]]]
) -> list[tuple[float, float, float, float]]:
    """south, north, west, east in degrees. Dateline-spanning rings are wide."""
    hit = _boxes.get(name)
    if hit is not None and hit[0] is rings:
        return hit[1]
    out: list[tuple[float, float, float, float]] = []
    for ring in rings:
        if not ring:
            out.append((0.0, 0.0, 0.0, 0.0))
            continue
        lats = [p[0] for p in ring]
        lons = [p[1] for p in ring]
        out.append((min(lats), max(lats), min(lons), max(lons)))
    _boxes[name] = (rings, out)
    return out


def fill_names() -> list[str]:
    """Names aligned with country_fills(). Empty string when the cache is old."""
    fills = country_fills()
    names = _names.get("fills")
    if names is None:
        names = _read_names("fills") or []
        _names["fills"] = names
    if len(names) != len(fills):
        return [""] * len(fills)
    return names


def places() -> list[tuple[str, float, float]]:
    """Major populated places (lat, lon). 110m Natural Earth."""
    global _places
    if _places is not None:
        return _places
    cached = _read_places()
    if cached is not None:
        _places = cached
        return cached
    schedule_fetch("places", NE_PLACES)
    return []


def places_dense() -> list[tuple[str, float, float]]:
    """Towns as well as majors. 50m Natural Earth when the cache is warm."""
    global _places_dense
    if _places_dense is not None:
        return _places_dense
    cached = _read_places("places50")
    if cached is not None:
        _places_dense = cached
        return cached
    schedule_fetch("places50", NE_PLACES_50M)
    return places()


def admin1_places() -> list[tuple[str, float, float]]:
    """States and provinces. Centroids from Natural Earth 50m when cached."""
    global _admin1
    if _admin1 is not None:
        return _admin1
    cached = _read_places("admin1")
    if cached is not None:
        _admin1 = cached
        return cached
    schedule_fetch("admin1", NE_ADMIN1)
    return []


def hit_country(lat: float, lon: float) -> str | None:
    """Point-in-polygon on country exteriors. First named hit wins."""
    fills = country_fills()
    names = fill_names()
    for ring, name in zip(fills, names, strict=False):
        if _point_in_ring(lat, lon, ring):
            return name or "country"
    return None


def nearest_place(
    lat: float, lon: float, *, max_deg: float = 1.6
) -> tuple[str, float, float] | None:
    best: tuple[str, float, float] | None = None
    best_d = max_deg * max_deg
    for name, plat, plon in places():
        dlat = plat - lat
        dlon = ((plon - lon + 180.0) % 360.0) - 180.0
        dist = dlat * dlat + dlon * dlon
        if dist < best_d:
            best_d = dist
            best = (name, plat, plon)
    return best


def schedule_land_fetch() -> None:
    """Warm the cache on enter. No-op under pytest."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    country_rings()
    country_fills()
    state_rings()
    places()
    places_dense()
    admin1_places()


def _load(name: str, url: str) -> list[list[tuple[float, float]]]:
    hit = _rings.get(name)
    if hit is not None:
        return hit
    cached = _read_cache(name)
    if cached is not None:
        _rings[name] = cached
        return cached
    schedule_fetch(name, url)
    return []


def _read_cache(name: str) -> list[list[tuple[float, float]]] | None:
    path = _CACHE / f"{name}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, list):
        return None
    rings: list[list[tuple[float, float]]] = []
    for item in raw:
        if not isinstance(item, list) or len(item) < 2:
            continue
        ring: list[tuple[float, float]] = []
        for pair in item:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                ring.append((float(pair[0]), float(pair[1])))
            except (TypeError, ValueError):
                continue
        if len(ring) >= 2:
            rings.append(ring)
    return rings or None


def schedule_fetch(name: str, url: str) -> None:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    with _lock:
        if name in _inflight:
            return
        if name.startswith("places") or name == "admin1":
            if name == "places50":
                if _places_dense is not None or _read_places("places50") is not None:
                    return
            elif name == "admin1":
                if _admin1 is not None or _read_places("admin1") is not None:
                    return
            elif _places is not None or _read_places() is not None:
                return
        else:
            if name in _rings or _read_cache(name) is not None:
                return
        _inflight.add(name)
    threading.Thread(
        target=_fetch_one, args=(name, url), daemon=True, name=f"earth-ne-{name}"
    ).start()


def _fetch_one(name: str, url: str) -> None:
    global _places, _places_dense, _admin1
    try:
        if not _host_pinned(urlparse(url).hostname):
            return
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return
            data = resp.json()
        if not isinstance(data, dict):
            return
        dest = _CACHE / f"{name}.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if name.startswith("places") or name == "admin1":
            found = (
                admin1_from_geojson(data)
                if name == "admin1"
                else places_from_geojson(data)
            )
            if not found:
                return
            dest.write_text(json.dumps(found), encoding="utf-8")
            if name == "places50":
                _places_dense = found
            elif name == "admin1":
                _admin1 = found
            else:
                _places = found
            n = len(found)
        else:
            rings = (
                exteriors_from_geojson(data)
                if name == "fills"
                else rings_from_geojson(data)
            )
            if not rings:
                return
            dest.write_text(json.dumps(rings), encoding="utf-8")
            _rings[name] = rings
            if name == "fills":
                labels = names_from_geojson(data)
                if len(labels) == len(rings):
                    (_CACHE / "fills_names.json").write_text(
                        json.dumps(labels), encoding="utf-8"
                    )
                    _names["fills"] = labels
            n = len(rings)
        try:
            from arelis.physics.telemetry import emit

            emit(
                "land_fetch",
                name=name,
                ok=True,
                n=n,
                n_fill=n if name == "fills" else 0,
            )
        except Exception:
            pass
    except Exception as exc:
        try:
            from arelis.physics.telemetry import emit

            emit("land_fetch", name=name, ok=False, err=type(exc).__name__)
        except Exception:
            pass
        return
    finally:
        with _lock:
            _inflight.discard(name)


def _exterior_ring(coords: Any) -> list[tuple[float, float]] | None:
    if not isinstance(coords, list) or not coords:
        return None
    return _line_ring(coords[0])


def _polygon_rings(coords: Any) -> list[list[tuple[float, float]]]:
    if not isinstance(coords, list):
        return []
    out: list[list[tuple[float, float]]] = []
    for ring in coords:
        parsed = _line_ring(ring)
        if parsed:
            out.append(parsed)
    return out


def _line_ring(coords: Any) -> list[tuple[float, float]] | None:
    if not isinstance(coords, list) or len(coords) < 2:
        return None
    ring: list[tuple[float, float]] = []
    for pair in coords:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        try:
            # GeoJSON is lon, lat.
            lon = float(pair[0])
            lat = float(pair[1])
        except (TypeError, ValueError):
            continue
        ring.append((lat, lon))
    return ring if len(ring) >= 2 else None


def names_from_geojson(payload: dict[str, Any]) -> list[str]:
    """One label per polygon exterior. Tests use a tiny fixture."""
    out: list[str] = []
    for feat in payload.get("features") or []:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
        kind = str(geom.get("type") or "")
        label = _prop_name(feat.get("properties") or {})
        if kind == "Polygon":
            out.append(label)
        elif kind == "MultiPolygon":
            coords = geom.get("coordinates")
            if isinstance(coords, list):
                out.extend(label for _ in coords)
    return out


def admin1_from_geojson(payload: dict[str, Any]) -> list[tuple[str, float, float]]:
    """State and province centroids. Tests use a tiny fixture."""
    out: list[tuple[str, float, float]] = []
    for feat in payload.get("features") or []:
        if not isinstance(feat, dict):
            continue
        label = _prop_name(feat.get("properties") or {})
        if not label:
            continue
        geom = feat.get("geometry") or {}
        kind = str(geom.get("type") or "")
        coords = geom.get("coordinates")
        rings: list[list[tuple[float, float]]] = []
        if kind == "Polygon":
            ring = _exterior_ring(coords)
            if ring:
                rings.append(ring)
        elif kind == "MultiPolygon":
            if isinstance(coords, list):
                for poly in coords:
                    ring = _exterior_ring(poly)
                    if ring:
                        rings.append(ring)
        elif kind == "Point":
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                try:
                    out.append((label, float(coords[1]), float(coords[0])))
                except (TypeError, ValueError):
                    pass
            continue
        pts = [p for ring in rings for p in ring]
        if not pts:
            continue
        lat = sum(p[0] for p in pts) / len(pts)
        lon = sum(p[1] for p in pts) / len(pts)
        out.append((label, lat, lon))
    return out


def places_from_geojson(payload: dict[str, Any]) -> list[tuple[str, float, float]]:
    out: list[tuple[str, float, float]] = []
    for feat in payload.get("features") or []:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
        if str(geom.get("type") or "") != "Point":
            continue
        coords = geom.get("coordinates")
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue
        try:
            lon = float(coords[0])
            lat = float(coords[1])
        except (TypeError, ValueError):
            continue
        label = _prop_name(feat.get("properties") or {})
        if label:
            out.append((label, lat, lon))
    return out


def _prop_name(props: Any) -> str:
    if not isinstance(props, dict):
        return ""
    for key in ("NAME", "name", "NAME_EN", "ADMIN", "NAMEASCII"):
        raw = props.get(key)
        if raw:
            return str(raw).strip()
    return ""


def _point_in_ring(
    lat: float, lon: float, ring: list[tuple[float, float]]
) -> bool:
    if len(ring) < 3:
        return False
    inside = False
    j = len(ring) - 1
    for i, (yi, xi) in enumerate(ring):
        yj, xj = ring[j]
        if (yi > lat) != (yj > lat):
            xing = (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi
            if lon < xing:
                inside = not inside
        j = i
    return inside


def _read_names(name: str) -> list[str] | None:
    path = _CACHE / f"{name}_names.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, list):
        return None
    return [str(item) if item is not None else "" for item in raw]


def _read_places(name: str = "places") -> list[tuple[str, float, float]] | None:
    path = _CACHE / f"{name}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, list):
        return None
    out: list[tuple[str, float, float]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) < 3:
            continue
        try:
            out.append((str(item[0]), float(item[1]), float(item[2])))
        except (TypeError, ValueError):
            continue
    return out or None


def _host_pinned(host: str | None) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == NE_HOST or name.endswith("." + NE_HOST)


def _cache_dir_for_tests(path: Path) -> None:
    """Test hook. Do not use from adapters."""
    global _CACHE, _places, _places_dense, _admin1
    _CACHE = path
    _rings.clear()
    _ecef.clear()
    _boxes.clear()
    _names.clear()
    _places = None
    _places_dense = None
    _admin1 = None
