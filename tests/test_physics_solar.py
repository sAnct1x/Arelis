"""SI solar-system lab: GM table, Kepler III, belt gaps, energy with REBOUND."""

from __future__ import annotations

import math

import pytest

from arelis.physics.constants import AU_M, GM_SUN
from arelis.physics.demo import sun_and_planet
from arelis.physics.engine import rebound_available


def test_newtonian_phi_and_well_are_not_gr() -> None:
    from arelis.physics.elements import (
        newtonian_phi,
        well_grid,
        well_inner_ring,
        well_line_indices,
        well_theta_count,
    )

    assert newtonian_phi(GM_SUN, AU_M) == pytest.approx(-GM_SUN / AU_M)
    r_e = 6_371_000.0
    span = 8.0 * r_e
    n = 16
    pts = well_grid(GM_SUN, r_e, extent=span, n=n)
    zs = [p[2] for p in pts]
    assert min(zs) == pytest.approx(-0.5 * r_e, rel=1e-4)
    assert max(math.hypot(p[0], p[1]) for p in pts) == pytest.approx(span, rel=0.02)
    assert not any(abs(p[0]) > 0.85 * span and abs(p[1]) > 0.85 * span for p in pts)
    n_th = well_theta_count(n)
    assert len(pts) == (n + 1) * n_th
    inner = well_inner_ring(n)
    lines = well_line_indices(n)
    assert inner >= 2
    assert len(lines) % 2 == 0
    assert max(lines) < len(pts)
    assert min(lines) >= inner * n_th


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


def test_go_realtime_locks_to_the_clock() -> None:
    if not rebound_available():
        pytest.skip("REBOUND is not installed")
    from arelis.physics.scene import SolarSystem

    system = SolarSystem.from_states(
        sun_and_planet(), tracers=0, epoch_jd=2_451_545.0
    )
    assert system.paused is True
    system.go_realtime(now_jd=2_451_545.0 + 1.0)
    assert system.paused is False
    assert system.wall_lock is True
    assert system.rate == pytest.approx(1.0)
    assert system.t == pytest.approx(86_400.0, rel=1e-6)
    system.set_rate(3_600.0)
    assert system.wall_lock is False


