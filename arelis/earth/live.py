"""Optional public feeds. Off unless EarthRuntime.live is on.

Distance-gated by arelis.earth.lod: space fetches satellites, approach
fetches local planes, near adds boats, city opens the rest if the chip
is on. Hosts named here are pinned in tests/test_egress.py. Failures
leave the simulated layer in place. Keyed legal feeds are in; logging
into a camera you do not own is not an adapter.
"""

from __future__ import annotations

import time
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
from arelis.earth.fdsn import fetch_fdsn
from arelis.earth.firms import fetch_firms
from arelis.earth.frames import lla_to_ecef
from arelis.earth.gdacs import fetch_gdacs
from arelis.earth.geonet import fetch_geonet
from arelis.earth.gfw import fetch_gfw
from arelis.earth.launches import fetch_launches
from arelis.earth.lod import EarthView, adapter_allowed, filter_to_view, organize
from arelis.earth.metar import fetch_metar
from arelis.earth.ndbc import fetch_ndbc
from arelis.earth.nws import fetch_nws
from arelis.earth.openaq import fetch_openaq
from arelis.earth.opensky import fetch_opensky
from arelis.earth.radar import fetch_radar
from arelis.earth.radio import fetch_radio
from arelis.earth.rwis import fetch_rwis
from arelis.earth.satnogs import fetch_satnogs
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

_TIMEOUT = 12.0
_PINNED_HOSTS = frozenset({"earthquake.usgs.gov"})


def _adapter_fns() -> dict[str, Callable[[], Any]]:
    """Looked up at call time so tests can mute live.fetch_*."""
    return {
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
        "openaq": fetch_openaq,
        "ndbc": fetch_ndbc,
        "tides": fetch_tides,
        "rwis": fetch_rwis,
        "firms": fetch_firms,
        "launches": fetch_launches,
        "eonet": fetch_eonet,
        "airports": fetch_airports,
        "tip": fetch_tip,
        "volcanoes": fetch_volcanoes,
        "gdacs": fetch_gdacs,
        "argo": fetch_argo,
        "fdsn": fetch_fdsn,
        "traffic": fetch_traffic,
    }


def merge_live(
    store: EntityStore,
    view: EarthView | None = None,
    layers: dict[str, bool] | None = None,
    only: tuple[str, ...] | None = None,
) -> None:
    """Pull the adapters this band and these chips allow. Skip the rest.

    No view (tests, first tool live) runs the full set, same as before.
    A space/approach/near view does not call city catalogs. Layers that
    were not fetched stay put — we do not wipe cameras because sats ran.
    """
    jobs = _jobs(view, layers, only)
    if not jobs:
        return
    try:
        from arelis.guard import get_watch

        if not get_watch().egress_open():
            from arelis.physics.telemetry import emit

            emit(
                "live_merge",
                band=view.band if view is not None else "full",
                n_jobs=0,
                skipped="watch_mute",
            )
            return
    except Exception:
        pass
    t0 = time.perf_counter()
    got = _gather(jobs)
    _apply_live(store, got, set(jobs), view)
    try:
        from arelis.physics.telemetry import emit

        counts = {
            key: (len(val) if isinstance(val, list) else 0 if val is None else 1)
            for key, val in got.items()
        }
        emit(
            "live_merge",
            band=view.band if view is not None else "full",
            n_jobs=len(jobs),
            ms=int((time.perf_counter() - t0) * 1000),
            adapters=sorted(jobs),
            got=sum(counts.values()),
            empty=sum(1 for val in got.values() if not val),
        )
    except Exception:
        pass


def _jobs(
    view: EarthView | None,
    layers: dict[str, bool] | None,
    only: tuple[str, ...] | None,
) -> dict[str, Callable[[], Any]]:
    band = view.band if view is not None else None
    jobs: dict[str, Callable[[], Any]] = {}
    for key, fn in _adapter_fns().items():
        if only is not None and key not in only:
            continue
        if band is not None and not adapter_allowed(key, band, layers):
            continue
        if band is None and layers is not None and not adapter_allowed(key, "city", layers):
            continue
        if key == "opensky" and view is not None and view.bbox is not None:
            box = view.bbox
            jobs[key] = lambda b=box: fetch_opensky(bbox=b)
        else:
            jobs[key] = fn
    return jobs


def _kept(entities: list[Entity] | None, view: EarthView | None) -> list[Entity]:
    return organize(filter_to_view(list(entities or []), view), view)


