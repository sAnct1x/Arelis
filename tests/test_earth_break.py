"""Try to break Earth / Reality contracts. These go red when the lie returns."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtGui import QPainter, QPixmap

from arelis.earth.entity import Entity
from arelis.earth.frames import lla_to_ecef
from arelis.earth.runtime import EarthRuntime, get_earth, set_earth
from arelis.tools.earth_tool import EarthTool


def _quake(eid: str, lat: float, lon: float) -> Entity:
    x, y, z = lla_to_ecef(lat, lon, 0.0)
    return Entity(
        id=eid,
        cls="quake",
        layer="quakes",
        label="last shock",
        x=x,
        y=y,
        z=z,
        freshness="delayed",
        source="USGS all_day",
    )


def test_empty_usgs_clears_last_quakes() -> None:
    from arelis.earth.live import _apply_live
    from arelis.earth.store import EntityStore

    store = EntityStore()
    store.upsert(_quake("usgs:old", 35.0, 139.0))
    _apply_live(store, {"usgs": []}, {"usgs"}, view=None)
    assert store.in_layer("quakes") == ()


def test_usgs_timeout_keeps_sim_quakes() -> None:
    from arelis.earth.live import _apply_live
    from arelis.earth.store import EntityStore

    store = EntityStore()
    store.upsert(_quake("usgs:sim", 35.0, 139.0))
    _apply_live(store, {"usgs": None}, {"usgs"}, view=None)
    assert store.get("usgs:sim") is not None


def test_usgs_fail_is_none_empty_features_is_quiet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import arelis.earth.live as live

    monkeypatch.setattr(live, "_get_json", lambda *_a, **_k: None)
    assert live.fetch_usgs() is None
    monkeypatch.setattr(live, "_get_json", lambda *_a, **_k: {"features": []})
    assert live.fetch_usgs() == []


def test_leave_twice_is_already_solar() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    first = earth.leave()
    second = earth.leave()
    assert earth.active is False
    assert "solar" in second.lower() or "already" in second.lower()
    assert first != "" or second != ""


def test_enter_leave_enter_is_active() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth.leave()
    earth.enter(unix=2.0)
    assert earth.active is True
    earth.leave()


def test_double_unlock_does_not_raise() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth.unlock()
    earth.unlock()
    assert earth.ride_id == ""
    assert earth.track_id == ""
    earth.leave()


@pytest.mark.asyncio
async def test_earth_tool_leave_when_solar_is_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: True)
    set_earth(EarthRuntime())
    tool = EarthTool()
    left = await tool.run(action="leave")
    assert left.ok
    again = await tool.run(action="leave")
    assert again.ok
    set_earth(None)


@pytest.mark.asyncio
async def test_earth_tool_layer_unknown_is_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: True)
    set_earth(EarthRuntime())
    tool = EarthTool()
    await tool.run(action="enter")
    miss = await tool.run(action="layer", layer="buildings")
    assert not miss.ok
    set_earth(None)


def test_software_view_flap_does_not_leave_earth(qt_app) -> None:
    """paint_overlay used to reset_view on _view_id mismatch and kick you out."""
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import SolarPanel
    from arelis.ui.panels.solar_paint import paint_overlay

    if not rebound_available():
        pytest.skip("needs REBOUND demo system")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    panel._view_id = 0
    pix = QPixmap(320, 240)
    painter = QPainter(pix)
    try:
        paint_overlay(panel, painter, software=True)
    finally:
        painter.end()
    zone = get_earth()
    assert zone is not None and zone.active is True
    panel._leave_earth_zone()
    set_earth(None)
    set_system(None)


def test_hide_during_globe_mount_does_not_leave_earth(qt_app) -> None:
    from PySide6.QtGui import QHideEvent

    from arelis.ui.panels.solar import SolarPanel

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    panel._globe_mounting = True
    panel.hideEvent(QHideEvent())
    zone = get_earth()
    assert zone is not None and zone.active is True
    panel._globe_mounting = False
    panel._leave_earth_zone()
    set_earth(None)


def test_hide_event_leaves_earth(qt_app) -> None:
    from PySide6.QtGui import QHideEvent

    from arelis.ui.panels.solar import SolarPanel

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    panel.hideEvent(QHideEvent())
    zone = get_earth()
    assert zone is None or zone.active is False
    set_earth(None)


def test_inspect_mercury_leaves_then_earth_can_reenter(qt_app) -> None:
    from arelis.ui.panels.solar import SolarPanel

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    panel._set_inspect("Mercury")
    zone = get_earth()
    assert zone is None or zone.active is False
    panel._enter_earth_zone()
    zone = get_earth()
    assert zone is not None and zone.active is True
    panel._leave_earth_zone()
    set_earth(None)


def test_enter_without_travel_snaps_native_eye(qt_app) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import SolarPanel
    from arelis.ui.panels.solar_earth import SPACE_ENTER_ALT_M

    if not rebound_available():
        pytest.skip("needs REBOUND demo system")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    panel = SolarPanel()
    from arelis.physics.runtime import get_system

    system = get_system()
    if system is not None:
        panel._view_id = id(system)
    panel._enter_earth_zone()
    zone = get_earth()
    assert zone is not None and zone.active
    cam = panel._earth_cam
    assert cam is not None
    from arelis.earth.frames import ecef_to_geodetic

    _lat, _lon, alt = ecef_to_geodetic(*cam.eye)
    assert alt > SPACE_ENTER_ALT_M * 0.4
    panel._leave_earth_zone()
    set_earth(None)
    set_system(None)


def test_find_null_island_query_does_not_goto() -> None:
    from arelis.ui.earth_find import apply_goto

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SimpleNamespace(
        _earth_find_on=True,
        _earth_find_q="Null Island",
        _earth_find_hits=[],
        _earth_find_ix=0,
        _earth_find_box=None,
        _earth_say=None,
        update=lambda: None,
        _select_earth_place=lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not hop")),
    )
    assert apply_goto(panel) is False
    earth.leave()
    set_earth(None)


def test_leave_clears_pending_enter(qt_app) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import get_system, set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import SolarPanel

    if not rebound_available():
        pytest.skip("needs REBOUND demo system")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    system = get_system()
    assert system is not None
    system.pending_enter_earth = True
    panel._leave_earth_zone()
    assert system.pending_enter_earth is False
    panel._tick()
    zone = get_earth()
    assert zone is None or zone.active is False
    set_earth(None)
    set_system(None)


def test_travel_to_sun_leaves_earth_before_warp(qt_app) -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar import SolarPanel

    if not rebound_available():
        pytest.skip("needs REBOUND demo system")
    set_system(SolarSystem.from_states(sun_and_planet(), tracers=0))
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    panel._enter_earth_zone()
    panel._travel_to("Sun")
    zone = get_earth()
    assert zone is None or zone.active is False
    assert panel._warp is not None
    assert panel._warp.name == "Sun"
    set_earth(None)
    set_system(None)


def test_reset_after_paint_keeps_earth(qt_app) -> None:
    from arelis.ui.panels.solar import SolarPanel

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    panel._reset_pending = True
    panel._reset_after_paint()
    zone = get_earth()
    assert zone is not None and zone.active is True
    panel._leave_earth_zone()
    set_earth(None)


def test_opensky_empty_does_not_wipe_military() -> None:
    from arelis.earth.live import _apply_live
    from arelis.earth.store import EntityStore

    x, y, z = lla_to_ecef(51.5, -0.12, 10_000.0)
    store = EntityStore()
    store.upsert(
        Entity(
            id="icao:ae0001",
            cls="aircraft",
            layer="military",
            label="RCH1",
            x=x,
            y=y,
            z=z,
            freshness="delayed",
            source="adsb.lol",
        )
    )
    _apply_live(store, {"opensky": []}, {"opensky"}, view=None)
    assert store.get("icao:ae0001") is not None


def test_ais_no_key_ohio_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth import ais as ais_mod
    from arelis.earth.lod import LookBBox

    monkeypatch.setattr(ais_mod, "aisstream_key", lambda path=None: "")

    def _boom(*_a, **_k):
        raise AssertionError("Baltic AIS is not a Columbus feed")

    monkeypatch.setattr(ais_mod, "fetch_digitraffic", _boom)
    monkeypatch.setattr(ais_mod, "fetch_barentswatch", _boom)
    ships = ais_mod.fetch_ais(bbox=LookBBox(38.8, -84.2, 41.2, -81.8))
    assert ships is None


def test_miss_does_not_stamp_last_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "arelis.earth.live.merge_live",
        lambda *_a, **_k: {"cameras": None},
    )
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth._live_queue.append(("cameras",))
    earth._merge_live()
    assert "cameras" not in earth.last_fetch_unix
    earth.leave()


def test_heard_empty_does_stamp_last_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "arelis.earth.live.merge_live",
        lambda *_a, **_k: {"cameras": []},
    )
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth._live_queue.append(("cameras",))
    earth._merge_live()
    assert "cameras" in earth.last_fetch_unix
    earth.leave()


@pytest.mark.asyncio
async def test_earth_tool_goto_drops_null_island(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from arelis.earth.gazetteer import GotoHit

    monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: True)
    monkeypatch.setattr(
        "arelis.earth.gazetteer.resolve_place",
        lambda *_a, **_k: GotoHit(kind="city", name="Null Island", lat=0.0, lon=0.0),
    )
    set_earth(EarthRuntime())
    tool = EarthTool()
    got = await tool.run(action="goto", query="zzzz-not-a-city")
    assert not got.ok
    set_earth(None)


def test_firms_is_keyed_in_earth_tool_description() -> None:
    assert "FIRMS if keyed" in EarthTool.description
    assert "Open-Meteo, FIRMS," not in EarthTool.description


def test_look_space_uses_enter_alt() -> None:
    import inspect

    from arelis.ui import world_host
    from arelis.ui.panels.solar_earth import SPACE_ENTER_ALT_M

    src = inspect.getsource(world_host)
    assert "SPACE_ENTER_ALT_M" in src
    assert SPACE_ENTER_ALT_M == 20_000_000.0


def test_earth_say_hidden_while_riding(qt_app) -> None:
    from PySide6.QtGui import QPainter, QPixmap

    from arelis.ui.earth_chrome import paint_earth_say, set_earth_say
    from arelis.ui.panels.solar import SolarPanel

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
    earth.ride("norad:25544")
    set_earth(earth)
    panel = SolarPanel()
    panel.resize(640, 400)
    set_earth_say(panel, "No place named zzzz-not-a-city.", "Not a hop to 0, 0.")
    pix = QPixmap(640, 400)
    pix.fill()
    painter = QPainter(pix)
    try:
        box = paint_earth_say(panel, painter)
    finally:
        painter.end()
    assert box.isEmpty()
    panel._leave_earth_zone()
    set_earth(None)


def test_empty_launches_clears_ll2_keeps_bundled_site() -> None:
    from arelis.earth.live import _apply_live
    from arelis.earth.store import EntityStore

    store = EntityStore()
    x, y, z = lla_to_ecef(28.6, -80.6, 0.0)
    store.upsert(
        Entity(
            id="ll2:old-pad",
            cls="site",
            layer="sites",
            label="old pad",
            x=x,
            y=y,
            z=z,
            source="Launch Library 2",
        )
    )
    hx, hy, hz = lla_to_ecef(36.02, -114.74, 0.0)
    store.upsert(
        Entity(
            id="site:hoover",
            cls="site",
            layer="sites",
            label="Hoover Dam",
            x=hx,
            y=hy,
            z=hz,
            source="bundled public coordinates",
        )
    )
    _apply_live(store, {"launches": []}, {"launches"}, view=None)
    assert store.get("ll2:old-pad") is None
    assert store.get("site:hoover") is not None


def test_launches_timeout_keeps_pad() -> None:
    from arelis.earth.live import _apply_live
    from arelis.earth.store import EntityStore

    store = EntityStore()
    x, y, z = lla_to_ecef(28.6, -80.6, 0.0)
    store.upsert(
        Entity(
            id="ll2:sim-pad",
            cls="site",
            layer="sites",
            label="sim pad",
            x=x,
            y=y,
            z=z,
            source="Launch Library 2",
        )
    )
    _apply_live(store, {"launches": None}, {"launches"}, view=None)
    assert store.get("ll2:sim-pad") is not None


def test_fires_without_key_is_a_named_hole(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth.copy import layer_hole_line

    monkeypatch.setattr("arelis.earth.firms.firms_key", lambda path=None: "")
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth.live = True
    earth.layers["fires"] = True
    line = layer_hole_line(earth) or ""
    assert "MAP_KEY" in line
    notes = " ".join(earth.coverage_notes())
    assert "MAP_KEY" in notes


def test_fly_camera_pushes_look_when_globe_is_live(qt_app) -> None:
    from PySide6.QtCore import Qt

    from arelis.ui.panels.solar import SolarPanel

    looks: list[tuple[float, float]] = []
    nudges: list[tuple[float, float, float]] = []

    class Host:
        failed = False

        def isVisible(self) -> bool:
            return True

        def push_look(self, yaw: float, pitch: float) -> None:
            looks.append((yaw, pitch))

        def push_nudge(self, fwd: float, right: float, up: float) -> None:
            nudges.append((fwd, right, up))

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    panel = SolarPanel()
    panel._globe_host = Host()
    panel._keys.add(int(Qt.Key.Key_Left))
    panel._fly_camera(0.05)
    assert looks
    panel._leave_earth_zone()
    set_earth(None)
