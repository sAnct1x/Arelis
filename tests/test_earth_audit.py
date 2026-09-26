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
    "shodan-banners": "keyed",
    "owned-rtsp": "shipped",
    "contacts": "shipped",
    "unsecured-cams": "out",
    "face-index": "out",
    "car-vin": "out",
}


def test_every_feed_id_and_status_is_pinned() -> None:
    from arelis.earth.feeds import FEEDS

    got = {spec.id: spec.status for spec in FEEDS}
    assert got == FEEDS_PIN
    assert len(got) == 141


def test_later_and_out_are_not_live_adapters() -> None:
    from arelis.earth.feeds import FEEDS
    from arelis.earth.live import _adapter_fns

    later_out = {spec.id for spec in FEEDS if spec.status in {"later", "out"}}
    adapters = set(_adapter_fns())
    assert later_out & adapters == set()
    assert "viirs-boats" in later_out
    assert "sat-ais" in later_out
    assert "viirs-boats" not in adapters


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


def test_empty_opensky_clears_last_city_flights() -> None:
    """Successful [] is not a miss. Restore `if flights:` and this goes red."""
    from arelis.earth.live import _apply_live

    store = EntityStore()
    store.upsert(_plane("icao:old", 40.7, -74.0))
    assert store.in_layer("flights")
    _apply_live(store, {"opensky": []}, {"opensky"}, view=None)
    assert store.in_layer("flights") == ()


def test_opensky_timeout_keeps_sim() -> None:
    from arelis.earth.live import _apply_live

    store = EntityStore()
    store.upsert(_plane("icao:sim", 40.7, -74.0))
    _apply_live(store, {"opensky": None}, {"opensky"}, view=None)
    assert len(store.in_layer("flights")) == 1
    assert store.get("icao:sim") is not None


def test_empty_ais_clears_last_harbor() -> None:
    from arelis.earth.live import _apply_live

    store = EntityStore()
    store.upsert(_ship("mmsi:old", 51.9, 4.5))
    _apply_live(store, {"ais": []}, {"ais"}, view=None)
    assert store.in_layer("vessels") == ()


def test_ais_timeout_keeps_sim() -> None:
    from arelis.earth.live import _apply_live

    store = EntityStore()
    store.upsert(_ship("mmsi:sim", 51.9, 4.5))
    _apply_live(store, {"ais": None}, {"ais"}, view=None)
    assert store.get("mmsi:sim") is not None


def test_empty_cameras_clears_last_city_pins() -> None:
    from arelis.earth.live import _apply_live

    store = EntityStore()
    store.upsert(_cam("cam:old", 51.5, -0.1))
    _apply_live(store, {"cameras": []}, {"cameras"}, view=None)
    assert store.in_layer("cameras") == ()


def test_camera_timeout_keeps_sim() -> None:
    from arelis.earth.live import _apply_live

    store = EntityStore()
    store.upsert(_cam("cam:sim", 51.5, -0.1))
    _apply_live(store, {"cameras": None}, {"cameras"}, view=None)
    assert store.get("cam:sim") is not None


def test_empty_celestrak_does_not_wipe_the_shell() -> None:
    """Orbital miss/empty is not a quiet-ocean replace."""
    from arelis.earth.live import _apply_live

    x, y, z = lla_to_ecef(0.0, 0.0, 400_000.0)
    store = EntityStore()
    store.upsert(
        Entity(
            id="norad:1",
            cls="satellite",
            layer="satellites",
            label="sim sat",
            x=x,
            y=y,
            z=z,
            freshness="simulated",
        )
    )
    _apply_live(store, {"celestrak": []}, {"celestrak"}, view=None)
    assert store.get("norad:1") is not None


def test_trails_note_points_forget() -> None:
    from arelis.earth.trails import forget, note, points

    forget()
    assert points("icao:a") == ()
    note("icao:a", (1.0e6, 2.0e6, 3.0e6))
    note("icao:a", (1.0e6, 2.0e6, 3.0e6))
    assert points("icao:a") == ((1.0e6, 2.0e6, 3.0e6),)
    note("icao:a", (1.0e6 + 100.0, 2.0e6, 3.0e6))
    assert len(points("icao:a")) == 2
    forget("icao:a")
    assert points("icao:a") == ()


def test_leave_forgets_earth_trails() -> None:
    from arelis.earth.trails import forget, note, points

    forget()
    note("icao:hot", (6.4e6, 0.0, 0.0))
    assert points("icao:hot")
    zone = EarthRuntime()
    zone.active = True
    zone.leave()
    assert points("icao:hot") == ()