def _apply_live(
    store: EntityStore,
    got: dict[str, Any],
    ran: set[str],
    view: EarthView | None,
) -> None:
    if {"usgs", "emsc", "geonet"} & ran:
        quakes = _kept(
            (got.get("usgs") or [])
            + (got.get("emsc") or [])
            + (got.get("geonet") or []),
            view,
        )
        if quakes:
            _replace_layer(store, "quakes", quakes)
    if "opensky" in ran:
        flights = got.get("opensky")
        if flights:
            civil = _kept([e for e in flights if e.layer == "flights"], view)
            drones = _kept([e for e in flights if e.layer == "drones"], view)
            _replace_layer(store, "flights", civil)
            _replace_layer(store, "drones", drones)
            if "adsb" not in ran:
                _replace_layer(store, "military", [])
    if "adsb" in ran:
        military = _kept(got.get("adsb"), view)
        if military:
            _replace_layer(store, "military", military)
    if "ais" in ran:
        vessels = _kept(got.get("ais"), view)
        if vessels:
            _replace_layer(store, "vessels", vessels)
    if {"radar", "gfw"} & ran:
        frames = got.get("radar") if "radar" in ran else None
        sar = got.get("gfw") if "gfw" in ran else None
        if frames or sar:
            kept = _kept((frames or []) + (sar or []), view)
            if kept:
                _replace_layer(store, "radar", kept)
    if {"celestrak", "spacetrack"} & ran:
        sats = _merge_sats(got.get("celestrak"), got.get("spacetrack"))
        if sats:
            iss = [e for e in sats if e.layer == "iss"]
            rest = [e for e in sats if e.layer != "iss"]
            if iss:
                _replace_layer(store, "iss", iss)
            if rest:
                _replace_layer(store, "satellites", rest)
    if {"radio", "aprs", "satnogs"} & ran:
        radio = _kept(
            (got.get("radio") or [])
            + (got.get("aprs") or [])
            + (got.get("satnogs") or []),
            view,
        )
        if radio:
            _replace_layer(store, "radio", radio)
    if {"cameras", "shodan"} & ran:
        pins = _kept((got.get("cameras") or []) + (got.get("shodan") or []), view)
        if pins:
            _replace_layer(store, "cameras", pins)
    weather_keys = {
        "weather",
        "nws",
        "swpc",
        "metar",
        "waqi",
        "openaq",
        "ndbc",
        "tides",
        "rwis",
    }
    if weather_keys & ran:
        weather = _kept(
            (got.get("weather") or [])
            + (got.get("nws") or [])
            + (got.get("swpc") or [])
            + (got.get("metar") or [])
            + (got.get("waqi") or [])
            + (got.get("openaq") or [])
            + (got.get("ndbc") or [])
            + (got.get("tides") or [])
            + (got.get("rwis") or []),
            view,
        )
        if weather:
            _replace_layer(store, "weather", weather)
    if "firms" in ran:
        fires = _kept(got.get("firms"), view)
        if fires:
            _replace_layer(store, "fires", fires)
    site_keys = (
        "launches",
        "eonet",
        "airports",
        "tip",
        "volcanoes",
        "gdacs",
        "argo",
        "fdsn",
    )
    if set(site_keys) & ran:
        sites: list[Entity] = []
        for k in site_keys:
            if k in ran:
                sites.extend(got.get(k) or [])
        for e in _kept(sites, view):
            store.upsert(e)
    if "traffic" in ran:
        incidents = _kept(got.get("traffic"), view)
        if incidents:
            _replace_layer(store, "traffic", incidents)


def _gather(jobs: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {key: None for key in jobs}
    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = {key: pool.submit(_safe, key, fn) for key, fn in jobs.items()}
        for key, fut in futs.items():
            out[key] = fut.result()
    return out


def _safe(key: str, fn: Callable[[], Any]) -> Any:
    t0 = time.perf_counter()
    err = ""
    try:
        result = fn()
    except Exception as exc:
        err = type(exc).__name__
        result = None
    try:
        from arelis.physics.telemetry import emit

        n = len(result) if isinstance(result, list) else (0 if result is None else 1)
        emit(
            "adapter",
            name=key,
            ok=err == "",
            n=n,
            ms=int((time.perf_counter() - t0) * 1000),
            err=err,
        )
    except Exception:
        pass
    return result


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
            resp = client.get(
                url,
                headers={"User-Agent": "ArelisEarth/0.2"},
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None
