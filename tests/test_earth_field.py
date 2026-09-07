"""Reality field walk: enter, inspect, coast, ocean, city, look-from.

The live eyes live in scripts/walk_earth_field.py. This file is the
contract that walk is allowed to assume — chips, bands, cards, look,
and which catalogs can paint where. Pytest stays simulated.
"""

from __future__ import annotations

import json

import pytest

from arelis.earth.copy import inspect_kind_line
from arelis.earth.entity import LAYER_IDS
from arelis.earth.frames import ecef_to_geodetic, lla_to_ecef
from arelis.earth.lod import EarthView, look_bbox, paint_layers
from arelis.earth.runtime import EarthRuntime, set_earth
from arelis.earth.simulate import CAMERAS, PORTS, RADIO
from arelis.ui.earth_overlay import earth_chip_items, inspect_card_text


def _view(band: str, lat: float, lon: float, alt_m: float) -> EarthView:
    return EarthView(
        band,
        alt_m=alt_m,
        lat=lat,
        lon=lon,
        bbox=look_bbox(lat, lon, band),
    )


def _on(earth: EarthRuntime, *layers: str) -> None:
    for key in earth.layers:
        earth.layers[key] = key in layers


def test_field_enter_shows_iss_and_the_card() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth.note_view(_view("space", 0.0, 0.0, 3_000_000.0))
    iss = earth.get("norad:25544")
    assert iss is not None
    assert iss.layer == "iss"
    assert earth.layers["iss"] is True
    assert earth.layers["cameras"] is False
    vis = {e.layer for e in earth.visible()}
    assert vis <= {"iss", "satellites"}
    assert "iss" in vis
    text = inspect_card_text(iss)
    assert "ISS" in text
    assert "click to ride" in text
    assert "Esc to leave it" in text
    assert "TEME" not in text


def test_field_iss_coasts_on_tick() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    first = earth.get("norad:25544")
    assert first is not None
    x0, y0, z0 = first.x, first.y, first.z
    earth.tick(unix=90.0)
    later = earth.get("norad:25544")
    assert later is not None
    drift = (
        (later.x - x0) ** 2 + (later.y - y0) ** 2 + (later.z - z0) ** 2
    ) ** 0.5
    assert drift > 1_000.0
    lat, _lon, alt = ecef_to_geodetic(later.x, later.y, later.z)
    assert 300_000.0 < alt < 500_000.0
    assert abs(lat) < 55.0


def test_field_iss_click_rides(qt_app) -> None:
    from arelis.ui.panels.solar import SolarPanel

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    iss = earth.get("norad:25544")
    assert iss is not None
    panel = SolarPanel()
    panel._on_globe_pick(iss.id)
    assert earth.ride_id == iss.id
    panel.hide()
    set_earth(None)


def test_field_ocean_opens_boats_not_cameras() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    lat, lon = PORTS[1][1], PORTS[1][2]  # Singapore strait
    earth.note_view(_view("near", lat, lon, 12_000.0))
    _on(earth, "iss", "satellites", "vessels", "cameras")
    vis = list(earth.visible())
    layers = {e.layer for e in vis}
    assert "vessels" in layers
    assert "cameras" not in layers
    assert "cameras" not in paint_layers("near")
    chips = dict(earth_chip_items("near"))
    assert "vessels" in chips
    assert "cameras" not in chips
    assert any("ship" in inspect_kind_line(e.layer, e.freshness) for e in vis)


def test_field_city_opens_cameras_radio_weather() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth.note_view(_view("city", 51.508, -0.128, 2_500.0))
    _on(earth, "cameras", "radio", "weather", "traffic")
    vis = list(earth.visible())
    have = {e.layer for e in vis}
    assert "cameras" in have
    assert "radio" in have
    assert "weather" in have
    labels = {e.label for e in vis if e.layer == "cameras"}
    assert any("Trafalgar" in name or "London" in name for name in labels)
    radio = {e.label for e in vis if e.layer == "radio"}
    assert any("BBC" in name for name in radio)
    chips = dict(earth_chip_items("city"))
    for kind in ("cameras", "radio", "weather", "traffic", "fires", "sites"):
        assert kind in chips


