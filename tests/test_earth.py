"""Earth zone: enter, ISS, simulated world, dump, tool."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from arelis.earth.dump import dump_state
from arelis.earth.frames import ecef_to_ecliptic, ecef_to_lla, lla_to_ecef
from arelis.earth.runtime import EarthRuntime, get_earth, set_earth
from arelis.earth.simulate import CAMERAS, ISS_NORAD, ISS_PERIOD_S, iss_entity, populate
from arelis.earth.store import EntityStore
from arelis.spatial.verbs import classify_physics_act
from arelis.tools.base import ToolRegistry
from arelis.tools.earth_tool import EarthTool


@pytest.fixture(autouse=True)
def _isolate_earth(monkeypatch: pytest.MonkeyPatch) -> None:
    set_earth(None)
    # Enter must not read the developer's contacts.yaml / secrets cameras.
    monkeypatch.setattr(
        "arelis.earth.runtime.EarthRuntime._merge_local",
        lambda self: None,
    )
    yield
    set_earth(None)


_LIVE_FETCHERS = (
    "fetch_usgs",
    "fetch_opensky",
    "fetch_adsb_mil",
    "fetch_ais",
    "fetch_celestrak",
    "fetch_radio",
    "fetch_cameras",
    "fetch_weather",
    "fetch_firms",
    "fetch_launches",
    "fetch_aprs",
    "fetch_shodan",
    "fetch_traffic",
    "fetch_radar",
    "fetch_gfw",
    "fetch_eonet",
    "fetch_nws",
    "fetch_airports",
    "fetch_spacetrack",
    "fetch_tip",
    "fetch_emsc",
    "fetch_swpc",
    "fetch_satnogs",
    "fetch_metar",
    "fetch_waqi",
    "fetch_geonet",
    "fetch_ndbc",
    "fetch_volcanoes",
    "fetch_gdacs",
    "fetch_tides",
    "fetch_argo",
)


def _mute_live(monkeypatch: pytest.MonkeyPatch, **keep: object) -> None:
    """Stub every live adapter. A new fetch in merge_live must land here."""

    def _none() -> None:
        return None

    for name in _LIVE_FETCHERS:
        monkeypatch.setattr(f"arelis.earth.live.{name}", keep.get(name, _none))


def test_lla_roundtrip_is_near_the_pin() -> None:
    x, y, z = lla_to_ecef(51.5, -0.12, 0.0)
    lat, lon, alt = ecef_to_lla(x, y, z)
    assert lat == pytest.approx(51.5, abs=0.4)
    assert lon == pytest.approx(-0.12, abs=0.4)
    assert abs(alt) < 30_000.0


def test_iss_returns_after_one_period() -> None:
    a = iss_entity(1_000.0)
    b = iss_entity(1_000.0 + ISS_PERIOD_S)
    assert a.id == f"norad:{ISS_NORAD}"
    assert a.freshness == "simulated"
    err = ((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2) ** 0.5
    assert err < 2_000.0


def test_populate_fills_every_layer() -> None:
    store = EntityStore()
    populate(store, 1_700_000_000.0)
    counts = store.counts()
    assert counts["iss"] == 1
    assert counts["flights"] > 100
    assert counts["vessels"] > 50
    assert counts["satellites"] > 50
    assert counts["quakes"] > 10
    assert counts["cameras"] >= 4
    assert store.get("norad:25544") is not None
    static = {"cameras", "sites"}
    for e in store.all():
        if e.layer in static:
            assert e.freshness == "reconstructed", e.id
        else:
            assert e.freshness == "simulated", e.id


def test_enter_leave_and_dump(tmp_path: Path) -> None:
    earth = EarthRuntime()
    earth.enter(unix=1_700_000_000.0)
    assert earth.active
    assert len(earth.store) > 200
    folder = dump_state(earth, root=tmp_path / "earth", stamp="test")
    assert (folder / "manifest.json").is_file()
    assert (folder / "state.jsonl").is_file()
    text = (folder / "state.jsonl").read_text(encoding="utf-8")
    assert "simulated" in text
    assert "norad:25544" in text
    assert "viewshed" in text
    assert "pose prior" in text
    assert "viewshed_ecef" not in text
    earth.leave()
    assert not earth.active
    assert len(earth.store) == 0


def test_layer_toggle_hides() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    n = len(earth.visible())
    assert earth.set_layer("flights", False) is False
    assert len(earth.visible()) < n
    assert earth.set_layer("nope") is None


def test_search_finds_iss() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    hits = earth.search("ISS")
    assert any(e.id == "norad:25544" for e in hits)


def test_ride_iss() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    hit = earth.ride("norad:25544")
    assert hit is not None
    assert earth.ride_id == "norad:25544"


@pytest.mark.asyncio
async def test_earth_tool_enter_status_leave(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: True)
    monkeypatch.setattr("arelis.earth.dump.dumps_root", lambda: tmp_path / "earth")
    set_earth(EarthRuntime())
    tool = EarthTool()
    entered = await tool.run(action="enter")
    assert entered.ok, entered.output
    assert entered.data["active"] is True
    status = await tool.run(action="status")
    assert status.ok
    assert "Earth" in status.output
    left = await tool.run(action="leave")
    assert left.ok
    assert left.data["active"] is False


@pytest.mark.asyncio
async def test_earth_tool_unknown_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: True)
    result = await EarthTool().run(action="explode")
    assert not result.ok


def test_earth_dump_does_not_need_allow() -> None:
    registry = ToolRegistry()
    registry.register(EarthTool())
    assert not registry.needs_confirm("earth", {"action": "dump"})
    assert not registry.needs_confirm("earth", {"action": "enter"})
    assert not registry.needs_confirm("earth", {"action": "live", "on": True})


def test_enter_earth_is_a_closed_verb() -> None:
    assert classify_physics_act("enter Earth").verb == "enter_earth"
    assert classify_physics_act("leave Earth").verb == "leave_earth"
    assert classify_physics_act("ride the ISS").verb == "ride_iss"
    assert classify_physics_act("take me to Earth", names=("Earth",)).verb == "travel"


def test_ecef_to_ecliptic_moves_with_earth_center() -> None:
    ecef = lla_to_ecef(0.0, 0.0, 0.0)
    a = ecef_to_ecliptic((0.0, 0.0, 0.0), ecef, 2_451_545.0)
    b = ecef_to_ecliptic((1.0e9, 0.0, 0.0), ecef, 2_451_545.0)
    assert b[0] - a[0] == pytest.approx(1.0e9, rel=1e-9)


def test_earth_cam_follows_earth_center() -> None:
    from arelis.earth.frames import EarthCam, apply_earth_cam
    from arelis.physics.camera import FlyCamera

    cam = FlyCamera()
    jd = 2_451_545.0
    earth_a = (1.5e11, 0.0, 0.0)
    earth_b = (0.0, 1.5e11, 0.0)
    pose = EarthCam(
        eye=lla_to_ecef(0.0, 0.0, 50_000_000.0),
        look=(0.0, 0.0, 0.0),
        up=(0.0, 0.0, 1.0),
    )
    apply_earth_cam(cam, earth_a, jd, pose)
    off_a = (cam.x - earth_a[0], cam.y - earth_a[1], cam.z - earth_a[2])
    apply_earth_cam(cam, earth_b, jd, pose)
    off_b = (cam.x - earth_b[0], cam.y - earth_b[1], cam.z - earth_b[2])
    assert off_a[0] == pytest.approx(off_b[0], rel=1e-9, abs=1.0)
    assert off_a[1] == pytest.approx(off_b[1], rel=1e-9, abs=1.0)
    assert off_a[2] == pytest.approx(off_b[2], rel=1e-9, abs=1.0)


def test_ride_pose_sits_on_the_contact() -> None:
    from types import SimpleNamespace

    from arelis.earth.entity import Entity
    from arelis.ui.earth_overlay import entity_world, ride_pose

    ecef = lla_to_ecef(0.0, 0.0, 400_000.0)
    entity = Entity(
        id="ride:test",
        cls="station",
        layer="iss",
        label="ISS",
        x=ecef[0],
        y=ecef[1],
        z=ecef[2],
        vx=0.0,
        vy=7_600.0,
        vz=0.0,
    )
    earth = SimpleNamespace(x=0.0, y=0.0, z=0.0)
    system = SimpleNamespace(
        nbody=SimpleNamespace(find=lambda name: earth if name == "Earth" else None),
        epoch_jd=2_451_545.0,
        t=0.0,
    )
    pose = ride_pose(system, entity)
    assert pose is not None
    eye, look, up = pose
    world = entity_world(system, entity)
    assert world is not None
    sit = math.dist(eye, world)
    assert 40.0 <= sit <= 250.0
    un = math.sqrt(up[0] ** 2 + up[1] ** 2 + up[2] ** 2)
    assert un == pytest.approx(1.0, abs=1e-6)
    ahead = math.dist(look, world)
    to_earth = math.dist(look, (earth.x, earth.y, earth.z))
    assert ahead < to_earth
    still = Entity(
        id="ride:still",
        cls="camera",
        layer="cameras",
        label="cam",
        x=ecef[0],
        y=ecef[1],
        z=ecef[2],
    )
    still_pose = ride_pose(system, still)
    assert still_pose is not None
    assert still_pose[1] == (earth.x, earth.y, earth.z)


def test_earth_cam_roundtrip_keeps_the_eye() -> None:
    from arelis.earth.frames import apply_earth_cam, capture_earth_cam
    from arelis.physics.camera import FlyCamera

    cam = FlyCamera()
    earth = (1.4e11, 2.0e10, -1.0e9)
    cam.x, cam.y, cam.z = earth[0] + 8.0e7, earth[1], earth[2]
    cam.look_at(*earth)
    jd = 2_451_545.0
    pose = capture_earth_cam(cam, earth, jd)
    cam.x += 1.0e9
    apply_earth_cam(cam, earth, jd, pose)
    assert cam.x == pytest.approx(earth[0] + 8.0e7, rel=1e-6, abs=20.0)
    assert cam.y == pytest.approx(earth[1], rel=1e-6, abs=20.0)
    assert cam.z == pytest.approx(earth[2], rel=1e-6, abs=20.0)


def test_earth_cam_spin_keeps_ecef_eye() -> None:
    from arelis.earth.frames import (
        EarthCam,
        apply_earth_cam,
        ecliptic_offset_to_ecef,
    )
    from arelis.physics.camera import FlyCamera

    cam = FlyCamera()
    earth = (1.5e11, 0.0, 0.0)
    pose = EarthCam(
        eye=lla_to_ecef(40.0, -75.0, 40_000_000.0),
        look=(0.0, 0.0, 0.0),
        up=(0.0, 0.0, 1.0),
    )
    jd_a = 2_451_545.0
    jd_b = jd_a + 0.5
    apply_earth_cam(cam, earth, jd_a, pose)
    off_a = (cam.x - earth[0], cam.y - earth[1], cam.z - earth[2])
    apply_earth_cam(cam, earth, jd_b, pose)
    off_b = (cam.x - earth[0], cam.y - earth[1], cam.z - earth[2])
    ecef_a = ecliptic_offset_to_ecef(off_a, jd_a)
    ecef_b = ecliptic_offset_to_ecef(off_b, jd_b)
    assert ecef_a[0] == pytest.approx(pose.eye[0], rel=1e-6, abs=50.0)
    assert ecef_b[0] == pytest.approx(pose.eye[0], rel=1e-6, abs=50.0)
    assert ecef_a[1] == pytest.approx(pose.eye[1], rel=1e-6, abs=50.0)
    assert ecef_b[1] == pytest.approx(pose.eye[1], rel=1e-6, abs=50.0)
    assert math.hypot(*off_a) != pytest.approx(0.0)
    assert off_a[0] != pytest.approx(off_b[0], abs=1.0e5)


def test_jobs_do_not_get_earth() -> None:
    from arelis.config import load_config
    from arelis.tools import build_tool_registry
    from arelis.workspace import WorkspaceRoots

    config = load_config()
    jobs = build_tool_registry(
        config, WorkspaceRoots.from_config(config), allow_send=False
    )
    assert "earth" not in jobs.names()
    attended = build_tool_registry(
        config, WorkspaceRoots.from_config(config), allow_send=True
    )
    assert "earth" in attended.names()


def _ais_envelope(lat: float, lon: float, mmsi: str, name: str = "TEST") -> dict:
    return {
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": mmsi,
            "ShipName": name,
            "latitude": lat,
            "longitude": lon,
            "time_utc": "2026-08-28 12:00:00.000000000 +0000 UTC",
        },
        "Message": {
            "PositionReport": {
                "UserID": int(mmsi) if mmsi.isdigit() else 0,
                "Latitude": lat,
                "Longitude": lon,
                "Sog": 12.3,
                "Cog": 180.0,
            }
        },
    }


def test_ais_keeps_coasts_and_paints_gyre_packets() -> None:
    from arelis.earth.ais import entities_from_messages, open_ocean_hole

    assert open_ocean_hole(51.9, 4.48) is False
    assert open_ocean_hole(21.3, -157.8) is False
    assert open_ocean_hole(19.3, 166.65) is False
    assert open_ocean_hole(28.2, -177.4) is False
    assert open_ocean_hole(16.7, -169.5) is False
    assert open_ocean_hole(30.0, -150.0) is True
    assert open_ocean_hole(25.0, -40.0) is True
    messages = [
        _ais_envelope(51.90, 4.48, "244123456", "ROTTERDAM"),
        _ais_envelope(30.0, -150.0, "367000001", "GYRE"),
        _ais_envelope(21.3, -157.8, "338000002", "HONOLULU"),
    ]
    ships = entities_from_messages(messages, unix=1.0)
    ids = {e.id for e in ships}
    assert ids == {"mmsi:244123456", "mmsi:367000001", "mmsi:338000002"}
    hit = next(e for e in ships if e.id == "mmsi:244123456")
    assert hit.freshness == "live"
    assert hit.layer == "vessels"
    assert "paid" in hit.cite
    assert "APIKey" not in hit.cite
    assert "aisstream_key" not in str(hit.meta)


def test_ais_without_key_does_not_open_a_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arelis.earth import ais as ais_mod

    monkeypatch.setattr(ais_mod, "aisstream_key", lambda path=None: "")
    monkeypatch.setattr(ais_mod, "fetch_digitraffic", lambda: None)
    monkeypatch.setattr(ais_mod, "fetch_barentswatch", lambda: None)

    def _boom(*_a, **_k):
        raise AssertionError("websocket must not run without a key")

    monkeypatch.setattr(ais_mod, "_drain", _boom)
    assert ais_mod.fetch_ais() is None


def test_ais_without_key_still_uses_digitraffic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arelis.earth import ais as ais_mod
    from arelis.earth.entity import Entity

    monkeypatch.setattr(ais_mod, "aisstream_key", lambda path=None: "")
    monkeypatch.setattr(ais_mod, "fetch_barentswatch", lambda: None)

    def _boom(*_a, **_k):
        raise AssertionError("websocket must not run without a key")

    monkeypatch.setattr(ais_mod, "_drain", _boom)
    pos = lla_to_ecef(60.15, 24.96, 0.0)
    finland = Entity(
        id="mmsi:230000001",
        cls="vessel",
        layer="vessels",
        label="SUOMENLINNA",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        freshness="live",
        source="Fintraffic Digitraffic",
        when_unix=2.0,
    )
    monkeypatch.setattr(ais_mod, "fetch_digitraffic", lambda: [finland])
    ships = ais_mod.fetch_ais()
    assert ships is not None
    assert {e.id for e in ships} == {"mmsi:230000001"}


def test_digitraffic_geojson_keeps_helsinki_and_names() -> None:
    from arelis.earth.ais import entities_from_digitraffic

    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "mmsi": 230000001,
                "geometry": {"type": "Point", "coordinates": [24.96, 60.15]},
                "properties": {
                    "mmsi": 230000001,
                    "sog": 8.2,
                    "cog": 90.0,
                    "timestampExternal": 1_700_000_000_000,
                },
            },
            {
                "mmsi": 367000001,
                "geometry": {"type": "Point", "coordinates": [-150.0, 30.0]},
                "properties": {"mmsi": 367000001, "timestampExternal": 1_700_000_000_000},
            },
        ],
    }
    names = [{"mmsi": 230000001, "name": "SUOMENLINNA II"}]
    ships = entities_from_digitraffic(payload, names, unix=1.0)
    assert {e.id for e in ships} == {"mmsi:230000001", "mmsi:367000001"}
    hit = next(e for e in ships if e.id == "mmsi:230000001")
    assert hit.label == "SUOMENLINNA II"
    assert hit.source == "Fintraffic Digitraffic"
    assert hit.freshness == "live"
    assert "Fintraffic" in hit.cite
    assert hit.when_unix == pytest.approx(1_700_000_000.0)


def test_merge_vessels_newer_report_wins() -> None:
    from arelis.earth.ais import merge_vessels
    from arelis.earth.entity import Entity

    pos = lla_to_ecef(60.15, 24.96, 0.0)
    older = Entity(
        id="mmsi:230000001",
        cls="vessel",
        layer="vessels",
        label="OLD",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        when_unix=1.0,
        source="AISStream",
        freshness="live",
    )
    newer = Entity(
        id="mmsi:230000001",
        cls="vessel",
        layer="vessels",
        label="NEW",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        when_unix=2.0,
        source="Fintraffic Digitraffic",
        freshness="live",
    )
    other = Entity(
        id="mmsi:244123456",
        cls="vessel",
        layer="vessels",
        label="ROTTERDAM",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        when_unix=1.5,
        source="AISStream",
        freshness="live",
    )
    merged = merge_vessels([older, other], [newer])
    by_id = {e.id: e for e in merged}
    assert by_id["mmsi:230000001"].label == "NEW"
    assert "mmsi:244123456" in by_id


def test_live_ais_replaces_vessels_and_tick_does_not_clobber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.live import merge_live
    from arelis.earth.simulate import populate, refresh_moving

    store = EntityStore()
    populate(store, 1.0)
    assert len(store.in_layer("vessels")) > 50
    pos = lla_to_ecef(51.9, 4.48, 0.0)
    live_ship = Entity(
        id="mmsi:244123456",
        cls="vessel",
        layer="vessels",
        label="ROTTERDAM",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        freshness="live",
        source="AISStream",
        cite="AISStream terrestrial AIS.",
    )
    _mute_live(monkeypatch, fetch_ais=lambda: [live_ship])
    merge_live(store)
    ships = store.in_layer("vessels")
    assert len(ships) == 1
    assert ships[0].id == "mmsi:244123456"
    refresh_moving(store, 10.0)
    still = store.in_layer("vessels")
    assert len(still) == 1
    assert still[0].id == "mmsi:244123456"
    assert still[0].freshness == "live"
    assert all(not e.id.startswith("sim-ship:") for e in still)


def test_military_live_does_not_freeze_civil_sim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.live import merge_live
    from arelis.earth.simulate import populate, refresh_moving

    store = EntityStore()
    populate(store, 1.0)
    civil = store.get("sim-flight:0001")
    assert civil is not None and civil.layer == "flights"
    before = (civil.x, civil.y, civil.z)
    pos = lla_to_ecef(51.5, -0.12, 10_000.0)
    mil = Entity(
        id="icao:ae0001",
        cls="aircraft",
        layer="military",
        label="RCH1",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        freshness="delayed",
        source="adsb.lol",
        cite="adsb.lol public mil ADS-B.",
    )
    _mute_live(monkeypatch, fetch_adsb_mil=lambda: [mil])
    merge_live(store)
    assert store.get("icao:ae0001") is not None
    refresh_moving(store, 10_000.0)
    assert store.get("icao:ae0001") is not None
    after = store.get("sim-flight:0001")
    assert after is not None
    moved = ((after.x - before[0]) ** 2 + (after.y - before[1]) ** 2 + (after.z - before[2]) ** 2) ** 0.5
    assert moved > 100.0
    assert all(e.id != "sim-flight:0000" for e in store.in_layer("military"))


def test_refresh_still_moves_simulated_vessels() -> None:
    from arelis.earth.simulate import populate, refresh_moving

    store = EntityStore()
    populate(store, 1.0)
    before = store.get("sim-ship:0000")
    assert before is not None
    refresh_moving(store, 10_000.0)
    after = store.get("sim-ship:0000")
    assert after is not None
    assert after.freshness == "simulated"
    moved = (after.x - before.x) ** 2 + (after.y - before.y) ** 2
    assert moved > 1.0


def test_live_ais_failure_keeps_sim(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth.live import merge_live
    from arelis.earth.simulate import populate

    store = EntityStore()
    populate(store, 1.0)
    n = len(store.in_layer("vessels"))
    _mute_live(monkeypatch)
    merge_live(store)
    assert len(store.in_layer("vessels")) == n
    assert all(e.freshness == "simulated" for e in store.in_layer("vessels"))


# Public ISS TLE (CelesTrak epoch 2008 day 264). Not a personal coordinate.
_ISS_TLE = """ISS (ZARYA)
1 25544U 98067A   08264.51782528 -.00002182  00000-0 -11606-4 0  2927
2 25544  51.6416 247.4627 0006703 130.5360 325.0288 15.72125391563537
"""


def test_teme_to_ecef_preserves_radius_and_z() -> None:
    from arelis.earth.frames import julian_unix, teme_to_ecef

    jd = julian_unix(1_220_000_000.0)
    teme = (4.0e6, 3.0e6, 5.0e6)
    ecef = teme_to_ecef(teme, jd)
    r0 = (teme[0] ** 2 + teme[1] ** 2 + teme[2] ** 2) ** 0.5
    r1 = (ecef[0] ** 2 + ecef[1] ** 2 + ecef[2] ** 2) ** 0.5
    assert ecef[2] == pytest.approx(teme[2])
    assert r1 == pytest.approx(r0, rel=1e-12)


def test_tle_iss_is_norad_25544_in_leo() -> None:
    pytest.importorskip("sgp4")
    from datetime import UTC, datetime, timedelta

    from arelis.earth.tle import entities_from_tle_text, parse_tle_blocks

    blocks = parse_tle_blocks(_ISS_TLE)
    assert len(blocks) == 1
    assert blocks[0][0].startswith("ISS")
    epoch = datetime(2008, 1, 1, tzinfo=UTC) + timedelta(days=263.51782528)
    ships = entities_from_tle_text(_ISS_TLE, unix=epoch.timestamp())
    assert len(ships) == 1
    iss = ships[0]
    assert iss.id == "norad:25544"
    assert iss.layer == "iss"
    assert iss.label == "ISS"
    assert iss.freshness == "interpolated"
    r = (iss.x**2 + iss.y**2 + iss.z**2) ** 0.5
    assert 6.6e6 < r < 6.9e6
    assert "CelesTrak" in iss.cite
    assert "Starlink" in iss.cite


def test_live_tle_replaces_iss_and_tick_does_not_clobber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sgp4")
    from datetime import UTC, datetime, timedelta

    from arelis.earth.live import merge_live
    from arelis.earth.simulate import populate, refresh_moving
    from arelis.earth.tle import entities_from_tle_text

    epoch = datetime(2008, 1, 1, tzinfo=UTC) + timedelta(days=263.51782528)
    live_iss = entities_from_tle_text(_ISS_TLE, unix=epoch.timestamp())
    assert live_iss
    store = EntityStore()
    populate(store, 1.0)
    assert store.get("norad:25544") is not None
    assert store.get("norad:25544").freshness == "simulated"
    _mute_live(monkeypatch, fetch_celestrak=lambda: live_iss)
    merge_live(store)
    hit = store.get("norad:25544")
    assert hit is not None
    assert hit.freshness == "interpolated"
    assert hit.layer == "iss"
    n_sat = len(store.in_layer("satellites"))
    refresh_moving(store, epoch.timestamp())
    still = store.get("norad:25544")
    assert still is not None
    assert still.freshness == "interpolated"
    assert len(store.in_layer("satellites")) == n_sat


def test_celestrak_without_sgp4_keeps_sim(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth import tle as tle_mod

    monkeypatch.setattr(tle_mod, "_sgp4_ready", lambda: False)

    def _boom(*_a, **_k):
        raise AssertionError("CelesTrak must not fetch without sgp4")

    monkeypatch.setattr(tle_mod, "_get_tle", _boom)
    assert tle_mod.fetch_celestrak(unix=1.0) is None


def test_radio_keeps_geo_and_drops_missing() -> None:
    from arelis.earth.radio import entities_from_stations
    from arelis.earth.simulate import RADIO

    name, pin_lat, pin_lon = RADIO[0]
    rows = [
        {
            "stationuuid": "bbc-r4",
            "name": name,
            "geo_lat": pin_lat,
            "geo_long": pin_lon,
            "country": "The United Kingdom Of Great Britain And Northern Ireland",
            "homepage": "https://www.bbc.co.uk/radio4",
            "url": "http://should-not-be-stored.example/stream",
        },
        {
            "stationuuid": "null-island",
            "name": "Null",
            "geo_lat": 0.0,
            "geo_long": 0.0,
        },
        {
            "stationuuid": "no-geo",
            "name": "Nowhere",
        },
    ]
    pins = entities_from_stations(rows)
    assert len(pins) == 1
    hit = pins[0]
    assert hit.id == "rb:bbc-r4"
    assert hit.layer == "radio"
    assert hit.cls == "rf"
    assert hit.freshness == "reconstructed"
    assert "url" not in hit.meta
    assert "should-not-be-stored" not in hit.cite
    assert "should-not-be-stored" not in str(hit.meta)
    assert "audio ingest" in hit.cite.lower()


def test_live_radio_replaces_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.live import merge_live
    from arelis.earth.simulate import RADIO, populate

    store = EntityStore()
    populate(store, 1.0)
    n_sim = len(store.in_layer("radio"))
    assert n_sim >= 4
    _name, pin_lat, pin_lon = RADIO[0]
    pos = lla_to_ecef(pin_lat, pin_lon, 80.0)
    live_pin = Entity(
        id="rb:bbc-r4",
        cls="rf",
        layer="radio",
        label="BBC Radio 4",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        freshness="reconstructed",
        source="Radio Browser",
        cite="Radio Browser directory.",
    )
    _mute_live(monkeypatch, fetch_radio=lambda: [live_pin])
    merge_live(store)
    pins = store.in_layer("radio")
    assert len(pins) == 1
    assert pins[0].id == "rb:bbc-r4"
    assert all(not e.id.startswith("sim-radio:") for e in pins)


def test_radio_fetch_failure_does_not_open_if_unpinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arelis.earth import radio as radio_mod

    monkeypatch.setattr(radio_mod, "_host_pinned", lambda _h: False)
    assert radio_mod.fetch_radio() is None


def test_ecef_vel_from_track_east_is_along_east() -> None:
    from arelis.earth.frames import ecef_vel_from_track, enu_axes

    lat, lon = 51.5, -0.12
    east, _north, _up = enu_axes(lat, lon)
    vx, vy, vz = ecef_vel_from_track(lat, lon, 100.0, 90.0)
    assert vx == pytest.approx(100.0 * east[0], rel=1e-9)
    assert vy == pytest.approx(100.0 * east[1], rel=1e-9)
    assert vz == pytest.approx(100.0 * east[2], rel=1e-9)


def test_enu_east_matches_east_axis() -> None:
    from arelis.earth.frames import enu_axes, enu_to_ecef

    lat, lon = 51.5, -0.12
    origin = lla_to_ecef(lat, lon, 0.0)
    east, _north, _up = enu_axes(lat, lon)
    got = enu_to_ecef(lat, lon, 1000.0, 0.0, 0.0)
    assert got[0] - origin[0] == pytest.approx(1000.0 * east[0], rel=1e-9)
    assert got[1] - origin[1] == pytest.approx(1000.0 * east[1], rel=1e-9)
    assert got[2] - origin[2] == pytest.approx(1000.0 * east[2], rel=1e-9)


def test_viewshed_north_frustum_is_along_north() -> None:
    from arelis.earth.frames import enu_axes
    from arelis.earth.viewshed import frustum_ecef

    lat, lon = 51.5, -0.12
    origin = lla_to_ecef(lat, lon, 12.0)
    _east, north, _up = enu_axes(lat, lon)
    _pin, *arc = frustum_ecef(lat, lon, 0.0, 10.0, 800.0)
    assert len(arc) >= 3
    for point in arc:
        along = (
            (point[0] - origin[0]) * north[0]
            + (point[1] - origin[1]) * north[1]
            + (point[2] - origin[2]) * north[2]
        )
        assert along > 700.0


def test_bundled_cameras_have_pose_prior_viewsheds() -> None:
    store = EntityStore()
    populate(store, 1.0)
    cams = store.in_layer("cameras")
    assert {e.id for e in cams} == {row[0] for row in CAMERAS}
    for ent in cams:
        assert ent.freshness == "reconstructed"
        assert ent.coverage is not None
        assert ent.coverage.kind == "viewshed"
        fan = ent.meta.get("viewshed_ecef")
        assert isinstance(fan, list) and len(fan) >= 4


def test_tfl_places_keep_geo_and_drop_streams() -> None:
    from arelis.earth.cameras import entities_from_places
    from arelis.earth.simulate import CAMERAS

    cid, pin_lat, pin_lon, label = CAMERAS[0]
    rows = [
        {
            "id": "JamCams_00001.01251",
            "commonName": label,
            "lat": pin_lat,
            "lon": pin_lon,
            "url": "https://should-not-be-stored.example/cam",
            "additionalProperties": [
                {"key": "ImageUrl", "value": "https://should-not-be-stored.example/still.jpg"},
                {"key": "videoUrl", "value": "https://should-not-be-stored.example/stream.mp4"},
            ],
        },
        {"id": "JamCams_null", "commonName": "Null", "lat": 0.0, "lon": 0.0},
        {"id": "JamCams_nogeo", "commonName": "Nowhere"},
    ]
    pins = entities_from_places(rows)
    assert len(pins) == 1
    hit = pins[0]
    assert hit.id == "tfl:JamCams_00001.01251"
    assert hit.layer == "cameras"
    assert hit.freshness == "reconstructed"
    assert "url" not in hit.meta
    assert "ImageUrl" not in str(hit.meta)
    assert "should-not-be-stored" not in hit.cite
    assert "should-not-be-stored" not in str(hit.meta)
    assert "video ingest" in hit.cite.lower()
    # Bundled Trafalgar id has a pose prior; this JamCam id does not.
    assert hit.id != cid
    assert hit.coverage is not None
    assert hit.coverage.kind == "pin"


def test_live_cameras_replace_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.live import merge_live

    store = EntityStore()
    populate(store, 1.0)
    assert len(store.in_layer("cameras")) == len(CAMERAS)
    pos = lla_to_ecef(51.508, -0.128, 12.0)
    live_cam = Entity(
        id="tfl:JamCams_00001.01251",
        cls="camera",
        layer="cameras",
        label="TfL Trafalgar Square",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        freshness="reconstructed",
        source="TfL JamCam",
        cite="TfL JamCam published position.",
    )
    _mute_live(monkeypatch, fetch_cameras=lambda: [live_cam])
    merge_live(store)
    cams = store.in_layer("cameras")
    assert len(cams) == 1
    assert cams[0].id == "tfl:JamCams_00001.01251"
    assert all(not e.id.startswith("caltrans:") for e in cams)


def test_camera_fetch_failure_does_not_open_if_unpinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arelis.earth import cameras as cameras_mod

    monkeypatch.setattr(cameras_mod, "_host_pinned", lambda *_a, **_k: False)
    monkeypatch.setattr(cameras_mod, "fetch_osm_webcams", lambda: None)
    assert cameras_mod.fetch_cameras() is None


def test_opensky_uav_category_is_the_drones_layer() -> None:
    from arelis.earth.live import entities_from_opensky

    payload = {
        "time": 1.0,
        "states": [
            ["abc123", "UAL1  ", None, None, None, -0.12, 51.5, 10000, False, 200, 90, 0, None, None, None, None, 0, 0],
            ["def456", "UAV1  ", None, None, None, -0.12, 51.5, 120, False, 20, 0, 0, None, None, None, None, 0, 14],
        ],
    }
    rows = entities_from_opensky(payload)
    by_id = {e.id: e for e in rows}
    assert by_id["icao:abc123"].layer == "flights"
    assert by_id["icao:def456"].layer == "drones"
    assert by_id["icao:abc123"].vx != 0.0 or by_id["icao:abc123"].vy != 0.0
    assert "not every car" in by_id["icao:abc123"].cite.lower() or "cars" in by_id["icao:abc123"].cite.lower()


def test_caltrans_look_direction_becomes_a_viewshed() -> None:
    from arelis.earth.cameras import entities_from_caltrans

    payload = {
        "data": [
            {
                "cctv": {
                    "index": "17",
                    "location": {
                        "district": "4",
                        "locationName": "Bay Bridge",
                        "latitude": "37.784",
                        "longitude": "-122.406",
                        "direction": "South",
                        "route": "I-80",
                    },
                    "imageData": {
                        "currentImageURL": "https://should-not-be-stored.example/still.jpg",
                        "streamingVideoURL": "https://should-not-be-stored.example/stream",
                    },
                }
            }
        ]
    }
    pins = entities_from_caltrans(payload)
    assert len(pins) == 1
    hit = pins[0]
    assert hit.id.startswith("caltrans:")
    assert hit.coverage is not None
    assert hit.coverage.kind == "viewshed"
    assert hit.meta.get("heading_deg") == 180.0
    assert "should-not-be-stored" not in str(hit.meta)
    assert "should-not-be-stored" not in hit.cite


def test_people_need_coordinates_on_the_card(tmp_path: Path) -> None:
    from arelis.earth.people import load_people

    book = tmp_path / "contacts.yaml"
    book.write_text(
        "contacts:\n"
        "  mapped:\n"
        "    name: Mapped\n"
        "    phone: '+15555550123'\n"
        "    lat: 51.5\n"
        "    lon: -0.12\n"
        "  unknown:\n"
        "    name: Unknown\n"
        "    phone: '+15555550124'\n",
        encoding="utf-8",
    )
    pins = load_people(book)
    assert len(pins) == 1
    assert pins[0].id == "contact:mapped"
    assert pins[0].layer == "people"
    assert pins[0].pii == "contact"


def test_adsb_mil_keeps_squawks() -> None:
    from arelis.earth.adsb import entities_from_ac

    rows = entities_from_ac(
        [
            {"hex": "ae0001", "flight": "RCH1", "lat": 51.5, "lon": -0.12, "alt_baro": 30000, "gs": 400},
            {"hex": "nogeo", "flight": "NONE"},
        ]
    )
    assert len(rows) == 1
    assert rows[0].layer == "military"
    assert rows[0].freshness == "delayed"


def test_overlay_ink_is_sodium_not_gold() -> None:
    from arelis.ui.earth_overlay import _FRESH_SCALE, _INK_ROLE, _ink
    from arelis.ui.theme import COLORS

    amber = COLORS["amber"].lower()
    assert amber == "#ff7a22"
    assert _INK_ROLE["flights"] == "amber"
    assert _INK_ROLE["iss"] == "text"
    assert _INK_ROLE["drones"] == "warn"
    assert _INK_ROLE["people"] == "text"
    live = _ink("flights", freshness="live")
    stale = _ink("flights", freshness="stale")
    assert stale.alpha() < live.alpha()
    assert _FRESH_SCALE["dead-reckoned"] < _FRESH_SCALE["delayed"]


def test_enter_note_names_simulated_or_live(monkeypatch: pytest.MonkeyPatch) -> None:
    _mute_live(monkeypatch)
    earth = EarthRuntime()
    note = earth.enter(unix=1.0)
    assert "simulated" in note
    earth.leave()
    earth.live = True
    note = earth.enter(unix=1.0)
    assert "live" in note


def test_shipped_feed_hosts_are_pinned() -> None:
    from arelis.earth.feeds import FEEDS, shipped_hosts
    from tests.test_egress import ALLOWED

    assert {spec.status for spec in FEEDS} <= {"shipped", "keyed", "later", "out"}
    assert any(spec.id == "unsecured-cams" and spec.status == "out" for spec in FEEDS)
    assert any(spec.id == "car-vin" and spec.status == "out" for spec in FEEDS)
    assert any(spec.id == "sat-ais" and spec.status == "out" for spec in FEEDS)
    assert any(
        spec.id == "digitraffic" and spec.status == "shipped" for spec in FEEDS
    )
    assert any(
        spec.id == "sentinel1-asf" and spec.status == "shipped" for spec in FEEDS
    )
    assert any(spec.id == "eonet" and spec.status == "shipped" for spec in FEEDS)
    for host in shipped_hosts():
        assert any(
            pin == host or pin.endswith("." + host) or host.endswith("." + pin)
            for pin in ALLOWED
        ), host


def test_earth_docs_inventory_matches_feeds() -> None:
    from collections import Counter
    from pathlib import Path

    from arelis.earth.feeds import FEEDS

    counts = Counter(spec.status for spec in FEEDS)
    earth = Path("docs/earth.md").read_text(encoding="utf-8")
    assert f"{counts['shipped']} shipped" in earth
    assert f"{counts['keyed']} keyed" in earth
    assert f"**{counts['later']} later**" in earth
    assert f"**{counts['out']} out**" in earth


def test_merge_live_stubs_every_fetcher() -> None:
    import arelis.earth.live as live_mod

    named = {name for name in _LIVE_FETCHERS}
    # Every fetch_* on live.py used by merge_live must be in the mute list.
    source = live_mod.merge_live.__code__.co_names
    fetches = {name for name in source if name.startswith("fetch_")}
    assert fetches <= named
    assert "fetch_cameras" in fetches
    assert "fetch_traffic" in fetches
    assert "fetch_aprs" in fetches
    assert "fetch_shodan" in fetches
    assert "fetch_radar" in fetches
    assert "fetch_gfw" in fetches
    assert "fetch_eonet" in fetches
    assert "fetch_nws" in fetches
    assert "fetch_airports" in fetches
    assert "fetch_spacetrack" in fetches
    assert "fetch_emsc" in fetches
    assert "fetch_waqi" in fetches
    assert "fetch_geonet" in fetches
    assert "fetch_ndbc" in fetches
    assert "fetch_volcanoes" in fetches
    assert "fetch_gdacs" in fetches
    assert "fetch_tides" in fetches
    assert "fetch_argo" in fetches


def test_caltrans_cctv_covers_twelve_districts() -> None:
    from arelis.earth.cameras import CALTRANS_CCTV

    assert len(CALTRANS_CCTV) == 12
    assert "d1/cctv/cctvStatusD01.json" in CALTRANS_CCTV[0]
    assert "d12/cctv/cctvStatusD12.json" in CALTRANS_CCTV[-1]


def test_aprs_without_a_key_stays_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth import aprs as aprs_mod

    monkeypatch.setattr(aprs_mod, "aprs_key", lambda path=None: "")
    assert aprs_mod.fetch_aprs() is None


def test_aprs_skips_ais_and_credits_the_source() -> None:
    from arelis.earth.aprs import _CITE, _UA, DEFAULT_CALLS, entities_from_entries

    assert DEFAULT_CALLS == ("W1AW",)
    assert "https://aprs.fi" in _CITE
    assert "Arelis/" in _UA
    pins = entities_from_entries(
        {
            "result": "ok",
            "entries": [
                {"name": "W1AW", "type": "l", "lat": "41.7", "lng": "-72.7"},
                {"name": "SHIP", "type": "a", "lat": "41.7", "lng": "-72.7", "mmsi": "1"},
            ],
        }
    )
    assert [p.id for p in pins] == ["aprs:w1aw"]


def test_shodan_drops_ip_and_banner_body() -> None:
    from arelis.earth.shodan import entities_from_matches

    pins = entities_from_matches(
        {
            "matches": [
                {
                    "ip_str": "203.0.113.10",
                    "data": "admin:admin rtsp://203.0.113.10/stream",
                    "product": "IP Camera",
                    "location": {"latitude": 37.8, "longitude": -122.4},
                }
            ]
        }
    )
    assert len(pins) == 1
    blob = str(pins[0].meta) + pins[0].cite + pins[0].id
    assert "203.0.113.10" not in blob
    assert "admin:admin" not in blob
    assert "rtsp://" not in blob
    assert pins[0].layer == "cameras"


def test_caltrans_lcs_is_a_closure_not_a_car() -> None:
    from arelis.earth.traffic import entities_from_lcs

    pins = entities_from_lcs(
        {
            "data": [
                {
                    "lcs": {
                        "index": "42",
                        "location": {
                            "latitude": "37.8",
                            "longitude": "-122.4",
                            "locationName": "Bay Bridge",
                            "route": "80",
                            "district": "4",
                        },
                    }
                }
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].layer == "traffic"
    assert pins[0].id.startswith("lcs:")
    assert pins[0].cls == "traffic"


def test_tfl_road_disruption_is_not_a_car() -> None:
    from arelis.earth.traffic import entities_from_tfl

    pins = entities_from_tfl(
        [
            {
                "id": "ABC",
                "location": "A12 Bow",
                "category": "RealTime",
                "geography": {"type": "Point", "coordinates": [-0.02, 51.53]},
            }
        ]
    )
    assert len(pins) == 1
    assert pins[0].id == "tfl-road:ABC"
    assert pins[0].layer == "traffic"
    assert "not a vin" in pins[0].cite.lower()


def test_eonet_uses_the_last_point() -> None:
    from arelis.earth.eonet import entities_from_events

    rows = [
        {
            "id": "EONET_1",
            "title": "Tropical Storm Test",
            "categories": [{"id": "severeStorms", "title": "Severe Storms"}],
            "geometry": [
                {
                    "date": "2026-08-25T06:00:00Z",
                    "type": "Point",
                    "coordinates": [-119.9, 14.9],
                },
                {
                    "date": "2026-08-25T18:00:00Z",
                    "type": "Point",
                    "coordinates": [-118.8, 19.5],
                },
            ],
        }
    ]
    hits = entities_from_events(rows)
    assert len(hits) == 1
    assert hits[0].id == "eonet:EONET_1"
    assert hits[0].layer == "sites"
    assert hits[0].freshness == "delayed"
    assert "face" in hits[0].cite.lower()
    assert hits[0].meta["lon"] == pytest.approx(-118.8)


def test_osm_webcam_has_no_stream_url() -> None:
    from arelis.earth.osm import entities_from_elements

    pins = entities_from_elements(
        [
            {
                "type": "node",
                "id": 99,
                "lat": 51.5,
                "lon": -0.12,
                "tags": {"name": "Thames", "camera:type": "webcam", "url": "rtsp://x"},
            }
        ]
    )
    assert len(pins) == 1
    assert pins[0].id == "osm:node:99"
    assert pins[0].layer == "cameras"
    blob = str(pins[0].meta) + pins[0].cite
    assert "rtsp://" not in blob


def test_radar_keeps_ocean_passes() -> None:
    from arelis.earth.radar import entities_from_features

    features = [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-151.0, 29.0],
                        [-149.0, 29.0],
                        [-149.0, 31.0],
                        [-151.0, 31.0],
                        [-151.0, 29.0],
                    ]
                ],
            },
            "properties": {
                "centerLat": 30.0,
                "centerLon": -150.0,
                "sceneName": "S1A_IW_GRDH_1SDV_GYRE",
                "platform": "Sentinel-1A",
                "startTime": "2026-08-27T16:23:33Z",
            },
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [80.0, -10.0],
                        [82.0, -10.0],
                        [82.0, -8.0],
                        [80.0, -8.0],
                        [80.0, -10.0],
                    ]
                ],
            },
            "properties": {
                "centerLat": -9.0,
                "centerLon": 81.0,
                "sceneName": "S1A_IW_GRDH_1SDV_INDIAN",
                "platform": "Sentinel-1A",
                "startTime": "2026-08-27T16:23:33Z",
            },
        },
    ]
    frames = entities_from_features(features)
    assert {e.id for e in frames} == {
        "s1:S1A_IW_GRDH_1SDV_GYRE",
        "s1:S1A_IW_GRDH_1SDV_INDIAN",
    }
    hit = next(e for e in frames if "GYRE" in e.id)
    assert hit.layer == "radar"
    assert hit.freshness == "delayed"
    assert hit.cls == "site"
    assert "hull" in hit.cite.lower() or "ship" in hit.cite.lower()
    assert hit.meta["footprint_ll"][0] == [29.0, -151.0]


def test_radar_without_catalog_stays_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth import radar as radar_mod

    monkeypatch.setattr(radar_mod, "_search_box", lambda *_a, **_k: None)
    assert radar_mod.fetch_radar() is None


def test_live_radar_replaces_empty_layer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.live import merge_live
    from arelis.earth.simulate import populate

    store = EntityStore()
    populate(store, 1.0)
    assert len(store.in_layer("radar")) == 0
    pos = lla_to_ecef(30.0, -150.0, 0.0)
    frame = Entity(
        id="s1:TEST",
        cls="site",
        layer="radar",
        label="Sentinel-1A pass",
        x=pos[0],
        y=pos[1],
        z=pos[2],
        freshness="delayed",
        source="NASA ASF DAAC",
    )
    _mute_live(monkeypatch, fetch_radar=lambda: [frame])
    merge_live(store)
    hits = store.in_layer("radar")
    assert len(hits) == 1
    assert hits[0].id == "s1:TEST"


def test_earth_chip_items_cover_live_and_every_layer() -> None:
    from arelis.earth.entity import LAYER_IDS
    from arelis.ui.earth_overlay import earth_chip_items

    kinds = [kind for kind, _label in earth_chip_items()]
    assert kinds[0] == "live"
    assert kinds[1] == "tiles"
    assert tuple(kinds[2:]) == LAYER_IDS


def test_earth_chips_toggle_live_and_layers(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    from arelis.ui.panels.solar import SolarPanel

    _mute_live(monkeypatch)
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    panel.resize(640, 480)
    panel._hud_bottom = 80
    hits, box = panel._earth_chip_layout()
    kinds = [kind for kind, _rect in hits]
    assert kinds[0] == "live"
    assert "tiles" in kinds
    assert "flights" in kinds
    assert "traffic" in kinds
    assert not box.isEmpty()
    assert earth.layers["flights"] is True
    panel._toggle_earth_chip("flights")
    assert earth.layers["flights"] is False
    assert earth.layers["traffic"] is False
    panel._toggle_earth_chip("traffic")
    assert earth.layers["traffic"] is True
    live_rect = next(rect for kind, rect in hits if kind == "live")
    pos = QPointF(live_rect.center().x(), live_rect.center().y())
    press = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    panel.mousePressEvent(press)
    assert earth.live is True
    panel._toggle_earth_chip("tiles")
    assert earth.tiles is True
    panel.hide()


def test_nyc_cameras_keep_geo_and_drop_stills() -> None:
    from arelis.earth.cameras import entities_from_nyc

    pins = entities_from_nyc(
        [
            {
                "id": "cam-1",
                "name": "Central Park",
                "latitude": 40.785,
                "longitude": -73.969,
                "imageUrl": "https://should-not-be-stored.example/still.jpg",
            },
            {"id": "zero", "name": "Null", "latitude": 0.0, "longitude": 0.0},
        ]
    )
    assert len(pins) == 1
    hit = pins[0]
    assert hit.id == "nyc:cam-1"
    assert "imageUrl" not in str(hit.meta)
    assert "should-not-be-stored" not in str(hit.meta)
    assert "should-not-be-stored" not in hit.cite


def test_singapore_cameras_drop_image_urls() -> None:
    from arelis.earth.cameras import entities_from_singapore

    pins = entities_from_singapore(
        {
            "items": [
                {
                    "cameras": [
                        {
                            "camera_id": "2701",
                            "image": "https://should-not-be-stored.example/a.jpg",
                            "location": {"latitude": 1.44, "longitude": 103.77},
                        }
                    ]
                }
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "sg:2701"
    assert "should-not-be-stored" not in str(pins[0].meta)


def test_hk_xml_keeps_geo_and_drops_url() -> None:
    from arelis.earth.cameras import entities_from_hk_xml

    xml = """
    <image-list>
      <image>
        <key>H429F</key>
        <description>Aberdeen</description>
        <latitude>22.24845</latitude>
        <longitude>114.1505</longitude>
        <url>https://should-not-be-stored.example/H429F.JPG</url>
      </image>
    </image-list>
    """
    pins = entities_from_hk_xml(xml)
    assert len(pins) == 1
    assert pins[0].id == "hk:H429F"
    assert "should-not-be-stored" not in str(pins[0].meta)


def test_owned_face_boxes_sit_in_enu() -> None:
    from arelis.earth.owned import entities_from_boxes

    boxes = entities_from_boxes("desk", 40.7, -74.0, 90.0, 70.0, [(0.5, 0.8, 0.1, 0.1)])
    assert len(boxes) == 1
    hit = boxes[0]
    assert hit.layer == "people"
    assert hit.pii == "inferred"
    assert "rtsp" not in str(hit.meta)
    assert "face index" in hit.cite.lower()


def test_barentswatch_latest_keeps_mmsi() -> None:
    from arelis.earth.barentswatch import entities_from_latest

    ships = entities_from_latest(
        [
            {
                "mmsi": 257789800,
                "name": "GRIEG ARTIC",
                "latitude": 59.14,
                "longitude": 5.82,
                "speedOverGround": 0.1,
                "courseOverGround": 63.8,
                "msgtime": "2022-11-02T13:46:12+00:00",
            }
        ],
        unix=1.0,
    )
    assert len(ships) == 1
    assert ships[0].id == "mmsi:257789800"
    assert ships[0].layer == "vessels"


def test_gfw_report_cells_are_unnamed() -> None:
    from arelis.earth.gfw import entities_from_report

    hits = entities_from_report(
        {"entries": [{"lat": 30.0, "lon": -150.0, "detections": 2, "date": "2026-08-20"}]},
        unix=1.0,
    )
    assert len(hits) == 1
    assert hits[0].layer == "radar"
    assert "mmsi" not in hits[0].meta
    assert hits[0].freshness == "delayed"


def test_open511_is_not_a_car() -> None:
    from arelis.earth.traffic import entities_from_open511

    pins = entities_from_open511(
        {
            "events": [
                {
                    "id": "drivebc.ca/DBC-1",
                    "headline": "CONSTRUCTION",
                    "geography": {"type": "Point", "coordinates": [-123.1, 49.3]},
                },
                {"id": "nogeo", "headline": "Nowhere"},
            ]
        },
        prefix="bc511",
        source="DriveBC Open511",
        cite="DriveBC Open511. Not a VIN index.",
    )
    assert len(pins) == 1
    assert pins[0].id == "bc511:drivebc.ca/DBC-1"
    assert pins[0].layer == "traffic"
    assert "vin" in pins[0].cite.lower()


def test_nsw_hazard_is_not_a_car() -> None:
    from arelis.earth.traffic import entities_from_geojson_incidents

    pins = entities_from_geojson_incidents(
        {
            "features": [
                {
                    "id": "H1",
                    "geometry": {"type": "Point", "coordinates": [151.2, -33.9]},
                    "properties": {
                        "headline": "Crash",
                        "roads": [{"mainStreet": "M1"}],
                    },
                }
            ]
        },
        prefix="nsw",
        source="NSW Live Traffic",
        cite="NSW Live Traffic. Not a VIN index.",
    )
    assert len(pins) == 1
    assert pins[0].id == "nsw:H1"
    assert pins[0].layer == "traffic"


def test_cars_511_is_not_a_car() -> None:
    from arelis.earth.traffic import entities_from_cars

    pins = entities_from_cars(
        [
            {
                "ID": 61,
                "Latitude": 43.65,
                "Longitude": -79.38,
                "RoadwayName": "HWY-401",
                "Description": "Lane blocked",
            },
            {"ID": 0, "Latitude": 0.0, "Longitude": 0.0, "Description": "Null"},
        ],
        prefix="511on",
        source="Ontario 511",
    )
    assert len(pins) == 1
    assert pins[0].id == "511on:61"
    assert pins[0].layer == "traffic"
    assert "vin" in pins[0].cite.lower()


def test_nws_alert_uses_polygon_centroid() -> None:
    from arelis.earth.nws import entities_from_alerts

    pins = entities_from_alerts(
        {
            "features": [
                {
                    "id": "https://api.weather.gov/alerts/urn:oid:1",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-90.0, 38.0],
                                [-89.0, 38.0],
                                [-89.0, 39.0],
                                [-90.0, 39.0],
                                [-90.0, 38.0],
                            ]
                        ],
                    },
                    "properties": {
                        "id": "urn:oid:1",
                        "event": "Tornado Warning",
                        "areaDesc": "Test County",
                    },
                },
                {
                    "id": "nogeo",
                    "geometry": None,
                    "properties": {"id": "nogeo", "event": "Nowhere"},
                },
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "nws:urn:oid:1"
    assert pins[0].layer == "weather"
    assert pins[0].meta["lat"] == pytest.approx(38.5)
    assert pins[0].meta["lon"] == pytest.approx(-89.5)


def test_ourairports_keeps_scheduled_large_fields() -> None:
    from arelis.earth.airports import entities_from_csv

    csv = (
        "id,ident,type,name,latitude_deg,longitude_deg,elevation_ft,continent,"
        "iso_country,iso_region,municipality,scheduled_service,icao_code,iata_code\n"
        "1,EGLL,large_airport,Heathrow,51.47,-0.45,83,EU,GB,GB-ENG,London,yes,EGLL,LHR\n"
        "2,XX00,small_airport,Strip,51.5,-0.12,10,EU,GB,GB-ENG,Nowhere,yes,XX00,\n"
        "3,EGKK,large_airport,Gatwick,51.15,-0.19,202,EU,GB,GB-ENG,London,no,EGKK,LGW\n"
    )
    pins = entities_from_csv(csv)
    assert len(pins) == 1
    assert pins[0].id == "apt:EGLL"
    assert pins[0].layer == "sites"
    assert pins[0].freshness == "reconstructed"
    assert "radar" in pins[0].cite.lower()


def test_dead_reckon_coasts_then_goes_stale() -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.simulate import advance_live

    store = EntityStore()
    pos = lla_to_ecef(51.5, -0.12, 10_000.0)
    store.upsert(
        Entity(
            id="icao:abc123",
            cls="aircraft",
            layer="flights",
            label="UAL1",
            x=pos[0],
            y=pos[1],
            z=pos[2],
            vx=100.0,
            vy=0.0,
            vz=0.0,
            when_unix=1_000.0,
            freshness="delayed",
            source="OpenSky Network",
        )
    )
    advance_live(store, 1_010.0, 10.0)
    mid = store.get("icao:abc123")
    assert mid is not None
    assert mid.freshness == "delayed"
    assert mid.x == pytest.approx(pos[0] + 1000.0)
    advance_live(store, 1_100.0, 10.0)
    aged = store.get("icao:abc123")
    assert aged is not None
    assert aged.freshness == "dead-reckoned"
    advance_live(store, 1_000.0 + 16.0 * 60.0, 10.0)
    dead = store.get("icao:abc123")
    assert dead is not None
    assert dead.freshness == "stale"


def test_refresh_without_dt_does_not_stale_untimestamped_live() -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.simulate import populate, refresh_moving

    store = EntityStore()
    populate(store, 1.0)
    pos = lla_to_ecef(51.5, -0.12, 10_000.0)
    store.upsert(
        Entity(
            id="icao:live1",
            cls="aircraft",
            layer="flights",
            label="LIVE",
            x=pos[0],
            y=pos[1],
            z=pos[2],
            freshness="delayed",
            source="OpenSky Network",
        )
    )
    refresh_moving(store, 10_000.0)
    hit = store.get("icao:live1")
    assert hit is not None
    assert hit.freshness == "delayed"


def test_owned_local_camera_pin_needs_only_wgs84(tmp_path: Path) -> None:
    from arelis.earth.cameras import load_owned

    book = tmp_path / "secrets.yaml"
    book.write_text(
        "earth:\n"
        "  local_camera:\n"
        "    latitude: 51.5\n"
        "    longitude: -0.12\n"
        "    heading_deg: 90\n",
        encoding="utf-8",
    )
    pins = load_owned(book)
    assert len(pins) == 1
    assert pins[0].id == "owned:local"
    assert pins[0].layer == "cameras"
    assert pins[0].meta.get("heading_deg") == 90.0
    assert "rtsp" not in str(pins[0].meta)


def test_osm_boxes_are_denser_than_continents() -> None:
    from arelis.earth.osm import _BOXES

    assert len(_BOXES) >= 40


def test_celestrak_samples_mega_constellations() -> None:
    from arelis.earth.tle import _GROUPS, _SAMPLE_GROUPS

    names = {group for group, _budget in _GROUPS}
    assert "galileo" in names
    assert "education" in names
    assert "intelsat" in names
    assert "starlink" in _SAMPLE_GROUPS
    assert "planet" in _SAMPLE_GROUPS
    assert "oneweb" in _SAMPLE_GROUPS
    assert "military" in _SAMPLE_GROUPS


def test_spacetrack_without_account_does_not_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arelis.earth import spacetrack as st

    monkeypatch.setattr(st, "spacetrack_user", lambda path=None: "")
    monkeypatch.setattr(st, "spacetrack_password", lambda path=None: "")

    def _boom(*_a, **_k):
        raise AssertionError("Space-Track must not login without an account")

    monkeypatch.setattr(st, "_client", _boom)
    assert st.fetch_spacetrack(unix=1.0) is None
    assert st.fetch_tip() is None


def test_spacetrack_tip_is_not_a_hull() -> None:
    from arelis.earth.spacetrack import entities_from_tip

    pins = entities_from_tip(
        [
            {
                "NORAD_CAT_ID": "12345",
                "OBJECT_NAME": "TEST DEB",
                "LAT": 10.0,
                "LON": 20.0,
            },
            {"NORAD_CAT_ID": "0", "OBJECT_NAME": "NOGEO"},
        ]
    )
    assert len(pins) == 1
    assert pins[0].id == "tip:12345"
    assert pins[0].layer == "sites"
    assert "hull" in pins[0].cite.lower() or "guarantee" in pins[0].cite.lower()


def test_swpc_ovation_keeps_bright_cells() -> None:
    from arelis.earth.swpc import entities_from_ovation

    pins = entities_from_ovation(
        {"coordinates": [[-150.0, 65.0, 40.0], [-150.0, 20.0, 2.0]]}
    )
    assert len(pins) == 1
    assert pins[0].layer == "weather"
    assert pins[0].meta["aurora"] == 40.0


def test_emsc_keeps_reported_events() -> None:
    from arelis.earth.emsc import entities_from_fdsn

    pins = entities_from_fdsn(
        {
            "features": [
                {
                    "id": "20260101.1",
                    "geometry": {"type": "Point", "coordinates": [28.0, -26.2]},
                    "properties": {"mag": 4.2, "flynn_region": "SOUTH AFRICA", "time": 1_700_000_000_000},
                },
                {"id": "nogeo", "geometry": {}, "properties": {"mag": 3.0}},
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "emsc:20260101.1"
    assert pins[0].layer == "quakes"


def test_satnogs_station_has_no_audio_url() -> None:
    from arelis.earth.satnogs import entities_from_stations

    pins = entities_from_stations(
        [
            {
                "id": 1,
                "name": "Test",
                "lat": 51.5,
                "lng": -0.12,
                "url": "https://should-not-be-stored.example/stream",
            }
        ]
    )
    assert len(pins) == 1
    assert pins[0].id == "satnogs:1"
    assert pins[0].layer == "radio"
    assert "should-not-be-stored" not in str(pins[0].meta)
    assert "audio" in pins[0].cite.lower()


def test_metar_keeps_station_temp() -> None:
    from arelis.earth.metar import entities_from_geojson

    pins = entities_from_geojson(
        {
            "features": [
                {
                    "geometry": {"type": "Point", "coordinates": [-0.45, 51.47]},
                    "properties": {"id": "EGLL", "temp": 12.0},
                }
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "metar:EGLL"
    assert pins[0].layer == "weather"


def test_waqi_without_token_stays_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth import waqi as waqi_mod

    monkeypatch.setattr(waqi_mod, "waqi_token", lambda path=None: "")
    assert waqi_mod.fetch_waqi() is None


def test_waqi_station_is_not_a_car() -> None:
    from arelis.earth.waqi import entities_from_map

    pins = entities_from_map(
        {
            "data": [
                {"uid": 9, "aqi": 42, "lat": 51.5, "lon": -0.12, "station": {"name": "London"}},
                {"uid": 0, "aqi": "-", "lat": 0.0, "lon": 0.0},
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "waqi:9"
    assert pins[0].layer == "weather"
    assert "car" in pins[0].cite.lower()


def test_viirs_boats_stays_later() -> None:
    from arelis.earth.feeds import FEED_BY_ID

    spec = FEED_BY_ID["viirs-boats"]
    assert spec.status == "later"
    assert spec.host == ""


def test_wzdx_is_not_a_car() -> None:
    from arelis.earth.traffic import entities_from_wzdx

    pins = entities_from_wzdx(
        {
            "features": [
                {
                    "id": "wz-1",
                    "properties": {
                        "road_event_id": "ut-42",
                        "core_details": {
                            "event_type": "work-zone",
                            "road_names": ["I-15"],
                            "description": "Lane closure",
                        },
                    },
                    "geometry": {"type": "Point", "coordinates": [-111.9, 40.8]},
                }
            ]
        },
        prefix="ut-wzdx",
        source="Utah WZDx",
    )
    assert len(pins) == 1
    assert pins[0].id == "ut-wzdx:ut-42"
    assert pins[0].layer == "traffic"
    assert "not a vin" in pins[0].cite.lower()


def test_ndbc_buoy_is_not_a_hull() -> None:
    from arelis.earth.ndbc import entities_from_stations

    pins = entities_from_stations(
        {
            "station": [
                {"id": "41001", "lat": "34.7", "lon": "-72.7", "name": "East Hatteras"},
                {"id": "nogeo", "name": "Missing"},
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "ndbc:41001"
    assert pins[0].layer == "weather"
    assert "hull" in pins[0].cite.lower()


def test_usgs_volcano_is_not_every_vent() -> None:
    from arelis.earth.volcanoes import entities_from_geojson

    pins = entities_from_geojson(
        {
            "features": [
                {
                    "id": "kilauea",
                    "properties": {"volcanoName": "Kilauea", "alertLevel": "WATCH"},
                    "geometry": {"type": "Point", "coordinates": [-155.3, 19.4]},
                }
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "volc:kilauea"
    assert pins[0].layer == "sites"
    assert "unmonitored" in pins[0].cite.lower()


def test_gdacs_is_not_a_face() -> None:
    from arelis.earth.gdacs import entities_from_geojson

    pins = entities_from_geojson(
        {
            "features": [
                {
                    "properties": {
                        "eventid": 1001,
                        "name": "Test Storm",
                        "eventtype": "TC",
                        "alertlevel": "Orange",
                    },
                    "geometry": {"type": "Point", "coordinates": [120.0, 15.0]},
                }
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "gdacs:1001"
    assert pins[0].layer == "sites"
    assert "face" in pins[0].cite.lower()


def test_geonet_keeps_reported_events() -> None:
    from arelis.earth.geonet import entities_from_geojson

    pins = entities_from_geojson(
        {
            "features": [
                {
                    "properties": {
                        "publicID": "2026p001",
                        "magnitude": 3.4,
                        "locality": "Wellington",
                        "time": "2026-08-29T00:00:00Z",
                    },
                    "geometry": {"type": "Point", "coordinates": [174.8, -41.3, 12.0]},
                },
                {"properties": {"publicID": "nogeo"}, "geometry": {}},
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "geonet:2026p001"
    assert pins[0].layer == "quakes"
    assert pins[0].meta["depth_km"] == 12.0


def test_sigmet_uses_polygon_centroid() -> None:
    from arelis.earth.metar import entities_from_sigmet

    pins = entities_from_sigmet(
        {
            "features": [
                {
                    "properties": {"id": "SIG1", "hazard": "TURB", "firId": "KZNY"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [[-74.0, 40.0], [-72.0, 40.0], [-72.0, 42.0], [-74.0, 42.0], [-74.0, 40.0]]
                        ],
                    },
                }
            ]
        },
        prefix="sigmet",
    )
    assert len(pins) == 1
    assert pins[0].id == "sigmet:SIG1"
    assert pins[0].layer == "weather"
    assert pins[0].meta["lat"] == pytest.approx(40.8, abs=0.3)


def test_coops_gauge_is_not_a_hull() -> None:
    from arelis.earth.tides import entities_from_coops

    pins = entities_from_coops(
        {
            "stations": [
                {"id": "9414290", "name": "San Francisco", "lat": 37.8, "lng": -122.4},
                {"id": "nogeo", "name": "Missing"},
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "coops:9414290"
    assert pins[0].layer == "weather"
    assert "hull" in pins[0].cite.lower()


def test_ioc_gauge_is_not_altimetry() -> None:
    from arelis.earth.tides import entities_from_ioc

    pins = entities_from_ioc(
        [{"Code": "NEWL", "Lat": 50.1, "Lon": -5.5, "Location": "Newlyn"}]
    )
    assert len(pins) == 1
    assert pins[0].id == "ioc:newl"
    assert "altimetry" in pins[0].cite.lower()


def test_argo_sample_is_not_a_shell() -> None:
    from arelis.earth.argo import entities_from_table

    pins = entities_from_table(
        {
            "table": {
                "columnNames": ["latitude", "longitude", "platform_number"],
                "rows": [[20.0, -60.0, "6902746"], [None, None, "bad"]],
            }
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "argo:6902746"
    assert pins[0].layer == "sites"
    assert pins[0].meta.get("sample") is True
    assert "shell" in pins[0].cite.lower()


def test_ontario_cameras_drop_stills() -> None:
    from arelis.earth.cameras import entities_from_cars_cameras

    pins = entities_from_cars_cameras(
        [
            {
                "ID": "cam1",
                "Latitude": 43.7,
                "Longitude": -79.4,
                "Description": "Gardiner",
                "Url": "https://should-not-store.example/still.jpg",
            }
        ],
        prefix="on-cam",
        source="Ontario 511 cameras",
        cite="Position only. No still ingest.",
    )
    assert len(pins) == 1
    assert pins[0].id == "on-cam:cam1"
    blob = str(pins[0].meta) + pins[0].cite
    assert "still.jpg" not in blob


def test_tripcheck_uses_attributes() -> None:
    from arelis.earth.cameras import entities_from_tripcheck

    pins = entities_from_tripcheck(
        {
            "features": [
                {
                    "attributes": {
                        "CAMERAID": "I5-1",
                        "NAME": "I-5",
                        "LATITUDE": 45.5,
                        "LONGITUDE": -122.7,
                    }
                }
            ]
        }
    )
    assert len(pins) == 1
    assert pins[0].id == "odot:I5-1"
    assert pins[0].layer == "cameras"


def test_inspect_caption_names_source_and_freshness() -> None:
    from arelis.earth.entity import Entity
    from arelis.ui.earth_overlay import inspect_caption

    pos = lla_to_ecef(51.5, -0.12, 10_000.0)
    text = inspect_caption(
        Entity(
            id="icao:abc",
            cls="aircraft",
            layer="flights",
            label="BAW1",
            x=pos[0],
            y=pos[1],
            z=pos[2],
            vx=100.0,
            vy=0.0,
            vz=0.0,
            source="OpenSky Network",
            freshness="dead-reckoned",
            cite="OpenSky /api/states/all.",
        )
    )
    assert "BAW1" in text
    assert "dead-reckoned" in text
    assert "OpenSky Network" in text
    assert "m/s" in text


def test_osm_tile_math_is_stable() -> None:
    from arelis.earth.tiles import latlon_to_tile, tile_corners, zoom_for_disc

    assert zoom_for_disc(100.0) == 3
    z, x, y = latlon_to_tile(51.5, -0.12, 8)
    assert z == 8
    corners = tile_corners(z, x, y)
    assert len(corners) == 4
    lats = [c[0] for c in corners]
    assert min(lats) < 51.5 < max(lats)


def test_travel_to_earth_locks_the_eye(qt_app) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import SolarPanel

    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    panel.resize(640, 480)
    panel._travel_to("Earth")
    panel._finish_travel()
    assert get_earth() is not None
    assert get_earth().active
    assert panel._earth_cam is not None
    panel.reset_view()
    assert panel._earth_cam is None
    assert get_earth() is None or not get_earth().active
    panel.hide()
    set_system(None)

