"""OpenAQ v3 location pins. Free key. Not a VIN.

Key from earth.openaq_key or ARELIS_OPENAQ_KEY. Header X-API-Key.
One /v3/locations pull per Live (their free cap is 60/min, 2,000/hour).
Cite OpenAQ and the originating provider. Local observer only. Do not
scrape Explorer. Do not republish the dump. Failures return None.
Host pinned in egress.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef
from arelis.earth.secrets import earth_secret

OPENAQ_LOCATIONS = "https://api.openaq.org/v3/locations"
OPENAQ_HOST = "api.openaq.org"
OPENAQ_ENV = "ARELIS_OPENAQ_KEY"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 12.0
_CAP = 400
_CITE = (
    "OpenAQ (https://openaq.org) and the originating provider. "
    "Free key. Local observer only. Do not scrape Explorer. "
    "Do not republish the dump. A published monitor, not a car."
)


def openaq_key(path=None) -> str:
    return earth_secret("openaq_key", OPENAQ_ENV, path)


def fetch_openaq() -> list[Entity] | None:
    key = openaq_key()
    if not key:
        return None
    payload = _get_json(key)
    if payload is None:
        return None
    return entities_from_locations(payload) or None


def entities_from_locations(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("results")
    if not isinstance(rows, list):
        return []
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
    coords = row.get("coordinates") if isinstance(row.get("coordinates"), dict) else {}
    lat = _num(coords.get("latitude"))
    lon = _num(coords.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    loc_id = str(row.get("id") or "").strip()
    name = str(row.get("name") or loc_id or "monitor").strip()
    provider = row.get("provider") if isinstance(row.get("provider"), dict) else {}
    source = str(provider.get("name") or "").strip()
    if not loc_id and not name:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    cite = f"{source}. {_CITE}" if source else _CITE
    return Entity(
        id=f"openaq:{loc_id or name.casefold()[:32]}",
        cls="weather",
        layer="weather",
        label=name[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="OpenAQ",
        freshness="delayed",
        confidence=0.65,
        cite=cite,
        meta={"lat": lat, "lon": lon, "provider": source},
        coverage=Coverage(
            "station",
            "Published air monitor. Not a car. Not every city.",
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
    return name == OPENAQ_HOST or name.endswith("." + OPENAQ_HOST)


def _get_json(key: str) -> dict[str, Any] | None:
    if not _host_pinned(urlparse(OPENAQ_LOCATIONS).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                OPENAQ_LOCATIONS,
                params={"limit": str(_CAP), "monitor": "true"},
                headers={
                    "User-Agent": _UA,
                    "Accept": "application/json",
                    "X-API-Key": key,
                },
            )
            if resp.status_code == 429:
                return None
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