def test_field_known_fire_belt_paints_hotspots() -> None:
    from arelis.earth.entity import Entity

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    pos = lla_to_ecef(38.5, -122.5, 0.0)
    earth.store.upsert(
        Entity(
            id="field:napa-fire",
            cls="fire",
            layer="fires",
            label="Napa hotspot",
            x=pos[0],
            y=pos[1],
            z=pos[2],
            freshness="reconstructed",
            source="FIRMS",
            meta={"lat": 38.5, "lon": -122.5},
        )
    )
    earth.note_view(_view("city", 38.5, -122.5, 20_000.0))
    _on(earth, "fires")
    fires = [e for e in earth.visible() if e.layer == "fires"]
    assert any(e.id == "field:napa-fire" for e in fires)
    belt = [
        e
        for e in earth.store.all()
        if e.layer == "fires"
        and 34.0 <= float((e.meta or {}).get("lat") or 0) <= 42.0
        and -127.0 <= float((e.meta or {}).get("lon") or 0) <= -117.0
    ]
    assert belt


def test_field_military_and_drones_have_their_own_marks() -> None:
    from arelis.earth.entity import Entity
    from arelis.ui.earth_marks import HEADING_KINDS, mark_digest

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    for layer, eid, alt in (
        ("military", "field:mil", 8_000.0),
        ("drones", "field:uav", 400.0),
    ):
        pos = lla_to_ecef(40.7, -74.0, alt)
        earth.store.upsert(
            Entity(
                id=eid,
                cls="aircraft",
                layer=layer,
                label=layer,
                x=pos[0],
                y=pos[1],
                z=pos[2],
                freshness="delayed",
                source="ADS-B",
                meta={"lat": 40.7, "lon": -74.0, "track_deg": 90.0},
            )
        )
    earth.note_view(_view("near", 40.7, -74.0, 30_000.0))
    _on(earth, "flights", "military", "drones")
    have = {e.layer for e in earth.visible()}
    assert "flights" in have
    assert "military" in have
    assert "drones" in have
    assert mark_digest("military", band="city") != mark_digest("flights", band="city")
    assert mark_digest("drones", band="city") != mark_digest("flights", band="city")
    assert "military" in HEADING_KINDS
    assert "drones" in HEADING_KINDS
    chips = dict(earth_chip_items("near"))
    assert "military" in chips
    assert "drones" in chips


def test_field_every_layer_has_a_mark() -> None:
    from arelis.ui.earth_marks import mark_digest, mark_image

    seen: set[str] = set()
    for kind in LAYER_IDS:
        digest = mark_digest(kind, band="city")
        assert digest not in seen
        seen.add(digest)
        img = mark_image(kind, band="city")
        assert not img.isNull()


def test_field_marks_are_filled_not_outlines() -> None:
    from arelis.ui.earth_marks import FILL_ALPHA, mark_image

    img = mark_image("flights", band="city")
    wash = 0
    for y in range(img.height()):
        for x in range(img.width()):
            alpha = img.pixelColor(x, y).alpha()
            if FILL_ALPHA - 24 <= alpha <= FILL_ALPHA + 8:
                wash += 1
    assert wash > 20


def test_field_radio_and_camera_tiles_stay_off_the_globe() -> None:
    from arelis.earth.entity import Entity
    from arelis.ui.earth_dock import camera_facts, radio_rows

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth.note_view(_view("city", 51.508, -0.128, 2_500.0))
    _on(earth, "radio", "cameras")
    rows = radio_rows(earth)
    assert any("BBC" in (ent.label or "") for ent in rows)
    cam = Entity(
        id="tfl:tile",
        cls="camera",
        layer="cameras",
        label="Trafalgar",
        x=0.0,
        y=0.0,
        z=0.0,
        source="TfL JamCam",
        freshness="reconstructed",
        meta={
            "lat": 51.508,
            "lon": -0.128,
            "url": "https://secret.example/stream",
            "ip": "203.0.113.9",
            "operator": "TfL",
        },
    )
    text = camera_facts(cam)
    assert "Trafalgar" in text
    assert "TfL" in text
    assert "51.508" in text
    assert "secret.example" not in text
    assert "203.0.113" not in text
    assert "stream" not in text


def test_field_camera_click_opens_publisher_still() -> None:
    from arelis.earth.look import forget, offer_official, resolve

    forget()
    still = "https://jamcams.tfl.gov.uk/00001.01251.jpg"
    handle = offer_official("tfl:trafalgar", still)
    assert handle is not None
    assert handle.media == "still"
    assert handle.kind == "official"
    assert resolve("tfl:trafalgar") is handle
    assert still not in repr(handle)
    forget()


