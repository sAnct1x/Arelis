"""SI solar-system lab: GM table, Kepler III, belt gaps, energy with REBOUND."""

from __future__ import annotations

import math

import pytest

from arelis.physics.belt import KIRKWOOD_AU, generate_tracers, kirkwood_au
from arelis.physics.constants import AU_M, GM_EARTH, GM_JUPITER, GM_SUN
from arelis.physics.demo import sun_and_planet, two_body_period
from arelis.physics.elements import kepler_period, osculating
from arelis.physics.engine import rebound_available
from arelis.physics.hohmann import hohmann
from arelis.physics.lagrange import collinear_offsets, mass_parameter


def test_look_basis_is_orthonormal() -> None:
    from arelis.physics.camera import look_basis

    right, up, fwd = look_basis((0.0, 0.0, 0.0), (1.0, 0.2, 0.3))
    assert abs(sum(a * b for a, b in zip(fwd, right, strict=True))) < 1e-9
    assert abs(sum(a * b for a, b in zip(fwd, up, strict=True))) < 1e-9
    assert abs(sum(a * b for a, b in zip(right, up, strict=True))) < 1e-9
    assert math.sqrt(sum(x * x for x in fwd)) == pytest.approx(1.0)


def test_no_craft_chase_cam() -> None:
    import arelis.physics.camera as camera

    from arelis.physics.camera import FlyCamera
    from arelis.physics.scene import SolarSystem

    assert not hasattr(camera, "CRAFT_CHASE_DEFAULT")
    assert not hasattr(camera, "chase_eye")
    assert not hasattr(camera, "craft_axes")
    assert not hasattr(FlyCamera, "eye")
    assert not hasattr(SolarSystem, "enter_craft")
    assert not hasattr(SolarSystem, "craft_hud")


def test_gm_table_matches_published_de440() -> None:
    assert GM_SUN == pytest.approx(1.32712440041279419e20, rel=1e-12)
    assert GM_EARTH == pytest.approx(3.9860043543609598e14, rel=1e-9)
    assert GM_JUPITER == pytest.approx(1.266865349218008e17, rel=1e-9)


def test_circular_osculating_elements() -> None:
    a = AU_M
    v = math.sqrt(GM_SUN / a)
    el = osculating((a, 0.0, 0.0), (0.0, v, 0.0), GM_SUN)
    assert el is not None
    assert el.a == pytest.approx(a, rel=1e-6)
    assert el.e == pytest.approx(0.0, abs=1e-6)
    assert el.period_s == pytest.approx(kepler_period(a, GM_SUN), rel=1e-6)


def test_kepler_iii_two_body_period() -> None:
    a = AU_M
    t = two_body_period("Earth", a)
    # Sidereal year is ~365.256 d; Earth+Sun mu is slightly above GM_sun.
    assert t / 86400.0 == pytest.approx(365.256, rel=0.01)


def test_osculating_position_reconstructs_state() -> None:
    from arelis.physics.elements import position_at_true_anomaly

    a = AU_M
    v = math.sqrt(GM_SUN / a)
    r = (a, 0.0, 0.0)
    vel = (0.0, v, 0.0)
    el = osculating(r, vel, GM_SUN)
    assert el is not None
    px, py, pz = position_at_true_anomaly(el, el.true_anomaly)
    assert px == pytest.approx(a, rel=1e-6)
    assert py == pytest.approx(0.0, abs=1e3)
    assert pz == pytest.approx(0.0, abs=1e3)


def test_moon_osculating_is_about_earth() -> None:
    from arelis.physics.elements import position_at_true_anomaly

    a = 384_400_000.0
    v = math.sqrt(GM_EARTH / a)
    el = osculating((a, 0.0, 0.0), (0.0, v, 0.0), GM_EARTH)
    assert el is not None
    assert el.period_s / 86400.0 == pytest.approx(27.3, rel=0.05)
    px, _py, _pz = position_at_true_anomaly(el, el.true_anomaly)
    assert px == pytest.approx(a, rel=1e-5)


def test_earth_pole_is_latitude_90() -> None:
    from arelis.physics.attitude import earth_lonlat

    eps = math.radians(23.43927944444444)
    _lon, lat = earth_lonlat(0.0, math.sin(eps), math.cos(eps), 2_451_545.0)
    assert lat == pytest.approx(math.pi / 2.0, abs=1e-4)


