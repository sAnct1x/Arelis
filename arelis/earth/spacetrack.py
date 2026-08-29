"""Space-Track GP + TIP. Free account. Official SSA, not a paid product.

Register at https://www.space-track.org/auth/createAccount (a .edu login
is accepted). Identity/password from earth.spacetrack_user / _password or
ARELIS_SPACETRACK_USER / _PASSWORD. Session cookie only. Credentials never
land on entities. Sample payloads + ISS, not the painted catalog. TIP
reentries upsert onto sites. Failures return None so CelesTrak stays.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis import __source_url__, __version__
from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import lla_to_ecef
from arelis.earth.secrets import earth_secret
from arelis.earth.tle import entities_from_tle_text

SPACETRACK_HOST = "www.space-track.org"
SPACETRACK_LOGIN = "https://www.space-track.org/ajaxauth/login"
# ISS + LEO / MEO / GEO payload samples. Not the painted catalog.
_GP_PATHS = (
    "/basicspacedata/query/class/gp/NORAD_CAT_ID/25544/format/3le",
    "/basicspacedata/query/class/gp/OBJECT_TYPE/PAYLOAD/PERIOD/<128/orderby/NORAD_CAT_ID/limit/250/format/3le",
    "/basicspacedata/query/class/gp/OBJECT_TYPE/PAYLOAD/PERIOD/500--800/orderby/NORAD_CAT_ID/limit/40/format/3le",
    "/basicspacedata/query/class/gp/OBJECT_TYPE/PAYLOAD/PERIOD/1400--1500/orderby/NORAD_CAT_ID/limit/60/format/3le",
)
TIP_PATH = (
    "/basicspacedata/query/class/tip/orderby/INSERT_EPOCH desc/limit/20/format/json"
)
USER_ENV = "ARELIS_SPACETRACK_USER"
PASS_ENV = "ARELIS_SPACETRACK_PASSWORD"
_UA = f"Arelis/{__version__} (+{__source_url__})"
_TIMEOUT = 20.0
_CAP = 400
_CITE = (
    "Space-Track GP TLE + SGP4 (18 SDS / USSPACECOM). Free account. "
    "Payload sample + ISS, not the painted catalog. Classified objects absent. "
    "Do not republish the dump."
)
_TIP_CITE = (
    "Space-Track TIP reentry prediction. Public class. A predicted decay, "
    "not a hull name and not a guarantee."
)


def spacetrack_user(path=None) -> str:
    return earth_secret("spacetrack_user", USER_ENV, path)


def spacetrack_password(path=None) -> str:
    return earth_secret("spacetrack_password", PASS_ENV, path)


def fetch_spacetrack(*, unix: float | None = None) -> list[Entity] | None:
    """None if no account, login failed, or sgp4 missing. Keep CelesTrak."""
    user = spacetrack_user()
    password = spacetrack_password()
    if not user or not password:
        return None
    if not _sgp4_ready():
        return None
    now = unix if unix is not None else _now()
    texts = _drain_gp(user, password)
    if not texts:
        return None
    out: list[Entity] = []
    seen: set[int] = set()
    for text in texts:
        for entity in entities_from_tle_text(text, unix=now, cap=_CAP):
            norad = int(entity.meta.get("norad") or 0)
            if norad in seen:
                continue
            seen.add(norad)
            entity.source = "Space-Track GP"
            entity.cite = _CITE
            entity.meta = {**entity.meta, "ssa": "space-track", "sample": True}
            out.append(entity)
            if len(out) >= _CAP:
                return out
    return out or None


def fetch_tip() -> list[Entity] | None:
    user = spacetrack_user()
    password = spacetrack_password()
    if not user or not password:
        return None
    rows = _get_json(user, password, TIP_PATH)
    if not isinstance(rows, list):
        return None
    return entities_from_tip(rows) or None


def entities_from_tip(rows: list[Any]) -> list[Entity]:
    out: list[Entity] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        entity = _entity_from_tip(row)
        if entity is None or entity.id in seen:
            continue
        seen.add(entity.id)
        out.append(entity)
        if len(out) >= 20:
            break
    return out


def _entity_from_tip(row: dict[str, Any]) -> Entity | None:
    lat = _num(row.get("LAT") or row.get("lat"))
    lon = _num(row.get("LON") or row.get("lon") or row.get("LONG"))
    if lat is None or lon is None:
        return None
    if abs(lat) > 90.0 or abs(lon) > 180.0:
        return None
    norad = str(row.get("NORAD_CAT_ID") or row.get("OBJECT_NUMBER") or "").strip()
    name = str(row.get("OBJECT_NAME") or norad or "TIP").strip()
    if not norad and not name:
        return None
    pos = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=f"tip:{norad or name.casefold()[:32]}",
        cls="site",
        layer="sites",
        label=f"TIP {name}"[:80],
        x=pos[0],
        y=pos[1],
        z=pos[2],
        source="Space-Track TIP",
        freshness="delayed",
        confidence=0.45,
        cite=_TIP_CITE,
        meta={"lat": lat, "lon": lon, "norad": norad, "name": name},
        coverage=Coverage(
            "tip",
            "Predicted decay window. Not a hull. Not a guarantee.",
        ),
    )


def _sgp4_ready() -> bool:
    try:
        from sgp4.api import Satrec  # noqa: F401
    except ImportError:
        return False
    return True


def _now() -> float:
    import time

    return time.time()


def _host_pinned(host: str | None) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == SPACETRACK_HOST or name.endswith("." + SPACETRACK_HOST)


def _client(user: str, password: str) -> httpx.Client | None:
    if not _host_pinned(urlparse(SPACETRACK_LOGIN).hostname):
        return None
    client = httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        resp = client.post(
            SPACETRACK_LOGIN,
            data={"identity": user, "password": password},
            headers={"User-Agent": _UA},
        )
        resp.raise_for_status()
        if not _host_pinned(urlparse(str(resp.url)).hostname):
            client.close()
            return None
        if "Failed" in (resp.text or "") and "login" in (resp.text or "").casefold():
            client.close()
            return None
    except Exception:
        client.close()
        return None
    return client


def _drain_gp(user: str, password: str) -> list[str]:
    client = _client(user, password)
    if client is None:
        return []
    out: list[str] = []
    try:
        for path in _GP_PATHS:
            url = f"https://{SPACETRACK_HOST}{path}"
            if not _host_pinned(urlparse(url).hostname):
                continue
            resp = client.get(url, headers={"User-Agent": _UA})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                continue
            text = resp.text
            if isinstance(text, str) and "1 " in text:
                out.append(text)
    except Exception:
        return out
    finally:
        client.close()
    return out


def _get_json(user: str, password: str, path: str) -> Any:
    client = _client(user, password)
    if client is None:
        return None
    url = f"https://{SPACETRACK_HOST}{path}"
    try:
        if not _host_pinned(urlparse(url).hostname):
            return None
        resp = client.get(url, headers={"User-Agent": _UA})
        resp.raise_for_status()
        if not _host_pinned(urlparse(str(resp.url)).hostname):
            return None
        return resp.json()
    except Exception:
        return None
    finally:
        client.close()


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
