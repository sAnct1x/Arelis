"""Optional public feeds. Off unless EarthRuntime.live is on.

Hosts named here are pinned in tests/test_egress.py. Failures leave the
simulated layer in place. Keyed legal feeds are in; logging into a
camera you do not own is not an adapter.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlparse

import httpx

from arelis.earth.adsb import fetch_adsb_mil
from arelis.earth.airports import fetch_airports
from arelis.earth.ais import fetch_ais
from arelis.earth.aprs import fetch_aprs
from arelis.earth.argo import fetch_argo
from arelis.earth.cameras import fetch_cameras
from arelis.earth.emsc import fetch_emsc
from arelis.earth.entity import Entity
from arelis.earth.eonet import fetch_eonet
from arelis.earth.firms import fetch_firms
from arelis.earth.frames import ecef_vel_from_track, lla_to_ecef
from arelis.earth.gdacs import fetch_gdacs
from arelis.earth.geonet import fetch_geonet
from arelis.earth.gfw import fetch_gfw
from arelis.earth.launches import fetch_launches
from arelis.earth.metar import fetch_metar
from arelis.earth.ndbc import fetch_ndbc
from arelis.earth.nws import fetch_nws
from arelis.earth.radar import fetch_radar
from arelis.earth.radio import fetch_radio
from arelis.earth.satnogs import fetch_satnogs
from arelis.earth.secrets import earth_secret
from arelis.earth.shodan import fetch_shodan
from arelis.earth.spacetrack import fetch_spacetrack, fetch_tip
from arelis.earth.store import EntityStore
from arelis.earth.swpc import fetch_swpc
from arelis.earth.tides import fetch_tides
from arelis.earth.tle import fetch_celestrak
from arelis.earth.traffic import fetch_traffic
from arelis.earth.volcanoes import fetch_volcanoes
from arelis.earth.waqi import fetch_waqi
from arelis.earth.wx import fetch_weather

# User-started live Earth zone only. Never from jobs.
USGS_ALL_DAY = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
)
OPENSKY_STATES = "https://opensky-network.org/api/states/all"

_TIMEOUT = 12.0
_PINNED_HOSTS = frozenset({"earthquake.usgs.gov", "opensky-network.org"})


def merge_live(store: EntityStore) -> None:
    """Pull shipped adapters in parallel. Apply in a stable order."""
    got = _gather(
        {
            "usgs": fetch_usgs,
            "emsc": fetch_emsc,
            "geonet": fetch_geonet,
            "opensky": fetch_opensky,
            "adsb": fetch_adsb_mil,
            "ais": fetch_ais,
            "radar": fetch_radar,
            "gfw": fetch_gfw,
            "celestrak": fetch_celestrak,
            "spacetrack": fetch_spacetrack,
            "radio": fetch_radio,
            "aprs": fetch_aprs,
            "satnogs": fetch_satnogs,
            "cameras": fetch_cameras,
            "shodan": fetch_shodan,
            "weather": fetch_weather,
            "nws": fetch_nws,
            "swpc": fetch_swpc,
            "metar": fetch_metar,
            "waqi": fetch_waqi,
            "ndbc": fetch_ndbc,
            "tides": fetch_tides,
            "firms": fetch_firms,
            "launches": fetch_launches,
            "eonet": fetch_eonet,
            "airports": fetch_airports,
            "tip": fetch_tip,
            "volcanoes": fetch_volcanoes,
            "gdacs": fetch_gdacs,
            "argo": fetch_argo,
            "traffic": fetch_traffic,
        }
    )
    quakes = (got["usgs"] or []) + (got["emsc"] or []) + (got["geonet"] or [])
    if quakes:
        _replace_layer(store, "quakes", quakes)
    flights = got["opensky"]
    if flights:
        civil = [e for e in flights if e.layer == "flights"]
        drones = [e for e in flights if e.layer == "drones"]
        _replace_layer(store, "flights", civil)
        _replace_layer(store, "drones", drones)
        _replace_layer(store, "military", [])
    military = got["adsb"]
    if military:
        _replace_layer(store, "military", military)
    vessels = got["ais"]
    if vessels:
        _replace_layer(store, "vessels", vessels)
    frames = got["radar"]
    sar = got["gfw"]
    if frames is not None or sar is not None:
        _replace_layer(store, "radar", (frames or []) + (sar or []))
    sats = _merge_sats(got["celestrak"], got["spacetrack"])
    if sats:
        iss = [e for e in sats if e.layer == "iss"]
        rest = [e for e in sats if e.layer != "iss"]
        if iss:
            _replace_layer(store, "iss", iss)
        if rest:
            _replace_layer(store, "satellites", rest)
    radio = (got["radio"] or []) + (got["aprs"] or []) + (got["satnogs"] or [])
    if radio:
        _replace_layer(store, "radio", radio)
    pins = (got["cameras"] or []) + (got["shodan"] or [])
    if pins:
        _replace_layer(store, "cameras", pins)
    weather = (
        (got["weather"] or [])
        + (got["nws"] or [])
        + (got["swpc"] or [])
        + (got["metar"] or [])
        + (got["waqi"] or [])
        + (got["ndbc"] or [])
        + (got["tides"] or [])
    )
    if weather:
        _replace_layer(store, "weather", weather)
    fires = got["firms"]
    if fires:
        _replace_layer(store, "fires", fires)
    for e in (
        (got["launches"] or [])
        + (got["eonet"] or [])
        + (got["airports"] or [])
        + (got["tip"] or [])
        + (got["volcanoes"] or [])
        + (got["gdacs"] or [])
        + (got["argo"] or [])
    ):
        store.upsert(e)
    incidents = got["traffic"]
    if incidents:
        _replace_layer(store, "traffic", incidents)


def _gather(jobs: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {key: None for key in jobs}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = {key: pool.submit(_safe, fn) for key, fn in jobs.items()}
        for key, fut in futs.items():
            out[key] = fut.result()
    return out


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception:
        return None


def _merge_sats(
    celestrak: list[Entity] | None, official: list[Entity] | None
) -> list[Entity] | None:
    if not celestrak and not official:
        return None
    by_id: dict[str, Entity] = {}
    for entity in celestrak or []:
        by_id[entity.id] = entity
    for entity in official or []:
        by_id[entity.id] = entity
    return list(by_id.values())


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
    payload = _get_json(OPENSKY_STATES, auth=_opensky_auth())
    if not payload:
        return []
    return entities_from_opensky(payload)


def _opensky_auth() -> tuple[str, str] | None:
    user = earth_secret("opensky_user", "ARELIS_OPENSKY_USER")
    password = earth_secret("opensky_password", "ARELIS_OPENSKY_PASSWORD")
    if user and password:
        return (user, password)
    return None


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
        cite=_CITE_ADSB,
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


def _host_pinned(host: str | None) -> bool:
    if not host:
        return False
    name = host.lower()
    for pin in _PINNED_HOSTS:
        if name == pin or name.endswith("." + pin):
            return True
    return False


def _get_json(
    url: str, auth: tuple[str, str] | None = None
) -> dict[str, Any] | None:
    if not _host_pinned(urlparse(url).hostname):
        return None
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "ArelisEarth/0.2"},
                auth=auth,
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
