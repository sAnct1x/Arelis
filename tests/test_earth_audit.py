"""Phase 0 net for the Earth/Reality audit.

These tests are designed to go red when the named flaw returns.
Inventory counts in test_earth.py are not this file.
"""

from __future__ import annotations

import pytest

from arelis.earth.entity import Entity
from arelis.earth.frames import lla_to_ecef
from arelis.earth.runtime import EarthRuntime, set_earth
from arelis.earth.store import EntityStore
from arelis.tools.earth_tool import EarthTool

# Frozen 2026-09-19 against feeds.FEEDS. Deleting a region must update this.
FEEDS_PIN: dict[str, str] = {
    "usgs": "shipped",
    "opensky": "shipped",
    "adsb-mil": "shipped",
    "aisstream": "keyed",
    "celestrak": "shipped",
    "radio-browser": "shipped",
    "tfl-jamcam": "shipped",
    "caltrans-cctv": "shipped",
    "open-meteo": "shipped",
    "launches": "shipped",
    "firms": "keyed",
    "digitraffic": "shipped",
    "eonet": "shipped",
    "tfl-road": "shipped",
    "osm-webcams": "shipped",
    "sentinel1-asf": "shipped",
    "viirs-boats": "later",
    "sat-ais": "out",
    "barentswatch": "keyed",
    "gfw-sar": "keyed",
    "nyc-dot": "shipped",
    "sg-lta": "shipped",
    "fi-weathercam": "shipped",
    "hk-td": "shipped",
    "osm-tiles": "shipped",
    "osm-nominatim": "shipped",
    "fi-traffic": "shipped",
    "aprs": "keyed",
    "caltrans-lcs": "shipped",
    "drivebc": "shipped",
    "nsw-live": "shipped",
    "qld-traffic": "shipped",
    "nzta": "shipped",
    "on-511": "shipped",
    "mb-511": "shipped",
    "ns-511": "shipped",
    "ab-511": "shipped",
    "sk-511": "shipped",
    "fl-511": "shipped",
    "ny-511": "shipped",
    "cotrip": "shipped",
    "ia-511": "shipped",
    "mn-511": "shipped",
    "ga-511": "shipped",
    "nws": "shipped",
    "ourairports": "shipped",
    "spacetrack": "keyed",
    "swpc-ovation": "shipped",
    "emsc": "shipped",
    "satnogs": "shipped",
    "metar": "shipped",
    "waqi": "keyed",
    "ndbc": "shipped",
    "usgs-volcanoes": "shipped",
    "gdacs": "shipped",
    "geonet": "shipped",
    "wzdx-ut": "shipped",
    "wzdx-ky": "shipped",
    "wzdx-mo": "shipped",
    "wzdx-wi": "shipped",
    "wzdx-id": "shipped",
    "md-chart": "shipped",
    "sa-traffic": "shipped",
    "wa-traffic": "shipped",
    "sa-closures": "shipped",
    "wa-roadworks": "shipped",
    "wa-events": "shipped",
    "nd-511": "shipped",
    "wzdx-az": "shipped",
    "wzdx-la": "shipped",
    "wzdx-ia": "shipped",
    "wzdx-mn": "shipped",
    "wzdx-ga": "shipped",
    "on-cameras": "shipped",
    "mb-cameras": "shipped",
    "ns-cameras": "shipped",
    "ab-cameras": "shipped",
    "sk-cameras": "shipped",
    "fl-cameras": "shipped",
    "ny-cameras": "shipped",
    "co-cameras": "shipped",
    "ia-cameras": "shipped",
    "mn-cameras": "shipped",
    "ga-cameras": "shipped",
    "tripcheck": "shipped",
    "md-cameras": "shipped",
    "nd-cameras": "shipped",
    "al-algo": "shipped",
    "de-deldot": "shipped",
    "nz-cameras": "shipped",
    "qc-cameras": "shipped",
    "qc-events": "shipped",
    "de-autobahn": "shipped",
    "wzdx-nc": "shipped",
    "wzdx-in": "shipped",
    "wzdx-ks": "shipped",
    "wzdx-wa": "shipped",
    "wzdx-nb": "shipped",
    "wzdx-pe": "shipped",
    "wzdx-yt": "shipped",
    "wzdx-ak": "shipped",
    "wzdx-nv": "shipped",
    "coops": "shipped",
    "ioc-sealevel": "shipped",
    "argo": "shipped",
    "ingv-stations": "shipped",
    "geofon-stations": "shipped",
    "iris-iu": "shipped",
    "nrcan-stations": "shipped",
    "geonet-stations": "shipped",
    "mo-cameras": "shipped",
    "qc-chantiers": "shipped",
    "qc-conditions": "shipped",
    "fi-rwis": "shipped",
    "lt-rwis": "shipped",
    "qc-rwis": "shipped",
    "tx-drivetexas": "keyed",
    "nsw-cameras": "keyed",
    "wa-wsdot-cameras": "keyed",
    "wa-wsdot-alerts": "keyed",
    "oh-ohgo-cameras": "keyed",
    "oh-ohgo-events": "keyed",
    "nc-drivenc-cameras": "keyed",
    "cars-ut": "keyed",
    "cars-az": "keyed",
    "cars-id": "keyed",
    "cars-wi": "keyed",
    "cars-la": "keyed",
    "cars-ak": "keyed",
    "cars-nv": "keyed",
    "cars-ct": "keyed",
    "cars-ne": "keyed",
    "openaq": "keyed",
    "earthdata": "later",
    "copernicus-dataspace": "later",
    "owned-rtsp": "shipped",
    "contacts": "shipped",
    "unsecured-cams": "out",
    "face-index": "out",
    "car-vin": "out",
}


