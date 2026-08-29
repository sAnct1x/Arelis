"""Global Fishing Watch unmatched SAR detections. Keyed. CC BY-NC.

Industrial-scale metal the GFW model saw in Sentinel-1, unmatched to AIS.
About five days lag. Not a hull name. Not satellite AIS identity.
Local observer use; we do not resell this.

Token from earth.gfw_token or ARELIS_GFW_TOKEN (free GFW account).
Host pinned in tests/test_egress.py. Failures return None.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef
from arelis.paths import state_dir

GFW_REPORT = "https://gateway.api.globalfishingwatch.org/v3/4wings/report"
GFW_HOST = "gateway.api.globalfishingwatch.org"
GFW_KEY_ENV = "ARELIS_GFW_TOKEN"
SECRETS_PATH = state_dir() / "secrets.yaml"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 18.0
_CAP = 400
_LAG_DAYS = 5
_WINDOW_DAYS = 7
# Same named gyres AISStream used to drop. Presence, not identity.
_GYRES: tuple[tuple[str, list[list[float]]], ...] = (
    (
        "npac-west",
        [[160.0, 15.0], [180.0, 15.0], [180.0, 40.0], [160.0, 40.0], [160.0, 15.0]],
    ),
    (
        "npac-east",
        [[-180.0, 15.0], [-130.0, 15.0], [-130.0, 40.0], [-180.0, 40.0], [-180.0, 15.0]],
    ),
    (
        "natl",
        [[-50.0, 10.0], [-25.0, 10.0], [-25.0, 35.0], [-50.0, 35.0], [-50.0, 10.0]],
    ),
)
_CITE = (
    "Global Fishing Watch unmatched SAR detections (CC BY-NC). "
    "Industrial-scale contacts, ~5 day lag. Not a hull name. "
    "Not satellite AIS. Local observer, not a resale."
)
_COVERAGE = (
    "Radar saw metal here. AIS did not name it. Sample of gyre cells, "
    "not every Sentinel-1 detection."
)


def gfw_token(path: Path | None = None) -> str:
    env = (os.environ.get(GFW_KEY_ENV) or "").strip()
    if env:
        return env
    path = path or SECRETS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ""
    if not isinstance(raw, dict):
        return ""
    block = raw.get("earth")
    if not isinstance(block, dict):
        return ""
    return str(block.get("gfw_token") or "").strip()


def fetch_gfw() -> list[Entity] | None:
    token = gfw_token()
    if not token:
        return None
    end = datetime.now(UTC).date() - timedelta(days=_LAG_DAYS)
    start = end - timedelta(days=_WINDOW_DAYS)
    chunks: list[Any] = []
    any_ok = False
    for _name, ring in _GYRES:
        payload = _report(token, ring, start.isoformat(), end.isoformat())
        if payload is None:
            continue
        any_ok = True
        chunks.append(payload)
    if not any_ok:
        return None
    out: list[Entity] = []
    seen: set[str] = set()
    for payload in chunks:
        for entity in entities_from_report(payload):
            if entity.id in seen:
                continue
            seen.add(entity.id)
            out.append(entity)
            if len(out) >= _CAP:
                return out
    return out


def entities_from_report(
    payload: Any, *, unix: float | None = None
) -> list[Entity]:
    now = float(unix if unix is not None else time.time())
    out: list[Entity] = []
    seen: set[str] = set()
    for row in _cells(payload):
        entity = _entity_from_cell(row, now)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_cell(row: dict[str, Any], now: float) -> Entity | None:
    lat = _num(row.get("lat"))
    lon = _num(row.get("lon"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    detections = _num(row.get("detections")) or 1.0
    date = str(row.get("date") or "").strip()
    eid = f"gfw:sar:{lat:.3f}:{lon:.3f}:{date or int(now)}"
    pos = lla_to_ecef(lat, lon, 0.0)
    when = _unix_date(date, now)
    return Entity(
        id=eid,
        cls="site",
        layer="radar",
        label="SAR contact",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        when_unix=when,
        source="Global Fishing Watch SAR",
        freshness="delayed",
        confidence=0.55,
        cite=_CITE,
        meta={
            "lat": lat,
            "lon": lon,
            "detections": detections,
            "matched": False,
        },
        coverage=Coverage("radar", _COVERAGE),
        pii="none",
    )


def _cells(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            lat = _num(node.get("lat"))
            lon = _num(node.get("lon"))
            if lat is not None and lon is not None:
                found.append(node)
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def _report(token: str, ring: list[list[float]], start: str, end: str) -> Any:
    if not _host_pinned(urlparse(GFW_REPORT).hostname, GFW_HOST):
        return None
    body = {
        "geojson": {
            "type": "Polygon",
            "coordinates": [ring],
        }
    }
    params = {
        "spatial-resolution": "LOW",
        "temporal-resolution": "DAILY",
        "datasets[0]": "public-global-sar-presence:latest",
        "date-range": f"{start},{end}",
        "format": "JSON",
        "filters[0]": "matched='false'",
    }
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.post(
                GFW_REPORT,
                params=params,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": _UA,
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, GFW_HOST):
                return None
            return resp.json()
    except Exception:
        return None


def _unix_date(stamp: str, fallback: float) -> float:
    if not stamp:
        return fallback
    text = stamp.strip()[:10]
    try:
        dt = datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=UTC)
        return dt.timestamp()
    except (ValueError, OverflowError, OSError):
        return fallback


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _host_pinned(host: str | None, pin: str) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == pin or name.endswith("." + pin)
