"""Aviation Weather Center METARs + SIGMETs. Public. No key.

Recent station reports and active hazard-area centroids. Not a VIN
and not a forecast mesh. Failures return None. Host pinned in
tests/test_egress.py.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

METAR = "https://aviationweather.gov/api/data/metar?format=geojson&hours=1"
SIGMET = "https://aviationweather.gov/api/data/airsigmet?format=geojson"
ISIGMET = "https://aviationweather.gov/api/data/isigmet?format=geojson"
METAR_HOST = "aviationweather.gov"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 12.0
_CAP = 800
_SIGMET_CAP = 200
_CITE = (
    "Aviation Weather Center METAR GeoJSON, last hour. Station reports. "
    "Flight category when published. Not a forecast mesh. Not every strip."
)
_SIGMET_CITE = (
    "Aviation Weather Center SIGMET GeoJSON. Active hazard areas. "
    "Not every turbulence cell. Not a forecast mesh."
)


def fetch_metar() -> list[Entity] | None:
    metar = _get_json(METAR)
    hazards = _get_json(SIGMET)
    intl = _get_json(ISIGMET)
    stations = entities_from_geojson(metar) if isinstance(metar, dict) else []
    sigmets = entities_from_sigmet(hazards, prefix="sigmet") if isinstance(hazards, dict) else []
    isigmets = entities_from_sigmet(intl, prefix="isigmet") if isinstance(intl, dict) else []
    out = stations + sigmets + isigmets
    if metar is None and hazards is None and intl is None:
        return None
    return out or None


def entities_from_geojson(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_feat(row)
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
    if lat is None or lon is None:
        lat = _num(props.get("lat"))
        lon = _num(props.get("lon") or props.get("lon"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    icao = str(props.get("id") or props.get("icaoId") or props.get("stationId") or "").strip()
    temp = _num(props.get("temp") or props.get("tempC"))
    cat = str(props.get("fltCat") or props.get("flightCategory") or "").strip()
    wx = str(props.get("wxString") or props.get("rawOb") or "").strip()
    name = icao or "METAR"
    label = name
    if temp is not None:
        label = f"{name} {temp:.0f}°C"
    if cat:
        label = f"{label} {cat}"
    if not icao:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"metar:{icao}",
        cls="weather",
        layer="weather",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Aviation Weather METAR",
        freshness="delayed",
        confidence=0.75,
        cite=_CITE,
        meta={
            "lat": lat,
            "lon": lon,
            "icao": icao,
            "temp_c": temp,
            "flt_cat": cat,
            "wx": wx[:80],
        },
        coverage=Coverage(
            "station",
            "Published METAR. Not a forecast. Most of Earth is a hole.",
        ),
    )


def entities_from_sigmet(payload: dict[str, Any], *, prefix: str) -> list[Entity]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_sigmet(row, prefix=prefix)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _SIGMET_CAP:
            break
    return out


def _entity_from_sigmet(feat: dict[str, Any], *, prefix: str) -> Entity | None:
    props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
    geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
    lat, lon = _sigmet_ll(geom, props)
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    eid = str(
        props.get("id")
        or props.get("airSigmetId")
        or props.get("isigmetId")
        or feat.get("id")
        or ""
    ).strip()
    hazard = str(props.get("hazard") or props.get("hazardType") or "SIGMET").strip()
    raw = str(props.get("rawAirSigmet") or props.get("rawSigmet") or "").strip()
    label = hazard
    fir = str(props.get("firId") or props.get("icaoId") or "").strip()
    if fir and fir.casefold() not in label.casefold():
        label = f"{fir} {label}"
    if not eid and not label:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"{prefix}:{eid or label.casefold()[:40]}",
        cls="weather",
        layer="weather",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Aviation Weather SIGMET",
        freshness="delayed",
        confidence=0.65,
        cite=_SIGMET_CITE,
        meta={"lat": lat, "lon": lon, "hazard": hazard, "raw": raw[:80]},
        coverage=Coverage(
            "hazard",
            "Published SIGMET area centroid. Not every cell. Not a photograph.",
        ),
    )


def _sigmet_ll(
    geom: dict[str, Any], props: dict[str, Any]
) -> tuple[float | None, float | None]:
    lat = _num(props.get("lat") or props.get("latitude"))
    lon = _num(props.get("lon") or props.get("longitude"))
    if lat is not None and lon is not None:
        return lat, lon
    coords = geom.get("coordinates")
    if not isinstance(coords, list) or not coords:
        return None, None
    kind = str(geom.get("type") or "")
    if kind == "Point" and len(coords) >= 2:
        return _num(coords[1]), _num(coords[0])
    # Unwrap MultiPolygon / Polygon / MultiLineString until we have [lon, lat] pairs.
    ring: Any = coords
    while (
        isinstance(ring, list)
        and ring
        and isinstance(ring[0], (list, tuple))
        and ring[0]
        and isinstance(ring[0][0], (list, tuple))
    ):
        ring = ring[0]
    if not isinstance(ring, list) or not ring:
        return None, None
    lats: list[float] = []
    lons: list[float] = []
    for pair in ring:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        x, y = _num(pair[0]), _num(pair[1])
        if x is None or y is None:
            continue
        lons.append(x)
        lats.append(y)
    if not lats:
        return None, None
    return sum(lats) / len(lats), sum(lons) / len(lons)


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
    return name == METAR_HOST or name.endswith("." + METAR_HOST)


def _get_json(url: str = METAR) -> dict[str, Any] | None:
    if not _host_pinned(urlparse(url).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