def test_unlock_forgets_that_trail() -> None:
    from arelis.earth.trails import forget, note, points

    forget()
    zone = EarthRuntime()
    zone.active = True
    plane = _plane("icao:hot", 40.7, -74.0)
    zone.store.upsert(plane)
    zone.track("icao:hot")
    note("icao:hot", (plane.x, plane.y, plane.z))
    note("icao:hot", (plane.x + 100.0, plane.y, plane.z))
    assert points("icao:hot")
    zone.unlock()
    assert points("icao:hot") == ()
    forget()


def test_default_layers_are_sats_and_iss() -> None:
    from arelis.earth.catalog import LAYERS
    from arelis.earth.runtime import default_layers

    on = {spec.id for spec in LAYERS if spec.default_on}
    assert on == {"satellites", "iss"}
    flags = default_layers()
    assert flags["satellites"] is True
    assert flags["iss"] is True
    assert flags["flights"] is False
    assert flags["cameras"] is False


def test_buildings_stays_off_and_off_the_chip_bar() -> None:
    from arelis.ui.earth_overlay import earth_chip_items

    zone = EarthRuntime()
    zone.enter(unix=1.0)
    assert zone.buildings is False
    kinds = {kind for kind, _label in earth_chip_items("city")}
    assert "buildings" not in kinds
    assert "tiles" in kinds
    zone.leave()


def test_celestrak_bands_include_near_and_city() -> None:
    """Pin today's code. Phase 1.4 decides whether docs or lod is the lie."""
    from arelis.earth.lod import ADAPTER_BANDS

    assert ADAPTER_BANDS["celestrak"] == frozenset({"space", "approach", "near", "city"})
    assert ADAPTER_BANDS["opensky"] == frozenset({"approach", "near", "city"})
    assert "space" not in ADAPTER_BANDS["opensky"]
    assert "space" not in ADAPTER_BANDS["cameras"]


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
async def test_earth_tool_search_miss_and_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: True)
    set_earth(EarthRuntime())
    tool = EarthTool()
    await tool.run(action="enter")
    miss = await tool.run(action="search", query="no-such-contact-zz")
    assert miss.ok
    assert "No match" in miss.output
    from arelis.earth.runtime import get_earth

    get_earth().live = True
    live = await tool.run(action="live", on=False)
    assert live.ok
    assert live.data["live"] is False
    cov = await tool.run(action="coverage")
    assert cov.ok
    set_earth(None)


def test_earth_dump_frame_is_ecef() -> None:
    from arelis.earth import dump as earth_dump
    from arelis.physics import export as solar_export

    assert earth_dump.FRAME == "ECEF"
    assert solar_export.FRAME == "ECLIPJ2000"


def test_gibs_blue_marble_urls_match() -> None:
    from arelis.earth.globe_stack import GIBS_XYZ
    from arelis.earth.tiles import GIBS_BLUE

    assert GIBS_XYZ == GIBS_BLUE


def test_dump_state_drops_stream_urls(tmp_path) -> None:
    from arelis.earth.dump import dump_state

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    x, y, z = lla_to_ecef(51.5, -0.1, 0.0)
    earth.store.upsert(
        Entity(
            id="cam:secret",
            cls="camera",
            layer="cameras",
            label="owned",
            x=x,
            y=y,
            z=z,
            freshness="live",
            meta={"url": "rtsp://secret.example/live", "stream": "rtsp://secret.example/live"},
        )
    )
    folder = dump_state(earth, root=tmp_path, stamp="rtsp", trigger="dump")
    blob = (folder / "state.jsonl").read_text(encoding="utf-8")
    manifest = (folder / "manifest.json").read_text(encoding="utf-8")
    assert "rtsp://" not in blob
    assert "secret.example" not in blob
    assert "rtsp://" not in manifest
    earth.leave()


def test_spoken_leave_earth_uses_plate_teardown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from arelis.earth.runtime import EarthRuntime, set_earth
    from arelis.spatial.verbs import PhysicsAct
    from arelis.ui.world_host import apply_physics_act

    hits: list[str] = []
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)

    class Solar:
        def _leave_earth_zone(self) -> None:
            hits.append("teardown")
            earth.leave()

    class Notes:
        def append(self, *args: object, **kwargs: object) -> None:
            hits.append("note")

    window = SimpleNamespace(
        thinking=Notes(),
        world_window=SimpleNamespace(solar=Solar()),
    )
    monkeypatch.setattr("arelis.ui.world_host.touch_solar", lambda *_a, **_k: hits.append("touch"))
    apply_physics_act(window, PhysicsAct(verb="leave_earth"))
    assert hits[0] == "teardown"
    assert "touch" in hits
    assert earth.active is False
    set_earth(None)


