"""Upcoming launches from The Space Devs Launch Library 2. Public.

Pad coordinates only. Failures return None so bundled sites stay.
No silent pad — missing pads are dropped. Host pinned in test_egress.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

LAUNCH_LIBRARY = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/"
LAUNCH_HOST = "ll.thespacedevs.com"

_TIMEOUT = 8.0
_CAP = 40
_CITE = (
    "Launch Library 2 upcoming. Public pad coordinates. Not a countdown "
    "clock. Pads without geo are a hole."
)


def fetch_launches() -> list[Entity] | None:
    payload = _get_upcoming()
    if payload is None:
        return None
    rows = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    return entities_from_launches(rows)


def entities_from_launches(rows: list[dict[str, Any]]) -> list[Entity]:
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
    pad = row.get("pad") if isinstance(row.get("pad"), dict) else {}
    lat = _num(pad.get("latitude"))
    lon = _num(pad.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    uid = str(row.get("id") or "").strip()
    name = str(row.get("name") or pad.get("name") or "").strip()
    if not uid and not name:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    pad_name = str(pad.get("name") or "").strip()
    label = name or pad_name or uid
    return Entity(
        id=f"ll2:{uid or name.casefold()[:48]}",
        cls="site",
        layer="sites",
        label=label[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Launch Library 2",
        freshness="delayed",
        confidence=0.75,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "pad": pad_name, "launch_id": uid},
        coverage=Coverage(
            "pad",
            "Published pad pin. Not a T-0 clock. Classified pads are absent.",
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
    return name == LAUNCH_HOST or name.endswith("." + LAUNCH_HOST)


def _get_upcoming() -> dict[str, Any] | None:
    if not _host_pinned(urlparse(LAUNCH_LIBRARY).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                LAUNCH_LIBRARY,
                params={"limit": str(_CAP), "mode": "list"},
                headers={"User-Agent": "ArelisEarth/0.2"},
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