def test_saturn_rings_use_iau_pole_and_cited_radii() -> None:
    from arelis.physics.attitude import saturn_pole_ecliptic, saturn_ring_axes
    from arelis.physics.constants import (
        BODY_BY_NAME,
        SATURN_CASSINI_INNER_M,
        SATURN_CASSINI_OUTER_M,
        SATURN_RING_INNER_M,
        SATURN_RING_OUTER_M,
    )

    px, py, pz = saturn_pole_ecliptic()
    assert abs(px * px + py * py + pz * pz - 1.0) < 1e-9
    assert pz > 0.85
    xx, yx, zx = saturn_ring_axes()
    assert zx == pytest.approx((px, py, pz), abs=1e-9)
    cx = xx[1] * yx[2] - xx[2] * yx[1]
    cy = xx[2] * yx[0] - xx[0] * yx[2]
    cz = xx[0] * yx[1] - xx[1] * yx[0]
    assert (cx, cy, cz) == pytest.approx((px, py, pz), abs=1e-6)
    r = BODY_BY_NAME["Saturn"].radius
    assert SATURN_RING_INNER_M > r
    assert SATURN_RING_INNER_M < SATURN_CASSINI_INNER_M < SATURN_CASSINI_OUTER_M
    assert SATURN_CASSINI_OUTER_M < SATURN_RING_OUTER_M


def test_mars_pole_is_latitude_90() -> None:
    import numpy as np

    from arelis.physics.attitude import body_frame_ecliptic, lonlat_from_frame

    frame = body_frame_ecliptic("Mars", 2_451_545.0)
    assert frame is not None
    _xx, _yx, zx = frame
    _lon, lat = lonlat_from_frame(
        np.asarray(zx[0]),
        np.asarray(zx[1]),
        np.asarray(zx[2]),
        frame,
    )
    assert float(lat) == pytest.approx(math.pi / 2.0, abs=1e-4)


def test_saturn_globe_north_matches_ring_pole() -> None:
    from arelis.physics.attitude import body_frame_ecliptic, saturn_pole_ecliptic

    frame = body_frame_ecliptic("Saturn", 2_451_545.0)
    assert frame is not None
    _xx, _yx, zx = frame
    assert zx == pytest.approx(saturn_pole_ecliptic(), abs=1e-9)


def test_iau_w_frames_are_right_handed() -> None:
    from arelis.physics.attitude import body_frame_ecliptic
    from arelis.physics.constants import IAU_W

    for name in IAU_W:
        frame = body_frame_ecliptic(name, 2_451_545.0)
        assert frame is not None, name
        xx, yx, zx = frame
        cx = xx[1] * yx[2] - xx[2] * yx[1]
        cy = xx[2] * yx[0] - xx[0] * yx[2]
        cz = xx[0] * yx[1] - xx[1] * yx[0]
        assert (cx, cy, cz) == pytest.approx(zx, abs=1e-6), name
        assert abs(xx[0] ** 2 + xx[1] ** 2 + xx[2] ** 2 - 1.0) < 1e-9


def test_iau_w_does_not_replace_earth_gmst() -> None:
    from arelis.physics.constants import IAU_W, PLANET_NAMES

    assert "Earth" not in IAU_W
    mapped = set(PLANET_NAMES) - {"Earth"}
    assert mapped <= set(IAU_W)


def test_camera_can_look_straight_up_and_over_the_pole() -> None:
    from arelis.physics.camera import FlyCamera

    cam = FlyCamera()
    cam.yaw = 0.0
    cam.pitch = 0.0
    cam.look(0.0, math.pi / 2.0)
    fx, fy, fz = cam.forward()
    assert fy == pytest.approx(1.0, abs=1e-6)
    right, up, fwd = cam.basis()
    assert abs(sum(a * b for a, b in zip(fwd, up, strict=True))) < 1e-8
    assert abs(sum(a * a for a in fwd) - 1.0) < 1e-9
    cam.look(0.0, 0.5)
    _fx, fy2, _fz = cam.forward()
    assert fy2 < 0.95


def test_camera_tumble_stays_orthonormal() -> None:
    from arelis.physics.camera import FlyCamera

    cam = FlyCamera()
    for _ in range(48):
        cam.look(0.17, 0.23)
        right, up, fwd = cam.basis()
        assert abs(sum(a * b for a, b in zip(fwd, up, strict=True))) < 1e-6
        assert abs(sum(a * b for a, b in zip(fwd, right, strict=True))) < 1e-6
        assert abs(sum(a * b for a, b in zip(right, up, strict=True))) < 1e-6


