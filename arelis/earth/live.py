"""Optional public feeds. Off unless EarthRuntime.live is on.

Hosts named here are pinned in tests/test_egress.py. Failures leave the
simulated layer in place. Keyed legal feeds are in; logging into a
camera you do not own is not an adapter.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from arelis.earth.adsb import fetch_adsb_mil
from arelis.earth.ais import fetch_ais
from arelis.earth.aprs import fetch_aprs
from arelis.earth.cameras import fetch_cameras
from arelis.earth.entity import Entity
from arelis.earth.eonet import fetch_eonet
from arelis.earth.firms import fetch_firms
from arelis.earth.frames import lla_to_ecef
from arelis.earth.gfw import fetch_gfw
from arelis.earth.launches import fetch_launches
from arelis.earth.radar import fetch_radar
from arelis.earth.radio import fetch_radio
from arelis.earth.shodan import fetch_shodan
from arelis.earth.store import EntityStore
from arelis.earth.tle import fetch_celestrak
from arelis.earth.traffic import fetch_traffic
from arelis.earth.wx import fetch_weather

# User-started live Earth zone only. Never from jobs.
USGS_ALL_DAY = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
)
OPENSKY_STATES = "https://opensky-network.org/api/states/all"

_TIMEOUT = 12.0
_PINNED_HOSTS = frozenset({"earthquake.usgs.gov", "opensky-network.org"})


def merge_live(store: EntityStore) -> None:
    quakes = fetch_usgs()
    if quakes:
        _replace_layer(store, "quakes", quakes)
    flights = fetch_opensky()
    if flights:
        civil = [e for e in flights if e.layer == "flights"]
        drones = [e for e in flights if e.layer == "drones"]
        _replace_layer(store, "flights", civil)
        _replace_layer(store, "drones", drones)
        _replace_layer(store, "military", [])
    military = fetch_adsb_mil()
    if military:
        _replace_layer(store, "military", military)
    vessels = fetch_ais()
    if vessels:
        _replace_layer(store, "vessels", vessels)
    frames = fetch_radar()
    sar = fetch_gfw()
    if frames is not None or sar is not None:
        _replace_layer(store, "radar", (frames or []) + (sar or []))
    sats = fetch_celestrak()
    if sats:
        iss = [e for e in sats if e.layer == "iss"]
        rest = [e for e in sats if e.layer != "iss"]
        if iss:
            _replace_layer(store, "iss", iss)
        if rest:
            _replace_layer(store, "satellites", rest)
    stations = fetch_radio()
    hams = fetch_aprs()
    radio = (stations or []) + (hams or [])
    if radio:
        _replace_layer(store, "radio", radio)
    cameras = fetch_cameras()
    banners = fetch_shodan()
    pins = (cameras or []) + (banners or [])
    if pins:
        _replace_layer(store, "cameras", pins)
    wx = fetch_weather()
    if wx:
        _replace_layer(store, "weather", wx)
    fires = fetch_firms()
    if fires:
        _replace_layer(store, "fires", fires)
    pads = fetch_launches()
    events = fetch_eonet()
    for e in (pads or []) + (events or []):
        store.upsert(e)
    incidents = fetch_traffic()
    if incidents:
        _replace_layer(store, "traffic", incidents)


def _replace_layer(store: EntityStore, layer: str, entities: list[Entity]) -> None:
    for e in list(store.in_layer(layer)):
        store.remove(e.id)
    for e in entities:
        store.upsert(e)


def fetch_usgs() -> list[Entity]:
    payload = _get_json(USGS_ALL_DAY)
    if not payload:
        return []
    out: list[Entity] = []
    for feat in (payload.get("features") or [])[:200]:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        try:
            lon = float(coords[0])
            lat = float(coords[1])
        except (TypeError, ValueError, IndexError):
            continue
        mag = props.get("mag")
        try:
            mag_f = float(mag) if mag is not None else 0.0
        except (TypeError, ValueError):
            mag_f = 0.0
        pos = lla_to_ecef(lat, lon, 0.0)
        qid = str(feat.get("id") or f"usgs:{lat:.3f}:{lon:.3f}")
        when = props.get("time")
        unix = float(when) / 1000.0 if isinstance(when, (int, float)) else 0.0
        out.append(
            Entity(
                id=f"usgs:{qid}",
                cls="quake",
                layer="quakes",
                label=f"M{mag_f:.1f} {props.get('place') or ''}".strip(),
                x=pos[0],
                y=pos[1],
                z=pos[2],
                when_unix=unix,
                source="USGS all_day",
                freshness="delayed",
                confidence=0.85,
                cite="USGS earthquake GeoJSON, last 24h. Delayed.",
                meta={"mag": mag_f, "lat": lat, "lon": lon, "place": props.get("place")},
            )
        )
    return out


# OpenSky category 14 = UAV. 16/17 are rare ADS-B ground vehicles, not every car.
_UAV_CAT = 14
_CAP = 2500
_CITE_ADSB = (
    "OpenSky /api/states/all. Every squawk in this poll, capped. "
    "Oceans without a receiver are empty. Not navigation. "
    "UAV category is the drones layer. Individual cars are not in this feed."
)


def fetch_opensky() -> list[Entity]:
    payload = _get_json(OPENSKY_STATES)
    if not payload:
        return []
    return entities_from_opensky(payload)


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
    vx = float(row[8] or 0.0) if row[8] is not None else 0.0
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
        when_unix=unix,
        source="OpenSky Network",
        freshness="delayed",
        confidence=0.7,
        cite=_CITE_ADSB,
        meta={
            "icao24": icao,
            "lat": lat_f,
            "lon": lon_f,
            "alt_m": alt_f,
            "category": cat,
            "uav": uav,
        },
    )


def _host_pinned(host: str | None) -> bool:
    if not host:
        return False
    name = host.lower()
    for pin in _PINNED_HOSTS:
        if name == pin or name.endswith("." + pin):
            return True
    return False


def _get_json(url: str) -> dict[str, Any] | None:
    if not _host_pinned(urlparse(url).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "ArelisEarth/0.2"})
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