def test_space_does_not_fetch_ground_catalogs() -> None:
    from arelis.earth.lod import adapter_allowed
    from arelis.earth.runtime import default_layers

    layers = default_layers()
    assert adapter_allowed("celestrak", "space", layers) is True
    assert adapter_allowed("opensky", "space", layers) is False
    assert adapter_allowed("cameras", "space", layers) is False
    assert adapter_allowed("traffic", "space", layers) is False
    assert adapter_allowed("ais", "space", layers) is False


def test_earth_tool_enter_turns_live_on() -> None:
    from arelis.tools.earth_tool import EarthTool

    text = EarthTool.description
    assert "enter turns Live on" in text
    assert "snapshots then coasts" not in text
    assert "Live keeps pulling" not in text


def test_opensky_fail_is_none_empty_states_is_quiet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import arelis.earth.opensky as opensky

    monkeypatch.setattr(opensky, "_credits_ok", lambda: False)
    assert opensky.fetch_opensky() is None
    monkeypatch.setattr(opensky, "_credits_ok", lambda: True)
    monkeypatch.setattr(opensky, "_states", lambda *_a, **_k: None)
    assert opensky.fetch_opensky() is None
    monkeypatch.setattr(opensky, "_states", lambda *_a, **_k: {"time": 1, "states": []})
    assert opensky.fetch_opensky() == []


def test_traffic_fetch_module_pins_wzdx_and_rejects_evil_hosts() -> None:
    from arelis.earth import traffic_fetch

    hosts = {host for host, _url, _name in traffic_fetch._WZDX}
    assert "udottraffic.utah.gov" in hosts
    assert traffic_fetch._get_json("https://evil.example/x", "api.tfl.gov.uk") is None
    pins = traffic_fetch.entities_from_wzdx(
        {
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [-111.9, 40.8]},
                    "properties": {"core_details": {"event_type": "work-zone", "name": "I-15"}},
                }
            ]
        },
        prefix="ut",
        source="Utah WZDx",
    )
    assert pins
    assert all(e.layer == "traffic" for e in pins)
    assert all(e.cls == "traffic" for e in pins)


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


def test_ride_sets_track_unlock_clears_both() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    x, y, z = lla_to_ecef(0.0, 0.0, 400_000.0)
    earth.store.upsert(
        Entity(
            id="norad:25544",
            cls="station",
            layer="iss",
            label="ISS",
            x=x,
            y=y,
            z=z,
            freshness="live",
        )
    )
    hit = earth.ride("norad:25544")
    assert hit is not None
    assert earth.ride_id == "norad:25544"
    assert earth.track_id == "norad:25544"
    earth.unlock()
    assert earth.ride_id == ""
    assert earth.track_id == ""
    earth.leave()


def test_view_receipt_drops_stream_urls() -> None:
    from arelis.earth.dump import view_receipt

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth.store.upsert(
        Entity(
            id="cam:secret",
            cls="camera",
            layer="cameras",
            label="owned",
            x=1.0,
            y=2.0,
            z=3.0,
            freshness="live",
            meta={"url": "rtsp://secret.example/live"},
        )
    )
    blob = str(view_receipt(earth))
    assert "rtsp://" not in blob
    assert "secret.example" not in blob
    earth.leave()


def test_find_miss_is_loud_not_null_island() -> None:
    from types import SimpleNamespace

    from arelis.earth.runtime import EarthRuntime, set_earth
    from arelis.ui.earth_find import apply_goto

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SimpleNamespace(
        _earth_find_on=True,
        _earth_find_q="zzzz-not-a-city",
        _earth_find_hits=[],
        _earth_find_ix=0,
        _earth_find_box=None,
        _earth_say=None,
        update=lambda: None,
    )
    assert apply_goto(panel) is False
    title, line = panel._earth_say
    assert "zzzz-not-a-city" in title
    assert "0, 0" in line
    earth.leave()
    set_earth(None)


def test_nominatim_null_island_is_dropped() -> None:
    from arelis.earth.gazetteer import GotoHit, resolve_place
    from arelis.earth.geocode import clear_cache, remember_hits, search_address

    clear_cache()
    remember_hits("Null Island", [GotoHit("address", "Null Island", 0.0, 0.0)])
    assert search_address("Null Island", force=True) == []
    assert resolve_place("zzzz-not-a-place-on-earth") is None
    clear_cache()