def test_camera_approach_cannot_land() -> None:
    from arelis.physics.camera import FlyCamera, look_basis
    from arelis.physics.constants import BODY_BY_NAME

    cam = FlyCamera()
    earth = BODY_BY_NAME["Earth"]
    cam.fit_approach(earth.radius)
    assert cam.min_distance == pytest.approx(earth.radius * 2.5)
    assert cam.distance == pytest.approx(earth.radius * 8.0)
    cam.approach(0.01)
    assert cam.distance >= earth.radius * 2.5
    fx, fy, fz = look_basis((0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    assert abs(fz[1] - 1.0) < 1e-9
    assert abs(fx[0] ** 2 + fx[1] ** 2 + fx[2] ** 2 - 1.0) < 1e-9
    assert abs(fy[0] ** 2 + fy[1] ** 2 + fy[2] ** 2 - 1.0) < 1e-9


def test_sun_overview_cannot_fill_the_window() -> None:
    from arelis.physics.camera import FlyCamera
    from arelis.physics.constants import AU_M, BODY_BY_NAME

    cam = FlyCamera()
    cam.fit_overview(BODY_BY_NAME["Sun"].radius)
    cam.approach(0.01)
    assert cam.distance >= 0.12 * AU_M


def test_overview_distance_frames_neptune() -> None:
    from arelis.physics.camera import SOLAR_SPAN_M, FlyCamera, overview_distance
    from arelis.physics.constants import AU_M

    dist = overview_distance(SOLAR_SPAN_M)
    assert dist > 80.0 * AU_M
    cam = FlyCamera()
    cam.frame_system(SOLAR_SPAN_M)
    cam.place_looking_at(0.0, 0.0, 0.0, cam.distance)
    assert cam.distance == pytest.approx(dist)
    assert cam.max_distance > dist
    proj = cam.project((SOLAR_SPAN_M, 0.0, 0.0), (0.0, 0.0, 0.0), 960, 720)
    assert proj is not None
    sx, sy, depth = proj
    assert 0.0 <= sx <= 960.0
    assert 0.0 <= sy <= 720.0
    assert depth > 0.0


def test_travel_to_stays_outside_the_body() -> None:
    from arelis.physics.camera import FlyCamera
    from arelis.physics.constants import AU_M, BODY_BY_NAME

    cam = FlyCamera()
    earth = BODY_BY_NAME["Earth"]
    cam.travel_to(AU_M, 0.0, 0.0, earth.radius)
    dist = math.hypot(cam.x - AU_M, cam.y, cam.z)
    assert dist >= earth.radius * 2.5
    assert dist == pytest.approx(earth.radius * 8.0, rel=0.05)
    assert cam.speed <= earth.radius * 8.0 * 0.35 + 1.0
    cam.travel_to(0.0, 0.0, 0.0, BODY_BY_NAME["Sun"].radius)
    dist = math.hypot(cam.x, cam.y, cam.z)
    assert dist >= 0.12 * AU_M


def test_travel_to_arrives_sunlit_and_stays_put() -> None:
    from arelis.physics.camera import FlyCamera
    from arelis.physics.constants import AU_M, BODY_BY_NAME

    earth = BODY_BY_NAME["Earth"]
    sun = (0.0, 0.0, 0.0)
    target = (AU_M, 0.0, 0.0)
    cam = FlyCamera()
    cam.yaw = 2.8
    cam.pitch = -0.4
    cam.travel_to(*target, earth.radius, sun=sun)
    dx, dy, dz = cam.x - target[0], cam.y - target[1], cam.z - target[2]
    sx, sy, sz = sun[0] - target[0], sun[1] - target[1], sun[2] - target[2]
    assert dx * sx + dy * sy + dz * sz > 0.0
    first = (cam.x, cam.y, cam.z, cam.yaw, cam.pitch)
    cam.travel_to(*target, earth.radius, sun=sun)
    assert cam.x == pytest.approx(first[0], abs=1.0)
    assert cam.y == pytest.approx(first[1], abs=1.0)
    assert cam.z == pytest.approx(first[2], abs=1.0)
    assert cam.yaw == pytest.approx(first[3], abs=1e-9)
    assert cam.pitch == pytest.approx(first[4], abs=1e-9)


def test_camera_speed_is_log_clamped() -> None:
    from arelis.physics.camera import SPEED_MAX, SPEED_MIN, FlyCamera

    cam = FlyCamera()
    cam.speed = 1.0
    cam.nudge_speed(0.001)
    assert cam.speed == pytest.approx(SPEED_MIN)
    cam.set_speed_u(1.0)
    assert cam.speed == pytest.approx(SPEED_MAX)
    cam.set_speed_u(0.0)
    assert cam.speed == pytest.approx(SPEED_MIN)
    cam.set_speed_u(0.5)
    assert SPEED_MIN < cam.speed < SPEED_MAX


def test_l4_l5_are_sixty_degrees_from_the_planet() -> None:
    from arelis.physics.lagrange import sun_planet_l_points

    r = (AU_M, 0.0, 0.0)
    v = (0.0, math.sqrt(GM_SUN / AU_M), 0.0)
    pts = sun_planet_l_points(r, 1.0, 3.0e-6, v)
    assert "L4" in pts and "L5" in pts

    def _ang(p: tuple[float, float, float]) -> float:
        return math.atan2(p[1], p[0])

    assert abs(_ang(pts["L4"]) - math.pi / 3.0) < 1e-6
    assert abs(_ang(pts["L5"]) + math.pi / 3.0) < 1e-6


def test_hohmann_earth_mars_is_vis_viva() -> None:
    burn = hohmann(AU_M, 1.523679 * AU_M, GM_SUN)
    assert burn.dv1 == pytest.approx(2945.0, rel=0.08)
    assert burn.dv2 == pytest.approx(2649.0, rel=0.08)
    assert burn.tof_s / 86400.0 == pytest.approx(259.0, rel=0.08)


def test_cr3bp_l1_is_between_primary_and_secondary() -> None:
    mu = mass_parameter(1.0, 3.0e-6)
    x1, x2, x3 = collinear_offsets(mu)
    assert 0.0 < x1 < 1.0
    assert x2 > 1.0
    assert x3 < 0.0


def test_belt_tracers_miss_kirkwood_gaps() -> None:
    tracers = generate_tracers(400, seed=7)
    assert len(tracers) == 400
    assert tracers[0].label.startswith("belt particle")
    gaps = kirkwood_au()
    assert gaps == KIRKWOOD_AU
    for tr in tracers:
        a_au = tr.a / AU_M
        for gap in gaps:
            assert abs(a_au - gap) >= 0.045


@pytest.mark.skipif(not rebound_available(), reason="pip install -e \".[astro]\"")
def test_circular_catalog_demo_has_planets_and_moons() -> None:
    from arelis.physics.demo import circular_system
    from arelis.physics.scene import SolarSystem

    states = circular_system()
    assert "Sun" in states
    assert "Neptune" in states
    assert "Moon" in states
    assert "Titan" in states
    system = SolarSystem.from_states(states, tracers=0)
    earth = system.nbody.find("Earth")
    moon = system.nbody.find("Moon")
    assert earth is not None and moon is not None
    dist = math.hypot(moon.x - earth.x, moon.y - earth.y, moon.z - earth.z)
    assert dist == pytest.approx(384_399_000.0, rel=0.05)
    tagged = SolarSystem.from_states(
        states,
        tracers=0,
        epoch_tdb="pytest fixture, not Horizons",
    )
    assert "not Horizons" in tagged.ic_caption()
    assert "Horizons IC" not in tagged.ic_caption()
    two = SolarSystem.from_states(sun_and_planet(), tracers=0)
    assert "not Horizons" in two.ic_caption()


@pytest.mark.skipif(not rebound_available(), reason="pip install -e \".[astro]\"")
def test_ias15_two_body_energy_and_period() -> None:
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem

    system = SolarSystem.from_states(sun_and_planet(), tracers=0)
    e0 = system.nbody.energy()
    period = two_body_period("Earth", AU_M)
    system.nbody.integrate_to(period)
    e1 = system.nbody.energy()
    assert abs(e1 - e0) / abs(e0) < 1e-8
    earth = system.nbody.find("Earth")
    sun = system.nbody.find("Sun")
    assert earth is not None and sun is not None
    dx, dy, dz = earth.x - sun.x, earth.y - sun.y, earth.z - sun.z
    r = math.sqrt(dx * dx + dy * dy + dz * dz)
    assert r == pytest.approx(AU_M, rel=0.02)
    set_system(None)


@pytest.mark.skipif(not rebound_available(), reason="pip install -e \".[astro]\"")
def test_probe_delta_v_on_massless_is_not_counterfactual() -> None:
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem

    system = SolarSystem.from_states(sun_and_planet(), tracers=0)
    label = system.spawn_probe()
    assert system.counterfactual  # extra particle is not a Horizons IC
    system.counterfactual = False  # isolate: massless Δv must not raise the flag
    probe = system.nbody.find(label)
    assert probe is not None
    assert probe.mass == 0.0
    vx0 = probe.vx
    e0 = system.nbody.energy()
    assert system.nbody.apply_delta_v(label, (10.0, 0.0, 0.0))
    probe = system.nbody.find(label)
    assert probe is not None
    assert probe.vx == pytest.approx(vx0 + 10.0)
    assert not system.counterfactual
    e1 = system.nbody.energy()
    assert abs(e1 - e0) / abs(e0) < 1e-10
    set_system(None)


@pytest.mark.skipif(not rebound_available(), reason="pip install -e \".[astro]\"")
def test_spawn_probe_and_l4_are_massless() -> None:
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem

    system = SolarSystem.from_states(sun_and_planet(), tracers=0)
    e0 = system.nbody.energy()
    probe = system.spawn_probe()
    body = system.nbody.find(probe)
    assert body is not None
    assert body.mass == 0.0
    assert body.kind == "probe"
    l4 = system.spawn_lagrange("L4")
    marker = system.nbody.find(l4)
    assert marker is not None
    assert marker.mass == 0.0
    assert marker.kind == "lagrange"
    belt = system.spawn_tracer()
    tr = system.nbody.find(belt)
    assert tr is not None
    assert tr.tracer
    e1 = system.nbody.energy()
    assert abs(e1 - e0) / abs(e0) < 1e-10
    set_system(None)


def test_maps_without_files_do_not_invent_detail() -> None:
    from arelis.physics.maps import describe

    info = describe("Earth")
    if info.path is None:
        assert "none" in info.source.lower() or "Visible Earth" in info.source
    info_u = describe("Bennu")
    assert info_u.path is None
    assert "no public map" in info_u.source


def test_sun_track_present_and_subgiant() -> None:
    from arelis.physics.evolution import sample

    now = sample(0.0)
    assert now.r_sun == pytest.approx(1.0)
    assert now.m_sun == pytest.approx(1.0)
    assert now.phase == "main sequence"
    later = sample(5.4)
    assert later.r_sun > 1.0
    assert later.phase == "subgiant"
    birth = sample(-4.57)
    assert birth.phase == "ZAMS / formation era"
    assert birth.l_sun < 1.0
    assert birth.r_sun < 1.0


@pytest.mark.skipif(not rebound_available(), reason="pip install -e \".[astro]\"")
def test_future_gyr_scales_a_and_restores() -> None:
    from arelis.physics.evolution import sample
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem

    system = SolarSystem.from_states(sun_and_planet(), tracers=0)
    sun = system.nbody.find("Sun")
    earth = system.nbody.find("Earth")
    assert sun is not None and earth is not None
    r0 = math.hypot(earth.x - sun.x, earth.y - sun.y, earth.z - sun.z)
    radius0 = sun.radius
    track = sample(5.4)
    system.set_future_gyr(5.4)
    sun = system.nbody.find("Sun")
    earth = system.nbody.find("Earth")
    assert sun is not None and earth is not None
    r1 = math.hypot(earth.x - sun.x, earth.y - sun.y, earth.z - sun.z)
    assert r1 == pytest.approx(r0 / track.m_sun, rel=1e-6)
    assert sun.radius == pytest.approx(radius0 * track.r_sun, rel=1e-6)
    assert system.counterfactual is True
    system.set_future_gyr(0.0)
    sun = system.nbody.find("Sun")
    earth = system.nbody.find("Earth")
    assert sun is not None and earth is not None
    r2 = math.hypot(earth.x - sun.x, earth.y - sun.y, earth.z - sun.z)
    assert r2 == pytest.approx(r0, rel=1e-6)
    assert sun.radius == pytest.approx(radius0, rel=1e-6)
    hud = system.hud_for_lock()
    assert float(hud.get("future_gyr") or 0) == pytest.approx(0.0)
    set_system(None)


@pytest.mark.skipif(not rebound_available(), reason="pip install -e \".[astro]\"")
def test_prograde_impulse_is_counterfactual() -> None:
    from arelis.physics.runtime import set_system
    from arelis.physics.scene import SolarSystem

    system = SolarSystem.from_states(sun_and_planet(), tracers=0)
    earth = system.nbody.find("Earth")
    assert earth is not None
    speed0 = math.hypot(earth.vx, earth.vy, earth.vz)
    energy0 = system.energy0
    assert system.prograde_impulse("Earth", 100.0)
    assert system.counterfactual
    assert system.ic_caption() == "COUNTERFACTUAL"
    earth = system.nbody.find("Earth")
    assert earth is not None
    speed1 = math.hypot(earth.vx, earth.vy, earth.vz)
    assert speed1 == pytest.approx(speed0 + 100.0, rel=1e-9)
    assert system.energy0 != energy0
    assert not system.prograde_impulse("missing", 100.0)
    set_system(None)
