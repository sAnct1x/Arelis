"""OpenSky /api/states/all. OAuth2 client credentials. Not a VIN.

Basic username/password died March 2026. Account → API client →
credentials.json (clientId / clientSecret) into earth.opensky_client_id
/ _secret. POST auth.opensky-network.org for a Bearer token (~30 min).
401 refreshes once. Standard tier is 4,000 credits/day; a global
/states/all costs 4. We read X-Rate-Limit-Remaining and stop near the
cap, or on 429. extended=1 so UAV category 14 can split to drones.
Anonymous still works with no client. Failures return []. Token never
lands on entities. Hosts pinned in egress.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Entity
from arelis.earth.frames import ecef_vel_from_track, lla_to_ecef
from arelis.earth.secrets import earth_secret
from arelis.paths import state_dir

OPENSKY_STATES = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
OPENSKY_HOST = "opensky-network.org"
OPENSKY_AUTH_HOST = "auth.opensky-network.org"
CLIENT_ID_ENV = "ARELIS_OPENSKY_CLIENT_ID"
CLIENT_SECRET_ENV = "ARELIS_OPENSKY_CLIENT_SECRET"
BUDGET_PATH = state_dir() / "opensky_budget.json"
# Standard tier, from their Account card. Global /states/all costs 4;
# a laminated bbox costs 1. We never ask for the globe once the eye
# has a look box.
DAILY_LIMIT = 4_000
GLOBAL_COST = 4
BBOX_COST = 1
DAILY_STOP = 3_800
REMAINING_STOP = DAILY_LIMIT - DAILY_STOP
TOKEN_MARGIN_S = 30.0
_UAV_CAT = 14
_CAP = 2500
_TIMEOUT = 12.0
_UA = f"Arelis/{__version__} (+{__source_url__})"
_CITE = (
    "OpenSky /api/states/all. Every squawk in this poll, capped. "
    "Oceans without a receiver are empty. Not navigation. "
    "UAV category is the drones layer. Individual cars are not in this feed. "
    "OAuth2 client. Standard 4,000 credits/day; we stop near that cap."
)

_token = ""
_token_until = 0.0


def opensky_client_id(path=None) -> str:
    return earth_secret("opensky_client_id", CLIENT_ID_ENV, path)


def opensky_client_secret(path=None) -> str:
    return earth_secret("opensky_client_secret", CLIENT_SECRET_ENV, path)


def fetch_opensky(bbox: Any | None = None) -> list[Entity]:
    if not _credits_ok():
        return []
    from arelis.earth.lod import LookBBox

    box = bbox if isinstance(bbox, LookBBox) else None
    if box is None:
        payload = _states()
        if not payload:
            return []
        return entities_from_opensky(payload)
    out: list[Entity] = []
    seen: set[str] = set()
    for part in box.split():
        payload = _states(part)
        if not payload:
            continue
        for entity in entities_from_opensky(payload):
            if entity.id in seen:
                continue
            seen.add(entity.id)
            out.append(entity)
    return out


def entities_from_opensky(payload: dict[str, Any]) -> list[Entity]:
    states = payload.get("states") or []
    when = payload.get("time")
    unix = float(when) if isinstance(when, (int, float)) else 0.0
    out: list[Entity] = []
    for row in states:
        if not isinstance(row, (list, tuple)) or len(row) < 8:
            continue
        entity = _opensky_row(row, unix)
        if entity is None:
            continue
        out.append(entity)
        if len(out) >= _CAP:
            break
    return out


def _opensky_row(row: list[Any] | tuple[Any, ...], unix: float) -> Entity | None:
    icao = str(row[0] or "").strip()
    call = str(row[1] or "").strip() or icao
    lon, lat, alt = row[5], row[6], row[7]
    if lon is None or lat is None:
        return None
    try:
        lon_f, lat_f = float(lon), float(lat)
        alt_f = float(alt) if alt is not None else 10_000.0
    except (TypeError, ValueError):
        return None
    pos = lla_to_ecef(lat_f, lon_f, alt_f)
    vel = _row_float(row, 9)
    track = _row_float(row, 10)
    climb = _row_float(row, 11)
    vx, vy, vz = (
        ecef_vel_from_track(lat_f, lon_f, vel, track, climb)
        if vel > 0.5
        else (0.0, 0.0, 0.0)
    )
    try:
        cat = int(row[17]) if len(row) > 17 and row[17] is not None else 0
    except (TypeError, ValueError):
        cat = 0
    uav = cat == _UAV_CAT
    return Entity(
        id=f"icao:{icao or call}",
        cls="aircraft",
        layer="drones" if uav else "flights",
        label=call,
        x=pos[0],
        y=pos[1],
        z=pos[2],
        vx=vx,
        vy=vy,
        vz=vz,
        when_unix=unix,
        source="OpenSky Network",
        freshness="delayed",
        confidence=0.7,
        cite=_CITE,
        meta={
            "icao24": icao,
            "lat": lat_f,
            "lon": lon_f,
            "alt_m": alt_f,
            "gs_mps": vel,
            "track_deg": track,
            "category": cat,
            "uav": uav,
        },
    )


def _row_float(row: list[Any] | tuple[Any, ...], idx: int) -> float:
    if len(row) <= idx or row[idx] is None:
        return 0.0
    try:
        return float(row[idx])
    except (TypeError, ValueError):
        return 0.0


def _states(bbox: Any | None = None) -> dict[str, Any] | None:
    extra = {"bbox": bbox} if bbox is not None else {}
    payload, status = _get_states(_bearer(), **extra)
    if status == 401:
        _forget_token()
        payload, status = _get_states(_bearer(), **extra)
    if status == 429:
        return None
    return payload


def _bbox_params(bbox: Any | None) -> dict[str, float]:
    from arelis.earth.lod import LookBBox

    if not isinstance(bbox, LookBBox):
        return {}
    return {
        "lamin": bbox.south,
        "lomin": bbox.west,
        "lamax": bbox.north,
        "lomax": bbox.east,
    }


def _get_states(token: str, *, bbox: Any | None = None) -> tuple[dict[str, Any] | None, int]:
    if not _host_pinned(urlparse(OPENSKY_STATES).hostname, OPENSKY_HOST):
        return None, 0
    headers = {"User-Agent": _UA, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    params: dict[str, Any] = {"extended": "1"}
    params.update(_bbox_params(bbox))
    cost = BBOX_COST if _bbox_params(bbox) else GLOBAL_COST
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                OPENSKY_STATES,
                params=params,
                headers=headers,
            )
            _note_response(resp, cost=cost)
            if resp.status_code in (401, 429):
                return None, resp.status_code
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname, OPENSKY_HOST):
                return None, resp.status_code
            data = resp.json()
    except Exception:
        return None, 0
    if isinstance(data, dict):
        return data, 200
    return None, 0


def _bearer() -> str:
    global _token, _token_until
    if _token and time.time() < _token_until:
        return _token
    client_id = opensky_client_id()
    secret = opensky_client_secret()
    if not client_id or not secret:
        return ""
    if not _host_pinned(urlparse(OPENSKY_TOKEN).hostname, OPENSKY_AUTH_HOST):
        return ""
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.post(
                OPENSKY_TOKEN,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": secret,
                },
                headers={
                    "User-Agent": _UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            resp.raise_for_status()
            if not _host_pinned(
                urlparse(str(resp.url)).hostname, OPENSKY_AUTH_HOST
            ):
                return ""
            data = resp.json()
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""
    access = str(data.get("access_token") or "").strip()
    if not access:
        return ""
    expires = float(data.get("expires_in") or 1800)
    _token = access
    _token_until = time.time() + max(expires - TOKEN_MARGIN_S, 1.0)
    return _token


def _forget_token() -> None:
    global _token, _token_until
    _token = ""
    _token_until = 0.0


def _credits_ok() -> bool:
    budget = _load_budget()
    _unmute_if_due(budget)
    if budget.get("muted"):
        return False
    if budget.get("day") != _today():
        return True
    remaining = budget.get("remaining")
    if remaining is not None and int(remaining) <= REMAINING_STOP:
        return False
    spent = int(budget.get("spent") or 0)
    return spent < DAILY_STOP


def _note_response(resp: httpx.Response, *, cost: int = GLOBAL_COST) -> None:
    budget = _load_budget()
    today = _today()
    if budget.get("day") != today:
        budget["day"] = today
        budget["spent"] = 0
        budget["remaining"] = None
        budget["muted"] = False
        budget["muted_until"] = 0.0
    if resp.status_code not in (401,):
        budget["spent"] = int(budget.get("spent") or 0) + int(cost)
    remaining = _header_int(resp, "x-rate-limit-remaining")
    if remaining is not None:
        budget["remaining"] = remaining
    retry = _header_int(resp, "x-rate-limit-retry-after-seconds")
    close = (
        resp.status_code == 429
        or (remaining is not None and remaining <= REMAINING_STOP)
        or int(budget["spent"]) >= DAILY_STOP
    )
    if close:
        budget["muted"] = True
        if resp.status_code == 429 and retry:
            budget["muted_until"] = time.time() + float(retry)
        else:
            budget["muted_until"] = _next_utc_midnight()
    _save_budget(budget)
    try:
        from arelis.physics.telemetry import emit

        emit(
            "opensky_budget",
            status=resp.status_code,
            cost=int(cost),
            spent=int(budget.get("spent") or 0),
            remaining=budget.get("remaining"),
            muted=bool(budget.get("muted")),
        )
    except Exception:
        pass


def _unmute_if_due(budget: dict[str, Any]) -> bool:
    if not budget.get("muted"):
        return True
    until = float(budget.get("muted_until") or 0.0)
    if until and time.time() >= until:
        budget["muted"] = False
        budget["muted_until"] = 0.0
        if budget.get("day") != _today():
            budget["day"] = _today()
            budget["spent"] = 0
            budget["remaining"] = None
        _save_budget(budget)
        return True
    return False


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _next_utc_midnight() -> float:
    now = datetime.now(UTC)
    nxt = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return nxt.timestamp() + 86_400.0


def _header_int(resp: httpx.Response, name: str) -> int | None:
    raw = resp.headers.get(name)
    if raw is None:
        raw = resp.headers.get(name.title())
    if raw is None:
        return None
    try:
        return int(float(str(raw).strip()))
    except (TypeError, ValueError):
        return None


def _load_budget() -> dict[str, Any]:
    try:
        raw = json.loads(BUDGET_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_budget(budget: dict[str, Any]) -> None:
    try:
        BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
        BUDGET_PATH.write_text(
            json.dumps(budget, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError:
        return


def _host_pinned(host: str | None, pin: str) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == pin or name.endswith("." + pin)