def test_chip_off_blocks_that_adapter() -> None:
    from arelis.earth.lod import adapter_allowed
    from arelis.earth.runtime import default_layers

    layers = default_layers()
    layers["cameras"] = False
    layers["flights"] = False
    assert adapter_allowed("cameras", "city", layers) is False
    assert adapter_allowed("opensky", "approach", layers) is False
    layers["flights"] = True
    assert adapter_allowed("opensky", "approach", layers) is True


def test_look_still_urls_are_official() -> None:
    from arelis.earth import look

    for url in look._STILL_PIN_URLS:
        assert look.official_url_ok(url), url


def test_camera_and_look_hosts_agree() -> None:
    """3.6: a host in one list and not the others is a look-from hole or dead pin."""
    import ast
    import re
    from pathlib import Path
    from urllib.parse import urlparse

    from arelis.earth import cameras_fetch, look, traffic_fetch

    hostname = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")

    def named_in(mod) -> set[str]:
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        found: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            val = node.value.strip()
            if val.startswith("https://"):
                host = urlparse(val).hostname
                if host:
                    found.add(host.lower())
            elif hostname.match(val.lower()):
                found.add(val.lower())
        return found

    fetch_hosts = named_in(cameras_fetch) | named_in(traffic_fetch)
    still_hosts = {
        (urlparse(url).hostname or "").lower()
        for url in look._STILL_PIN_URLS
        if urlparse(url).hostname
    }
    named = fetch_hosts | still_hosts
    for pin in look._OFFICIAL_HOSTS:
        assert look._host_in(pin, named) or any(
            pin == h or h.endswith("." + pin) or pin.endswith("." + h) for h in named
        ), pin
    for host in still_hosts:
        assert look._host_in(host, look._OFFICIAL_HOSTS), host


def test_live_chip_layout_fits_off_label(qt_app) -> None:
    from PySide6.QtGui import QFont, QFontMetrics

    from arelis.earth.copy import live_chip_label
    from arelis.ui.earth_overlay import _chip_width

    fm = QFontMetrics(QFont("Segoe UI", 11))
    w = _chip_width(fm, "live", "x")
    need = fm.horizontalAdvance(live_chip_label(on=False)) + 20
    assert w >= need


def test_subsolar_lla_is_noon_at_greenwich() -> None:
    from datetime import UTC, datetime

    from arelis.earth.frames import subsolar_lla

    noon = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC).timestamp()
    lat, lon = subsolar_lla(unix=noon)
    assert abs(lon) < 1.0
    assert abs(lat) < 8.0
    midnight = datetime(2026, 9, 19, 0, 0, 0, tzinfo=UTC).timestamp()
    _lat, mlon = subsolar_lla(unix=midnight)
    assert abs(abs(mlon) - 180.0) < 1.0
    from arelis.earth.frames import subsolar_lla
    from arelis.ui.panels.solar_earth import SPACE_ENTER_ALT_M, earth_enter_lla

    lat, lon, alt = earth_enter_lla(None)
    assert alt == SPACE_ENTER_ALT_M
    assert abs(lat) <= 90.0
    assert abs(lon) <= 180.0
    slat, slon = subsolar_lla()
    assert abs(lat - slat) < 0.2
    assert abs(((lon - slon + 180) % 360) - 180) < 0.2


def test_enter_placeholder_look_is_sunlit_not_gulf_of_guinea() -> None:
    from arelis.earth.frames import subsolar_lla
    from arelis.earth.lod import EarthView
    from arelis.earth.runtime import EarthRuntime
    from arelis.ui.panels.solar_earth import earth_enter_lla

    earth = EarthRuntime()
    earth.last_view = EarthView("space", lat=20.0, lon=0.0)
    lat, lon, _alt = earth_enter_lla(earth)
    slat, slon = subsolar_lla()
    assert abs(lat - slat) < 0.2
    assert abs(((lon - slon + 180) % 360) - 180) < 0.2
    earth.last_view = EarthView("space")
    lat, lon, _alt = earth_enter_lla(earth)
    assert abs(lat - slat) < 0.2


def test_cesium_reveal_waits_for_tiles_not_a_timer() -> None:
    from pathlib import Path

    earth = (
        Path(__file__).resolve().parents[1] / "arelis" / "ui" / "panels" / "solar_earth.py"
    ).read_text(encoding="utf-8")
    js = (
        Path(__file__).resolve().parents[1] / "arelis" / "ui" / "earth_globe" / "bridge.js"
    ).read_text(encoding="utf-8")
    assert "singleShot(900" not in earth
    assert "Chromium actually fetches GIBS" in earth
    assert "tileLoadProgressEvent" in js
    assert "function watchGlobeTiles" in js
    assert "function enterPose" in js
    assert "function dressOsmLayer" in js