def _plane(eid: str, lat: float, lon: float) -> Entity:
    x, y, z = lla_to_ecef(lat, lon, 10_000.0)
    return Entity(
        id=eid,
        cls="aircraft",
        layer="flights",
        label="last city",
        x=x,
        y=y,
        z=z,
        freshness="live",
        source="OpenSky",
    )


def _ship(eid: str, lat: float, lon: float) -> Entity:
    x, y, z = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=eid,
        cls="vessel",
        layer="vessels",
        label="last harbor",
        x=x,
        y=y,
        z=z,
        freshness="live",
        source="AIS",
    )


def _cam(eid: str, lat: float, lon: float) -> Entity:
    x, y, z = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=eid,
        cls="camera",
        layer="cameras",
        label="last city cam",
        x=x,
        y=y,
        z=z,
        freshness="live",
        source="OSM",
    )


def test_opensky_timeout_keeps_sim() -> None:
    from arelis.earth.live import _apply_live

    store = EntityStore()
    store.upsert(_plane("icao:sim", 40.7, -74.0))
    _apply_live(store, {"opensky": None}, {"opensky"}, view=None)
    assert len(store.in_layer("flights")) == 1
    assert store.get("icao:sim") is not None


def test_pause_is_not_earth_live_off() -> None:
    from arelis.spatial.verbs import classify_physics_act, classify_physics_verb

    assert classify_physics_verb("pause") == "pause"
    assert classify_physics_act("pause").verb == "pause"
    live = classify_physics_act("turn live off")
    assert live is not None
    assert live.verb == "earth_layer"
    assert live.flag == "live"
    assert live.on is False
    buildings = classify_physics_act("show buildings")
    assert buildings is None or buildings.verb != "earth_layer"


@pytest.mark.asyncio
async def test_earth_tool_verbs_and_goto_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: True)
    set_earth(EarthRuntime())
    tool = EarthTool()
    st = await tool.run(action="status")
    assert st.ok
    entered = await tool.run(action="enter")
    assert entered.ok
    earth = entered.data
    assert earth["active"] is True
    miss = await tool.run(action="goto", query="zzzz-not-a-place-on-earth")
    assert not miss.ok
    assert miss.data.get("fail_class") == "fail:name"
    assert "0, 0" not in miss.output
    tok = await tool.run(action="goto", query="Tokyo")
    assert tok.ok
    assert abs(float(tok.data["lat"])) > 1e-3 or abs(float(tok.data["lon"])) > 1e-3
    from arelis.ui.panels.solar_earth import CITY_LOOK_ALT_M, earth_goto_alt_m

    assert earth_goto_alt_m(tok.data["kind"]) == CITY_LOOK_ALT_M
    no_track = await tool.run(action="track", id="nope")
    assert not no_track.ok
    no_ride = await tool.run(action="ride", id="nope")
    assert not no_ride.ok
    left = await tool.run(action="leave")
    assert left.ok
    set_earth(None)


@pytest.mark.asyncio
async def test_solar_craft_is_inspect_not_a_vehicle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from arelis.tools.solar_tool import SolarTool

    monkeypatch.setattr("arelis.tools.solar_tool.world_stage_allowed", lambda: True)
    system = SimpleNamespace(
        enter_inspect=lambda: None,
        lock="",
        nbody=SimpleNamespace(find=lambda *_a, **_k: None),
    )
    monkeypatch.setattr("arelis.tools.solar_tool.get_system", lambda: system)
    tool = SolarTool()
    craft = await tool.run(action="craft")
    inspect = await tool.run(action="inspect")
    assert craft.ok and inspect.ok
    assert craft.data["mode"] == "inspect"
    assert inspect.data["mode"] == "inspect"
    assert "no rideable craft" in craft.output.lower()


