"""Kystverket / BarentsWatch AIS. Keyed. Free AIS client.

Norwegian EEZ, Svalbard, and Jan Mayen, including Norwegian satellites
in that zone. Not a global paid sat-AIS product. Limits: no fishing
under 15 m, no leisure/sail under 45 m. NLOD. Credit Kystverket.

Client id/secret from earth.barentswatch_client_id / _secret or
ARELIS_BARENTSWATCH_CLIENT_ID / ARELIS_BARENTSWATCH_CLIENT_SECRET.
Hosts pinned in tests/test_egress.py. Failures return None.
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import ecef_vel_from_track, lla_to_ecef
from arelis.paths import state_dir

TOKEN_URL = "https://id.barentswatch.no/connect/token"
TOKEN_HOST = "id.barentswatch.no"
LATEST_URL = "https://live.ais.barentswatch.no/v1/latest/combined"
LATEST_HOST = "live.ais.barentswatch.no"
ID_ENV = "ARELIS_BARENTSWATCH_CLIENT_ID"
SECRET_ENV = "ARELIS_BARENTSWATCH_CLIENT_SECRET"
SECRETS_PATH = state_dir() / "secrets.yaml"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 12.0
_CAP = 2500
_CITE = (
    "Kystverket / BarentsWatch AIS. Norwegian EEZ including Norwegian "
    "satellites in that zone. NLOD. Not a global sat-AIS product. "
    "Not navigation. Credit Kystverket."
)
_COVERAGE = (
    "Norwegian EEZ / Svalbard / Jan Mayen. Fishing under 15 m and "
    "leisure/sail under 45 m are withheld. Not the whole ocean."
)

_token = ""
_token_until = 0.0


def barentswatch_creds(path: Path | None = None) -> tuple[str, str]:
    cid = (os.environ.get(ID_ENV) or "").strip()
    secret = (os.environ.get(SECRET_ENV) or "").strip()
    if cid and secret:
        return cid, secret
    path = path or SECRETS_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return "", ""
    if not isinstance(raw, dict):
        return "", ""
    block = raw.get("earth")
    if not isinstance(block, dict):
        return "", ""
    cid = cid or str(block.get("barentswatch_client_id") or "").strip()
    secret = secret or str(block.get("barentswatch_client_secret") or "").strip()
    return cid, secret


def fetch_barentswatch() -> list[Entity] | None:
    """None = no creds or failed. Empty list = heard nothing."""
    cid, secret = barentswatch_creds()
    if not cid or not secret:
        return None
    token = _bearer(cid, secret)
    if not token:
        return None
    payload = _get_latest(token)
    if payload is None:
        return None
    return entities_from_latest(payload)


def entities_from_latest(
    rows: Any, *, unix: float | None = None
) -> list[Entity]:
    now = float(unix if unix is not None else time.time())
    if not isinstance(rows, list):
        return []
    by_mmsi: dict[str, Entity] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_row(row, now)
        if entity is None:
            continue
        by_mmsi[entity.id] = entity
        if len(by_mmsi) >= _CAP:
            break
    return list(by_mmsi.values())


def _entity_from_row(row: dict[str, Any], now: float) -> Entity | None:
    lat = _num(row.get("latitude"))
    lon = _num(row.get("longitude"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    mmsi = str(row.get("mmsi") or "").strip()
    if not mmsi or mmsi == "0":
        return None
    name = str(row.get("name") or "").strip() or mmsi
    sog = _num(row.get("speedOverGround"))
    cog = _num(row.get("courseOverGround"))
    when = _unix_iso(row.get("msgtime"), now)
    pos = lla_to_ecef(lat, lon, 0.0)
    speed = (sog or 0.0) * 0.514444
    vx, vy, vz = (
        ecef_vel_from_track(lat, lon, speed, cog or 0.0)
        if speed > 0.5
        else (0.0, 0.0, 0.0)
    )
    return Entity(
        id=f"mmsi:{mmsi}",
        cls="vessel",
        layer="vessels",
        label=name,
        x=pos[0],
        y=pos[1],
        z=pos[2],
        vx=vx,
        vy=vy,
        vz=vz,
        when_unix=when,
        source="BarentsWatch AIS",
        freshness="live",
        confidence=0.85,
        cite=_CITE,
        meta={
            "mmsi": mmsi,
            "lat": lat,
            "lon": lon,
            "sog_kn": sog,
            "cog_deg": cog,
            "type": "barentswatch",
        },
        coverage=Coverage("eez", _COVERAGE),
    )


def _bearer(cid: str, secret: str) -> str:
    global _token, _token_until
    if _token and time.time() < _token_until - 60.0:
        return _token
    if not _host_pinned(urlparse(TOKEN_URL).hostname, TOKEN_HOST):
        return ""
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.post(
                TOKEN_URL,
                data={
                    "client_id": cid,
                    "client_secret": secret,
                    "scope": "ais",
                    "grant_type": "client_credentials",
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": _UA,
                },
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, TOKEN_HOST):
                return ""
            payload = resp.json()
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    token = str(payload.get("access_token") or "").strip()
    if not token:
        return ""
    try:
        ttl = float(payload.get("expires_in") or 3600.0)
    except (TypeError, ValueError):
        ttl = 3600.0
    _token = token
    _token_until = time.time() + max(60.0, ttl)
    return _token


def _get_latest(token: str) -> Any:
    if not _host_pinned(urlparse(LATEST_URL).hostname, LATEST_HOST):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                LATEST_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": _UA,
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, LATEST_HOST):
                return None
            return resp.json()
    except Exception:
        return None


def _unix_iso(stamp: Any, fallback: float) -> float:
    if not isinstance(stamp, str) or not stamp.strip():
        return fallback
    text = stamp.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
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
