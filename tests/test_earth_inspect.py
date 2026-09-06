"""Native Earth inspect: east on the right, city band reachable, honest field."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arelis.earth.frames import MEAN_R, lla_to_ecef, nadir_cam
from arelis.earth.lod import _NEAR_ALT_M, _SPACE_ALT_M, band_from_view
from arelis.earth.polish_score import CHECKS
from arelis.earth.tiles import _GIBS_MAX_ZOOM, zoom_for_disc, zoom_for_ground
from arelis.physics.camera import look_basis, project_with_basis
from arelis.physics.collision import EARTH_INSPECT_MIN_AGL_M, inspect_stop_m, stop_radius_m
from arelis.ui.panels.solar_earth import (
    CITY_LOOK_ALT_M,
    earth_goto_alt_m,
    earth_zone_speed,
    earth_zoom_factor,
)
from arelis.ui.panels.solar_paint import look_field_m


def test_nadir_look_puts_east_right_of_west() -> None:
    """Atlas convention: looking down, north up, east is screen-right."""
    pose = nadir_cam(39.0, -98.0, 1_200_000.0)
    right, up, fwd = look_basis(pose.eye, pose.look, pose.up)
    cal = lla_to_ecef(36.0, -119.5, 0.0)
    fla = lla_to_ecef(27.5, -81.5, 0.0)
    cal_s = project_with_basis(cal, pose.eye, (right, up, fwd), 800, 600)
    fla_s = project_with_basis(fla, pose.eye, (right, up, fwd), 800, 600)
    assert cal_s is not None and fla_s is not None
    assert fla_s[0] > cal_s[0]


def test_city_goto_opens_city_band() -> None:
    """Take me to Tokyo used to park at 80 km — near band, photoreal black."""
    alt = earth_goto_alt_m("city")
    assert alt == CITY_LOOK_ALT_M
    assert alt < _NEAR_ALT_M
    assert band_from_view(alt_m=alt, px_r=800.0, locked=True) == "city"
    assert earth_goto_alt_m("home") == CITY_LOOK_ALT_M
    assert earth_goto_alt_m("address") == 350.0
    assert earth_goto_alt_m("address") < _NEAR_ALT_M
    assert band_from_view(
        alt_m=earth_goto_alt_m("address"), px_r=800.0, locked=True
    ) == "city"
    assert band_from_view(
        alt_m=earth_goto_alt_m("continent"), px_r=80.0, locked=True
    ) == "space"


def test_earth_inspect_floor_opens_city_band() -> None:
    karman, _ = stop_radius_m("Earth")
    inspect, _ = inspect_stop_m("Earth")
    assert inspect < karman
    assert EARTH_INSPECT_MIN_AGL_M < _NEAR_ALT_M
    assert band_from_view(
        alt_m=EARTH_INSPECT_MIN_AGL_M, px_r=800.0, locked=True
    ) == "city"


def test_earth_wasd_is_walkable_near_the_ground() -> None:
    slow = earth_zone_speed(MEAN_R + 2_000.0, MEAN_R, 3.0e7)
    cruise = earth_zone_speed(MEAN_R + 80_000.0, MEAN_R, 3.0e7)
    assert slow < 200.0
    assert cruise < 8_000.0
    assert cruise > slow


def test_earth_wheel_falls_faster_than_a_solar_cruise() -> None:
    inward = earth_zoom_factor(120.0)
    assert 0.70 <= inward <= 0.82


def test_look_basis_right_is_east_for_nadir() -> None:
    eye = lla_to_ecef(0.0, 0.0, 1_000_000.0)
    look = lla_to_ecef(0.0, 0.0, 0.0)
    north = lla_to_ecef(0.25, 0.0, 1_000_000.0)
    up = (north[0] - eye[0], north[1] - eye[1], north[2] - eye[2])
    right, _up, _fwd = look_basis(eye, look, up)
    # Greenwich equator: ECEF +Y is east.
    assert right[1] > 0.7
    assert abs(right[0]) < 0.25


def test_scorecard_lists_the_audit_ids() -> None:
    ids = {c.id for c in CHECKS}
    for key in (
        "east-right-nadir",
        "clock-honest",
        "band-from-alt-when-locked",
        "inspect-reaches-city",
        "earth-uses-gpu-cesium",
        "no-disable-gpu-without-share",
        "one-planet-painter",
        "live-off-fetches-nothing",
        "leave-destroys-webengine",
        "wheel-is-zoom-on-earth",
        "field-is-distance-to-earth",
        "wasd-walk-near-ground",
        "streets-chip-shows-streets",
    ):
        assert key in ids


def test_locked_eye_bands_from_altitude_not_disc() -> None:
    assert (
        band_from_view(alt_m=_SPACE_ALT_M + 1.0, px_r=900.0, locked=True) == "space"
    )
    assert (
        band_from_view(alt_m=EARTH_INSPECT_MIN_AGL_M, px_r=40.0, locked=True)
        == "city"
    )


def test_field_line_is_distance_to_earth() -> None:
    earth = SimpleNamespace(x=0.0, y=0.0, z=0.0, radius=MEAN_R)
    panel = SimpleNamespace(
        cam=SimpleNamespace(distance=4.0e11, x=MEAN_R + 80_000.0, y=0.0, z=0.0),
        _inspect=None,
        _earth_zone_on=lambda: True,
        _earth_cam=None,
    )
    sys = SimpleNamespace(
        nbody=SimpleNamespace(find=lambda name: earth if name == "Earth" else None)
    )
    field = look_field_m(panel, sys)
    leftover = 4.0e11 * 0.36
    assert field < leftover / 10.0
    assert field < 50_000.0
    panel._earth_cam = SimpleNamespace(eye=lla_to_ecef(0.0, 0.0, 2_000.0))
    locked = look_field_m(panel, sys)
    assert locked < 2_000.0


def test_gibs_zoom_stays_capped() -> None:
    from pathlib import Path

    assert _GIBS_MAX_ZOOM == 8
    assert zoom_for_ground(900.0, "city") <= 8
    assert zoom_for_disc(900.0, "city") == 19
    overlay = (
        Path(__file__).resolve().parents[1]
        / "arelis"
        / "ui"
        / "earth_overlay.py"
    ).read_text(encoding="utf-8")
    assert "radius = 2 if view.band in {\"near\", \"city\"} else 1" in overlay


def test_clock_honest_when_not_wall_locked() -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem
    from arelis.ui.panels.solar_hud import hud_status_lines

    if not rebound_available():
        return
    system = SolarSystem.from_states(sun_and_planet(), tracers=0)
    system.wall_lock = False
    system.rate = 1.0
    system.paused = False
    panel = SimpleNamespace(
        _look_field_m=lambda _s: 1.0e7,
        _maps_alert=lambda: "",
        _space_live=lambda: True,
        _gl=None,
    )
    lines = hud_status_lines(panel, system)
    blob = " ".join(lines)
    assert "realtime" not in blob
    assert "1× at epoch" in blob or "locked to now" in blob


def test_live_off_does_not_refresh() -> None:
    from arelis.earth.runtime import EarthRuntime

    earth = EarthRuntime()
    earth.active = True
    earth.live = False
    earth._maybe_refresh_live(1.0)
    assert earth._live_busy is False


def test_enter_snapshots_then_coasts(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth.runtime import EarthRuntime

    kicks: list[bool] = []

    def fake_kick(self, *, refetch: bool = False) -> None:
        kicks.append(refetch)

    monkeypatch.setattr(EarthRuntime, "_kick_snapshot", fake_kick)
    monkeypatch.setattr(EarthRuntime, "_lock_wall_clock", lambda self: None)
    earth = EarthRuntime()
    note = earth.enter(unix=1.0)
    assert earth.live is False
    assert kicks == [False]
    assert "simulated" in note
    earth.enter(unix=2.0)
    assert kicks[-1] is True


def test_coast_fetches_a_new_band_once() -> None:
    from arelis.earth.lod import EarthView
    from arelis.earth.runtime import EarthRuntime

    earth = EarthRuntime()
    earth.active = True
    earth.live = False
    earth.layers["flights"] = True
    earth.last_view = EarthView("approach", alt_m=800_000.0, lat=0.0, lon=0.0)
    due = earth._coast_due(earth.last_view)
    assert "opensky" in due
    earth.last_fetch_unix["opensky"] = 1.0
    later = earth._coast_due(earth.last_view)
    assert "opensky" not in later


def test_ground_detail_waits_for_altitude() -> None:
    from arelis.earth.lod import (
        BUILDING_ALT_M,
        ROAD_ALT_M,
        ground_buildings_on,
        ground_streets_on,
    )

    assert ground_streets_on(band="near", alt_m=2_000.0) is False
    assert ground_streets_on(band="city", alt_m=ROAD_ALT_M + 1.0) is False
    assert ground_streets_on(band="city", alt_m=ROAD_ALT_M) is True
    assert ground_buildings_on(band="city", alt_m=BUILDING_ALT_M + 1.0) is False
    assert ground_buildings_on(band="city", alt_m=BUILDING_ALT_M) is True


def test_streets_chip_is_osm_not_gibs() -> None:
    from arelis.earth.tiles import GIBS_BLUE, OSM_TILE
    from arelis.ui.earth_overlay import earth_chip_items

    assert "openstreetmap.org" in OSM_TILE
    assert "gibs.earthdata.nasa.gov" in GIBS_BLUE
    assert OSM_TILE != GIBS_BLUE
    assert ("tiles", "Streets") in earth_chip_items("city")
    assert ("tiles", "Streets") not in earth_chip_items("near")
    assert ("tiles", "Streets") not in earth_chip_items("approach")


def test_earth_cam_is_ecef_so_land_stays_put() -> None:
    from arelis.earth.frames import EarthCam, ecef_to_geodetic

    pose = nadir_cam(39.0, -98.0, 80_000.0)
    assert isinstance(pose, EarthCam)
    lat, lon, _alt = ecef_to_geodetic(*pose.eye)
    assert abs(lat - 39.0) < 0.05
    assert abs(lon + 98.0) < 0.05
    later = nadir_cam(39.0, -98.0, 80_000.0)
    assert pose.eye == later.eye


def test_kepler_bootstrap_is_not_called_realtime() -> None:
    from arelis.physics.demo import sun_and_planet
    from arelis.physics.engine import rebound_available
    from arelis.physics.scene import SolarSystem

    if not rebound_available():
        return
    system = SolarSystem.from_states(sun_and_planet(), tracers=0)
    system.go_realtime()
    assert system.wall_lock is False
    assert system.rate == 1.0


def test_one_planet_painter_skips_qt_tiles_when_cesium_live() -> None:
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "arelis"
        / "ui"
        / "panels"
        / "solar_paint.py"
    ).read_text(encoding="utf-8")
    live = src.split("if getattr(panel, \"_earth_globe_live\"", 1)[1]
    branch, rest = live.split("else:", 1)
    assert "sync_earth_view" in branch
    assert "paint_earth" not in branch
    assert "paint_earth" in rest.split("panel._paint_hud", 1)[0]


def test_solar_idle_skips_fbo_readback() -> None:
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1] / "arelis" / "ui" / "solar_gl.py"
    ).read_text(encoding="utf-8")
    assert "if key == self._frame_key and self._frame is not None" in src
