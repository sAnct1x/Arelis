"""Shodan banner catalog. Keyed. Banners only — never a login.

API key from earth.shodan_key or ARELIS_SHODAN_KEY. Host pinned in
tests/test_egress.py. We keep lat/lon/product. We do not store the IP,
the banner body, or a stream URL. Default password is still a login.
An open port is not consent.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef
from arelis.paths import state_dir

SHODAN_SEARCH = "https://api.shodan.io/shodan/host/search"
SHODAN_HOST = "api.shodan.io"
SHODAN_KEY_ENV = "ARELIS_SHODAN_KEY"
SECRETS_PATH = state_dir() / "secrets.yaml"

_TIMEOUT = 12.0
_CAP = 200
_QUERY = "webcam has_geo:true"
_CITE = (
    "Shodan banner catalog the operator already indexed. Position and "
    "product only. Not a login. Banner body and IP are dropped. "
    "An open port is not consent."
)


def shodan_key(path: Path | None = None) -> str:
    env = (os.environ.get(SHODAN_KEY_ENV) or "").strip()
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
    return str(block.get("shodan_key") or "").strip()


def fetch_shodan() -> list[Entity] | None:
    key = shodan_key()
    if not key:
        return None
    payload = _get_search(key)
    if payload is None:
        return None
    return entities_from_matches(payload)


def entities_from_matches(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("matches")
    if not isinstance(rows, list):
        return []
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_match(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_match(row: dict[str, Any]) -> Entity | None:
    loc = row.get("location") if isinstance(row.get("location"), dict) else {}
    lat = _num(loc.get("latitude"))
    lon = _num(loc.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    product = str(row.get("product") or row.get("devicetype") or "webcam").strip()
    digest = hashlib.sha256(f"{lat:.3f}:{lon:.3f}:{product}".encode()).hexdigest()[:12]
    pos = lla_to_ecef(lat, lon, 12.0)
    return Entity(
        id=f"shodan:{digest}",
        cls="camera",
        layer="cameras",
        label=product[:48] or "banner",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Shodan banners",
        freshness="reconstructed",
        confidence=0.5,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "product": product[:48]},
        coverage=Coverage(
            "banner",
            "Indexed banner with geo. Not a login. IP and stream URL dropped.",
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
    return name == SHODAN_HOST or name.endswith("." + SHODAN_HOST)


def _get_search(key: str) -> dict[str, Any] | None:
    if not _host_pinned(urlparse(SHODAN_SEARCH).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                SHODAN_SEARCH,
                params={"key": key, "query": _QUERY, "minify": "true"},
                headers={"User-Agent": "ArelisEarth/0.2"},
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
