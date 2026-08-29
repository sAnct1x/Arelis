"""Public military ADS-B from adsb.lol. Squawking tracks only.

Host pinned in tests/test_egress.py. Failures return None so the
simulated military subset stays. Silent airframes stay absent.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

ADSB_MIL = "https://api.adsb.lol/v2/mil"
ADSB_HOST = "adsb.lol"

_TIMEOUT = 8.0
_CAP = 800
_CITE = (
    "adsb.lol /v2/mil. Public military ADS-B that is squawking. "
    "Silent airframes are a deaf zone. Not targeting."
)


def fetch_adsb_mil() -> list[Entity] | None:
    payload = _get_json()
    if payload is None:
        return None
    rows = payload.get("ac")
    if not isinstance(rows, list):
        return None
    return entities_from_ac(rows)


def entities_from_ac(rows: list[Any]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_ac(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_ac(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("lat"))
    lon = _num(row.get("lon"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    hex_id = str(row.get("hex") or "").strip()
    call = str(row.get("flight") or row.get("r") or hex_id).strip() or hex_id
    if not hex_id and not call:
        return None
    alt_ft = _num(row.get("alt_baro") or row.get("alt_geom")) or 0.0
    alt_m = max(0.0, alt_ft * 0.3048)
    gs = _num(row.get("gs")) or 0.0
    pos = lla_to_ecef(lat, lon, alt_m)
    return Entity(
        id=f"icao:{hex_id or call.casefold()}",
        cls="aircraft",
        layer="military",
        label=call.strip(),
        x=pos[0],
        y=pos[1],
        z=pos[2],
        vx=gs * 0.51444 if gs else 0.0,
        source="adsb.lol",
        freshness="delayed",
        confidence=0.65,
        cite=_CITE,
        meta={"icao24": hex_id, "lat": lat, "lon": lon, "alt_m": alt_m, "military": True},
        coverage=Coverage(
            "adsb",
            "Public squawk only. Anything not broadcasting is a hole.",
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
    return name == ADSB_HOST or name.endswith("." + ADSB_HOST)


def _get_json() -> dict[str, Any] | None:
    if not _host_pinned(urlparse(ADSB_MIL).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(ADSB_MIL, headers={"User-Agent": "ArelisEarth/0.2"})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
