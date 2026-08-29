"""NASA FIRMS hotspots. Keyed. Cloud and revisit stay holes.

MAP_KEY from earth.firms_key or ARELIS_FIRMS_KEY. Host pinned in
tests/test_egress.py. Failures return None so simulated fires stay.
The key never lands in dumps. This is a CSV area extract, not a login.
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef
from arelis.paths import state_dir

FIRMS_SITE = "https://firms.modaps.eosdis.nasa.gov"
FIRMS_HOST = "firms.modaps.eosdis.nasa.gov"
FIRMS_KEY_ENV = "ARELIS_FIRMS_KEY"
SECRETS_PATH = state_dir() / "secrets.yaml"

_TIMEOUT = 8.0
_CAP = 400
_CITE = (
    "NASA FIRMS VIIRS NRT, last 24h, world extract. Cloud and revisit hide "
    "fires. Keyed MAP_KEY. Not a perimeter."
)


def firms_key(path: Path | None = None) -> str:
    env = (os.environ.get(FIRMS_KEY_ENV) or "").strip()
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
    return str(block.get("firms_key") or "").strip()


def fetch_firms() -> list[Entity] | None:
    key = firms_key()
    if not key:
        return None
    text = _get_csv(key)
    if text is None:
        return None
    return entities_from_csv(text)


def entities_from_csv(text: str) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        entity = _entity_from_row(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _entity_from_row(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("latitude"))
    lon = _num(row.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    bright = _num(row.get("bright_ti4") or row.get("brightness"))
    acq = str(row.get("acq_date") or "").strip()
    pos = lla_to_ecef(lat, lon, 0.0)
    eid = f"firms:{lat:.3f}:{lon:.3f}:{acq}"
    return Entity(
        id=eid,
        cls="fire",
        layer="fires",
        label="hotspot" if bright is None else f"hotspot {bright:.0f} K",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="NASA FIRMS",
        freshness="delayed",
        confidence=0.65,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "bright": bright, "acq_date": acq},
        coverage=Coverage(
            "revisit",
            "Satellite hotspot. Cloud and revisit are holes. Not a perimeter.",
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
    return name == FIRMS_HOST or name.endswith("." + FIRMS_HOST)


def _get_csv(key: str) -> str | None:
    url = (
        f"{FIRMS_SITE}/api/area/csv/{key}/VIIRS_NOAA20_NRT/world/1"
    )
    if not _host_pinned(urlparse(FIRMS_SITE).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "ArelisEarth/0.2"})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            text = resp.text
    except Exception:
        return None
    if not isinstance(text, str) or "latitude" not in text.split("\n", 1)[0].lower():
        return None
    return text
