"""Radio Browser directory pins. Public. Not a tuner.

Hosts named here are pinned in tests/test_egress.py. Failures return None
so simulated FM pins stay. This is crowd-sourced stream geolocation, not
a transmitter viewshed and not decoded audio. Encrypted / private radio
stays out.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef
from arelis.earth.look import offer_radio

RADIO_BROWSER_ALL = "https://all.api.radio-browser.info/json/stations/search"
RADIO_BROWSER_DE = "https://de1.api.radio-browser.info/json/stations/search"
RADIO_BROWSER_HOST = "radio-browser.info"

_TIMEOUT = 8.0
_CAP = 800
_PARAMS = {
    "hidebroken": "true",
    "has_geo_info": "true",
    "limit": str(_CAP),
    "order": "clickcount",
    "reverse": "true",
}
_CITE = (
    "Radio Browser directory. Crowd-sourced stream geo, not a transmitter "
    "license point and not a tuner. Stations without geo are a hole. "
    "No audio ingest. Encrypted radio is out."
)


def fetch_radio() -> list[Entity] | None:
    payload = _get_stations(RADIO_BROWSER_ALL) or _get_stations(RADIO_BROWSER_DE)
    if payload is None:
        return None
    return entities_from_stations(payload)


def entities_from_stations(rows: list[dict[str, Any]]) -> list[Entity]:
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
    lat = _num(row.get("geo_lat"))
    lon = _num(row.get("geo_long"))
    if lat is None or lon is None:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    uid = str(row.get("stationuuid") or "").strip()
    name = str(row.get("name") or "").strip()
    if not uid and not name:
        return None
    eid = f"rb:{uid or name.casefold()[:48]}"
    country = str(row.get("country") or "").strip()
    homepage = str(row.get("homepage") or "").strip()
    pos = lla_to_ecef(lat, lon, 80.0)
    offer_radio(
        eid,
        str(row.get("url_resolved") or "").strip(),
        str(row.get("url") or "").strip(),
    )
    return Entity(
        id=eid,
        cls="rf",
        layer="radio",
        label=name or uid,
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Radio Browser",
        freshness="reconstructed",
        confidence=0.55,
        cite=_CITE,
        meta={
            "lat": lat,
            "lon": lon,
            "country": country,
            "homepage": homepage[:200],
            "stationuuid": uid,
        },
        coverage=Coverage(
            "directory",
            "Published stream location. Not an RF viewshed. Most transmitters are a hole.",
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
    return name == RADIO_BROWSER_HOST or name.endswith("." + RADIO_BROWSER_HOST)


def _get_stations(url: str) -> list[dict[str, Any]] | None:
    if not _host_pinned(urlparse(url).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                url,
                params=_PARAMS,
                headers={"User-Agent": "ArelisEarth/0.2"},
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    return [row for row in data if isinstance(row, dict)]
