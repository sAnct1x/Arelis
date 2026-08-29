"""USGS volcano monitoring catalog. Public GeoJSON. No key.

Monitored vents with an alert level. Remote / unmonitored vents stay
off. Complements EONET named events. Failures return None.
Host pinned in tests/test_egress.py.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

VOLCANOES = "https://volcanoes.usgs.gov/vsc/api/volcanoApi/geojson"
VOLCANOES_HOST = "volcanoes.usgs.gov"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 12.0
_CAP = 200
_CITE = (
    "USGS volcano monitoring GeoJSON. Alert-level catalog, not every vent "
    "erupting now. Unmonitored volcanoes stay off."
)


def fetch_volcanoes() -> list[Entity] | None:
    payload = _get_json()
    if payload is None:
        return None
    return entities_from_geojson(payload) or None


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
        lat = _num(props.get("lat") or props.get("latitude"))
        lon = _num(props.get("lon") or props.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    vid = str(
        props.get("volcanoId")
        or props.get("id")
        or feat.get("id")
        or ""
    ).strip()
    name = str(props.get("volcanoName") or props.get("name") or vid).strip()
    alert = str(props.get("alertLevel") or props.get("colorCode") or "").strip()
    if not vid and not name:
        return None
    label = name or vid
    if alert and alert.casefold() not in label.casefold():
        label = f"{label} {alert}"
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"volc:{vid or name.casefold()[:40]}",
        cls="site",
        layer="sites",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="USGS volcanoes",
        freshness="delayed",
        confidence=0.75,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "alert": alert, "name": name},
        coverage=Coverage(
            "catalog",
            "Monitored volcano. Unmonitored vents stay off. Not a face.",
        ),
    )


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
    return name == VOLCANOES_HOST or name.endswith("." + VOLCANOES_HOST)


def _get_json() -> dict[str, Any] | None:
    if not _host_pinned(urlparse(VOLCANOES).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(VOLCANOES, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
