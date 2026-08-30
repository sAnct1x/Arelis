"""Official road-weather stations. Published sites, not a forecast mesh.

Fintraffic RWIS, Lithuania eismoinfo, Quebec 511 meteo. Failures return
None. Hosts pinned in tests/test_egress.py.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

FI_RWIS = "https://tie.digitraffic.fi/api/weather/v1/stations"
FI_HOST = "tie.digitraffic.fi"
LT_RWIS = "https://eismoinfo.lt/weather-conditions-service"
LT_HOST = "eismoinfo.lt"
QC_RWIS = (
    "https://ws.mapserver.transports.gouv.qc.ca/swtq?service=wfs&version=2.0.0"
    "&request=GetFeature&typename=ms:stations_meteoroutieres"
    "&srsname=EPSG:4326&outputformat=geojson"
)
QC_HOST = "ws.mapserver.transports.gouv.qc.ca"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 12.0
_CAP = 2000
_FI_CITE = (
    "Fintraffic road-weather stations. Finnish road network. CC BY 4.0. "
    "Published sensors, not a forecast mesh."
)
_LT_CITE = (
    "Lithuania eismoinfo road-weather stations. Operator JSON. "
    "Published sensors, not a forecast mesh."
)
_QC_CITE = (
    "Quebec 511 / MTMD road-weather stations. Operator GeoJSON. "
    "Published sensors, not a forecast mesh."
)


def fetch_rwis() -> list[Entity] | None:
    chunks: list[list[Entity] | None] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [
            pool.submit(_fetch_fi),
            pool.submit(_fetch_lt),
            pool.submit(_fetch_qc),
        ]
        for fut in futs:
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


def entities_from_fi_rwis(payload: dict[str, Any]) -> list[Entity]:
    return _from_geojson(
        payload,
        prefix="fi-rwis",
        source="Fintraffic RWIS",
        cite=_FI_CITE,
        id_keys=("id",),
        name_keys=("name",),
    )


def entities_from_qc_rwis(payload: dict[str, Any]) -> list[Entity]:
    return _from_geojson(
        payload,
        prefix="qc-rwis",
        source="Quebec 511 weather stations",
        cite=_QC_CITE,
        id_keys=("station_meteo_id", "objectid"),
        name_keys=("station_meteo_nom",),
    )


def entities_from_lt_rwis(rows: list[dict[str, Any]]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        lat = _num(row.get("lat"))
        lon = _num(row.get("lng"), row.get("lon"))
        if lat is None or lon is None:
            continue
        if abs(lat) > 90.0 or abs(lon) > 180.0:
            continue
        cid = str(row.get("id") or "").strip()
        name = str(row.get("pavadinimas") or row.get("irenginys") or cid).strip()
        if not cid and not name:
            continue
        eid = f"lt-rwis:{cid or name.casefold()[:40]}"
        if eid in seen:
            continue
        seen.add(eid)
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=eid,
                cls="weather",
                layer="weather",
                label=name[:80],
                x=pos[0],
                y=pos[1],
                z=pos[2],
                source="Lithuania RWIS",
                freshness="delayed",
                confidence=0.75,
                cite=_LT_CITE,
                meta={"lat": lat, "lon": lon},
                coverage=Coverage(
                    "catalog",
                    "Published road-weather station. Not a forecast. Not a car.",
                ),
            )
        )
        if len(out) >= _CAP:
            break
    return out


def _from_geojson(
    payload: dict[str, Any],
    *,
    prefix: str,
    source: str,
    cite: str,
    id_keys: tuple[str, ...],
    name_keys: tuple[str, ...],
) -> list[Entity]:
    rows = payload.get("features")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for feat in rows:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties") if isinstance(feat.get("properties"), dict) else {}
        geom = feat.get("geometry") if isinstance(feat.get("geometry"), dict) else {}
        coords = geom.get("coordinates") if isinstance(geom.get("coordinates"), list) else []
        lon = _num(coords[0] if len(coords) > 0 else None)
        lat = _num(coords[1] if len(coords) > 1 else None)
        if lat is None or lon is None:
            lat = _num(props.get("latitude"), props.get("lat"))
            lon = _num(props.get("longitude"), props.get("lon"))
        if lat is None or lon is None:
            continue
        if abs(lat) > 90.0 or abs(lon) > 180.0:
            continue
        cid = ""
        for key in id_keys:
            cid = str(props.get(key) or feat.get("id") or "").strip()
            if cid:
                break
        name = ""
        for key in name_keys:
            name = str(props.get(key) or "").strip()
            if name:
                break
        if not cid and not name:
            continue
        eid = f"{prefix}:{cid or name.casefold()[:40]}"
        if eid in seen:
            continue
        seen.add(eid)
        pos = lla_to_ecef(lat, lon, 0.0)
        out.append(
            Entity(
                id=eid,
                cls="weather",
                layer="weather",
                label=(name or cid)[:80],
                x=pos[0],
                y=pos[1],
                z=pos[2],
                source=source,
                freshness="delayed",
                confidence=0.75,
                cite=cite,
                meta={"lat": lat, "lon": lon},
                coverage=Coverage(
                    "catalog",
                    "Published road-weather station. Not a forecast. Not a car.",
                ),
            )
        )
        if len(out) >= _CAP:
            break
    return out


def _fetch_fi() -> list[Entity] | None:
    payload = _get_json(FI_RWIS, FI_HOST)
    if not isinstance(payload, dict):
        return None
    return entities_from_fi_rwis(payload) or None


def _fetch_lt() -> list[Entity] | None:
    payload = _get_json(LT_RWIS, LT_HOST)
    if not isinstance(payload, list):
        return None
    rows = [row for row in payload if isinstance(row, dict)]
    return entities_from_lt_rwis(rows) or None


def _fetch_qc() -> list[Entity] | None:
    payload = _get_json(QC_RWIS, QC_HOST)
    if not isinstance(payload, dict):
        return None
    return entities_from_qc_rwis(payload) or None


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


def _host_pinned(host: str | None, pin: str) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == pin or name.endswith("." + pin)


def _num(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