def test_field_camera_click_starts_look_on_the_plate(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.look import forget, offer_official
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.look_session import LookSession
    from arelis.ui.panels.solar import SolarPanel

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    forget()
    still = "https://jamcams.tfl.gov.uk/00001.01251.jpg"
    offer_official("tfl:trafalgar", still)
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    pos = lla_to_ecef(51.508, -0.128, 12.0)
    cam = Entity(
        id="tfl:trafalgar",
        cls="camera",
        layer="cameras",
        label="TfL Trafalgar Square",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        freshness="reconstructed",
        source="TfL JamCam",
        meta={"lat": 51.508, "lon": -0.128},
    )
    earth.store.upsert(cam)
    earth.layers["cameras"] = True
    set_earth(earth)
    started: list[object] = []
    monkeypatch.setattr(
        LookSession, "start", lambda self, handle: started.append(handle)
    )
    panel = SolarPanel()
    panel.resize(640, 480)
    panel._select_earth_entity(cam, ride=False)
    assert panel._earth_id == "tfl:trafalgar"
    assert started
    assert getattr(started[0], "media", "") == "still"
    panel.hide()
    set_system(None)
    set_earth(None)
    forget()


def test_field_catalog_pins_are_where_the_walk_looks() -> None:
    assert CAMERAS[0][0] == "tfl:trafalgar"
    assert abs(CAMERAS[0][1] - 51.508) < 0.01
    assert any(row[0] == "Singapore" for row in PORTS)
    assert any(row[0] == "BBC Radio 4" for row in RADIO)
    space = dict(earth_chip_items("space"))
    assert set(space) >= {"band", "live", "iss", "satellites"}
    city = dict(earth_chip_items("city"))
    for kind in LAYER_IDS:
        if kind == "people":
            continue
        assert kind in city


def test_field_say_is_on_the_glass() -> None:
    from pathlib import Path

    chrome = Path("arelis/ui/earth_chrome.py").read_text(encoding="utf-8")
    hud = Path("arelis/ui/panels/solar_hud.py").read_text(encoding="utf-8")
    paint = Path("arelis/ui/panels/solar_paint.py").read_text(encoding="utf-8")
    assert "def paint_earth_say" in chrome
    assert "def set_earth_say" in chrome
    assert "paint_earth_say" in hud
    assert "_earth_say_box" in paint


def test_field_click_sat_does_not_rebuild_the_globe() -> None:
    from pathlib import Path

    body = Path("arelis/ui/panels/solar_earth.py").read_text(encoding="utf-8")
    chunk = body.split("def _select_earth_entity", 1)[1].split("\n    def ", 1)[0]
    assert "push_entities" in chunk
    assert "arm_ride" in chunk
    assert "_fly_ride_sit" in chunk
    assert chunk.index("_fly_ride_sit") < chunk.index("push_entities")
    assert "force=True" not in chunk
    fly = body.split("def _fly_ride_sit", 1)[1].split("\n    def ", 1)[0]
    assert "_go_earth_lla" in fly
    go = body.split("def _go_earth_lla", 1)[1].split("\n    def ", 1)[0]
    assert "arm_ride" in go
    walk = Path("scripts/walk_earth_field.py").read_text(encoding="utf-8")
    coast = walk.split("ISS COAST", 1)[1].split("_banner", 1)[0]
    assert "solar._tick()" in coast
    follow = body.split("def _globe_follow_ride", 1)[1].split("\n    def ", 1)[0]
    assert "keep_ride=True" in follow
    assert "sit = 80_000" in follow
    assert "return" not in follow.split('== "iss":', 1)[1].split("sit = 80_000", 1)[0]
    assert inspect_kind_line("satellites", "interpolated") == (
        "satellite · interpolated"
    )
    from arelis.earth.entity import Entity

    dummy = Entity(
        id="norad:1",
        cls="satellite",
        layer="satellites",
        label="STARLINK-1",
        x=0.0,
        y=0.0,
        z=0.0,
        freshness="interpolated",
        source="CelesTrak GP",
        cite="TEME classified",
        meta={"norad": 1, "group": "starlink"},
    )
    text = inspect_card_text(dummy)
    assert "STARLINK-1" in text
    assert "TEME" not in text


def test_field_look_shift_drops_city_catalog_ttl() -> None:
    from arelis.earth.runtime import drop_look_box_fetches

    last = {"cameras": 1.0, "celestrak": 1.0, "opensky": 1.0, "firms": 1.0}
    drop_look_box_fetches(last)
    assert "cameras" not in last
    assert "opensky" not in last
    assert "firms" not in last
    assert last["celestrak"] == 1.0


def test_field_escape_hops_off_the_station(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import SolarPanel

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setattr(
        "arelis.earth.runtime.EarthRuntime._merge_live", lambda self: None
    )
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    iss = earth.get("norad:25544")
    assert iss is not None
    released: list[str] = []

    class Host:
        failed = False

        def isVisible(self) -> bool:
            return False

        def release_camera(self) -> None:
            released.append("release")

    panel = SolarPanel()
    panel.resize(640, 480)
    panel._globe_host = Host()
    panel._select_earth_entity(iss, ride=True)
    assert earth.ride_id == "norad:25544"
    assert panel._hop_off_earth_contact() is True
    assert earth.ride_id == ""
    assert earth.track_id == ""
    assert panel._earth_id is None
    assert released == ["release"]
    assert panel._hop_off_earth_contact() is False
    panel._on_globe_ground(json.dumps({"sky": True}))
    panel.hide()
    set_system(None)
    set_earth(None)


def test_field_ride_arms_js_follow(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import SolarPanel

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    monkeypatch.setattr(
        "arelis.earth.runtime.EarthRuntime._merge_live", lambda self: None
    )
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    iss = earth.get("norad:25544")
    assert iss is not None
    armed: list[str] = []
    released: list[str] = []
    flies: list[tuple[float, float, float]] = []

    class Host:
        failed = False

        def isVisible(self) -> bool:
            return True

        def push_entities(self, rows) -> None:
            return None

        def arm_ride(self, entity_id: str) -> None:
            armed.append(str(entity_id or ""))

        def fly_to(self, lat, lon, alt_m) -> None:
            flies.append((float(lat), float(lon), float(alt_m)))

        def push_camera(self, lat, lon, alt_m, heading=None, pitch=None, **_kw) -> None:
            return None

        def release_camera(self) -> None:
            released.append("release")

    panel = SolarPanel()
    panel.resize(640, 480)
    panel._globe_host = Host()
    panel._select_earth_entity(iss, ride=True)
    assert earth.ride_id == "norad:25544"
    assert armed[-1] == "norad:25544"
    assert "" in armed
    assert flies
    assert 80_000.0 <= flies[0][2] <= 900_000.0
    assert released == ["release"]
    panel._select_earth_entity(iss, ride=False)
    assert earth.ride_id == ""
    assert armed[-1] == ""
    panel.hide()
    set_system(None)
    set_earth(None)


def test_field_find_does_not_seed_dest_as_eye(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    from arelis.earth.gazetteer import resolve_place
    from arelis.ui.panels.solar import SolarPanel

    monkeypatch.setattr(
        "arelis.earth.runtime.EarthRuntime._merge_live", lambda self: None
    )
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    hit = resolve_place("Tokyo")
    assert hit is not None

    class Host:
        failed = False

        def isVisible(self) -> bool:
            return True

        def fly_to(self, lat: float, lon: float, alt_m: float) -> None:
            return None

        def release_camera(self) -> None:
            return None

    panel = SolarPanel()
    panel.resize(960, 720)
    panel._globe_host = Host()
    panel._earth_agl_m = 20_000_000.0
    panel._earth_cam = None
    panel._select_earth_place(hit.as_place())
    assert panel._earth_agl_m == 20_000_000.0
    assert panel._earth_cam is None
    assert panel._earth_id is None
    panel.hide()
    set_earth(None)


def test_field_city_orbit_marks_do_not_glue_iss() -> None:
    from arelis.ui.earth_globe_host import pick_orbit_marks

    rows = [
        {"id": "plane:1", "layer": "flights"},
        {"id": "norad:25544", "layer": "iss", "hot": False},
        {"id": "sat:1", "layer": "satellites", "hot": False},
    ]
    picked = pick_orbit_marks(rows, keep_ids=set())
    assert not any(row["id"] == "norad:25544" for row in picked)
    assert not any(row["layer"] == "satellites" for row in picked)
    hot = pick_orbit_marks(rows, keep_ids={"norad:25544"})
    assert any(row["id"] == "norad:25544" for row in hot)
    assert not any(row["layer"] == "satellites" for row in hot)


def test_camera_tile_reserves_the_full_still_well() -> None:
    from pathlib import Path

    from arelis.ui.earth_dock import _LIVE_H, _PEEK_H, _frame_well_h

    class _Panel:
        def height(self) -> int:
            return 1031

    panel = _Panel()
    assert _frame_well_h(panel, "peek") == _PEEK_H
    assert _frame_well_h(panel, "live") == _LIVE_H
    dock = Path("arelis/ui/earth_dock.py").read_text(encoding="utf-8")
    assert "def _draw_look_still" in dock
    assert "drawImage(target, frame)" not in dock
    host = Path("arelis/ui/panels/solar_earth.py").read_text(encoding="utf-8")
    look = host.split("def _on_look_frame", 1)[1].split("\n    def ", 1)[0]
    assert "hud.update" in look
