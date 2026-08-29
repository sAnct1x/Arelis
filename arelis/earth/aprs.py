"""APRS station loc via aprs.fi. Keyed. Named stations only.

The aprs.fi API queries specific callsigns (up to 20 per request). It
does not search by wildcard or by map rectangle. Credit: aprs.fi
(https://aprs.fi). Key: earth.aprs_key / ARELIS_APRS_KEY. Optional
earth.aprs_calls lists extra stations; default is W1AW. AIS vessels
from this API (type a) are dropped — not a vessel dump. Failures
return None. Live click only; not a background harvest.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef
from arelis.paths import state_dir

APRS_API = "https://api.aprs.fi/api/get"
APRS_HOST = "api.aprs.fi"
APRS_KEY_ENV = "ARELIS_APRS_KEY"
SECRETS_PATH = state_dir() / "secrets.yaml"
# Public club station. Not a dump of the amateur service.
DEFAULT_CALLS: tuple[str, ...] = ("W1AW",)
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 8.0
_BATCH = 20
_CITE = (
    "aprs.fi loc for named stations (https://aprs.fi). "
    "Licensed amateur packet. Not a map clone. Not a tuner. "
    "Stations you did not name stay off the plate."
)
_KEEP_TYPES = frozenset({"l", "i", "o", "w"})


def aprs_key(path: Path | None = None) -> str:
    env = (os.environ.get(APRS_KEY_ENV) or "").strip()
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
    return str(block.get("aprs_key") or "").strip()


def station_calls(path: Path | None = None) -> tuple[str, ...]:
    path = path or SECRETS_PATH
    extra: list[str] = []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        raw = {}
    block = raw.get("earth") if isinstance(raw, dict) else None
    if isinstance(block, dict):
        listed = block.get("aprs_calls")
        if isinstance(listed, str):
            extra.extend(listed.split(","))
        elif isinstance(listed, list):
            extra.extend(str(item) for item in listed)
    seen: set[str] = set()
    out: list[str] = []
    for call in (*DEFAULT_CALLS, *extra):
        name = str(call or "").strip().upper()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
        if len(out) >= _BATCH:
            break
    return tuple(out)


def fetch_aprs() -> list[Entity] | None:
    key = aprs_key()
    if not key:
        return None
    payload = _get_loc(key, station_calls())
    if payload is None:
        return None
    if str(payload.get("result") or "") == "fail":
        return None
    return entities_from_entries(payload)


def entities_from_entries(payload: dict[str, Any]) -> list[Entity]:
    rows = payload.get("entries")
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
        if len(out) >= _BATCH:
            break
    return out


def _entity_from_row(row: dict[str, Any]) -> Entity | None:
    kind = str(row.get("type") or "l").strip().lower()
    if kind == "a":
        return None
    if kind not in _KEEP_TYPES:
        return None
    lat = _num(row.get("lat"))
    lon = _num(row.get("lng") if row.get("lng") is not None else row.get("lon"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    if abs(lat) < 1e-6 and abs(lon) < 1e-6:
        return None
    call = str(row.get("showname") or row.get("name") or "").strip()
    if not call:
        return None
    alt = _num(row.get("altitude")) or 0.0
    pos = lla_to_ecef(lat, lon, alt)
    return Entity(
        id=f"aprs:{call.casefold()[:24]}",
        cls="rf",
        layer="radio",
        label=call,
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="aprs.fi",
        freshness="delayed",
        confidence=0.7,
        cite=_CITE,
        meta={"lat": lat, "lon": lon, "call": call.casefold()},
        coverage=Coverage(
            "rf",
            "Named amateur station from aprs.fi. Not a regional dump.",
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
    return name == APRS_HOST or name.endswith("." + APRS_HOST)


def _get_loc(key: str, calls: tuple[str, ...]) -> dict[str, Any] | None:
    if not calls:
        return None
    if not _host_pinned(urlparse(APRS_API).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                APRS_API,
                params={
                    "name": ",".join(calls),
                    "what": "loc",
                    "apikey": key,
                    "format": "json",
                },
                headers={"User-Agent": _UA},
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
