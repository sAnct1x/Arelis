"""Argo float last-fix sample. Public ERDDAP JSON. No key.

A sample of recent surfacing positions, not a painted shell.
~4000 floats exist; we keep a small distinct-platform cap.
Failures return None. Host pinned in tests/test_egress.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef

ARGO_HOST = "erddap.ifremer.fr"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 14.0
_CAP = 80
_CITE = (
    "IFREMER Argo ERDDAP last-fix sample. Distinct platforms, capped. "
    "Not the shell. A pin is the last reported surfacing, not a track."
)


def fetch_argo(*, now: datetime | None = None) -> list[Entity] | None:
    payload = _get_json(_url(now))
    if payload is None:
        return None
    return entities_from_table(payload) or None


def entities_from_table(payload: dict[str, Any]) -> list[Entity]:
    table = payload.get("table") if isinstance(payload.get("table"), dict) else payload
    rows = table.get("rows") if isinstance(table, dict) else None
    names = table.get("columnNames") if isinstance(table, dict) else None
    if not isinstance(rows, list):
        return []
    idx = _columns(names if isinstance(names, list) else [])
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, list):
            continue
        entity = _entity_from_row(row, idx)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _columns(names: list[Any]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for i, name in enumerate(names):
        key = str(name or "").strip().casefold()
        if key:
            idx[key] = i
    return idx


def _entity_from_row(row: list[Any], idx: dict[str, int]) -> Entity | None:
    lat = _num(_cell(row, idx, "latitude"))
    lon = _num(_cell(row, idx, "longitude"))
    if lat is None or lon is None:
        if len(row) >= 2:
            lat = _num(row[0])
            lon = _num(row[1])
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    plat = str(_cell(row, idx, "platform_number") or _cell(row, idx, "platform") or "").strip()
    if not plat and len(row) >= 3:
        plat = str(row[2] or "").strip()
    if not plat:
        plat = f"{lat:.2f}:{lon:.2f}"
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"argo:{plat}",
        cls="site",
        layer="sites",
        label=f"Argo {plat}"[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="IFREMER Argo ERDDAP",
        freshness="delayed",
        confidence=0.55,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "platform": plat, "sample": True},
        coverage=Coverage(
            "sample",
            "Last reported surfacing. Not a continuous track. Not the shell.",
        ),
    )


def _cell(row: list[Any], idx: dict[str, int], name: str) -> Any:
    i = idx.get(name)
    if i is None or i >= len(row):
        return None
    return row[i]


def _url(now: datetime | None) -> str:
    end = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    start = end - timedelta(days=7)
    lo = start.strftime("%Y-%m-%dT00:00:00Z")
    hi = end.strftime("%Y-%m-%dT23:59:59Z")
    return (
        "https://erddap.ifremer.fr/erddap/tabledap/ArgoFloats.json"
        "?latitude,longitude,platform_number"
        f"&time%3E={lo}&time%3C={hi}&distinct()"
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
    return name == ARGO_HOST or name.endswith("." + ARGO_HOST)


def _get_json(url: str) -> dict[str, Any] | None:
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
