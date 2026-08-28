"""Catalog stop-spheres. No rebound, no death.

clip_relative / first_hit_on_segment are the math, not a live vehicle.
"""

from __future__ import annotations

from arelis.physics.clocks import RATE_MAX, RATE_MIN, clamp_rate, jd_iso
from arelis.physics.collision import (
    clip_relative,
    first_hit_on_segment,
    stop_radius_m,
)


def test_earth_stop_is_karman() -> None:
    r, cite = stop_radius_m("Earth")
    assert r == 6_371_000.0 + 100_000.0
    assert "Karman" in cite


def test_jupiter_stop_is_one_bar() -> None:
    r, cite = stop_radius_m("Jupiter")
    assert r == 69_911_000.0
    assert "1-bar" in cite


def test_moon_is_mean_radius() -> None:
    r, cite = stop_radius_m("Moon")
    assert r == 1_737_400.0
    assert "Airless" in cite or "mean" in cite.lower()


def test_clip_holds_outside_and_kills_inward() -> None:
    # Host at origin, test particle inside the sphere on +x, diving in.
    nx, ny, _nz, nvx, nvy, _nvz, hit = clip_relative(
        50.0,
        0.0,
        0.0,
        -10.0,
        3.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        100.0,
        pad=1.0,
    )
    assert hit
    assert nx == 101.0
    assert ny == 0.0
    assert nvx == 0.0
    assert nvy == 3.0


def test_clip_leaves_outward_speed() -> None:
    _nx, _ny, _nz, nvx, _nvy, _nvz, hit = clip_relative(
        50.0,
        0.0,
        0.0,
        8.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        100.0,
        pad=1.0,
    )
    assert hit
    assert nvx == 8.0


def test_segment_catches_a_tunnel() -> None:
    hit = first_hit_on_segment(
        -200.0,
        0.0,
        0.0,
        200.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        100.0,
        pad=0.0,
    )
    assert hit is not None
    t, ix, iy, iz = hit
    assert 0.0 < t < 1.0
    assert ix == -100.0
    assert iy == 0.0
    assert iz == 0.0


def test_segment_misses_a_wide_pass() -> None:
    assert (
        first_hit_on_segment(
            -200.0,
            500.0,
            0.0,
            200.0,
            500.0,
            0.0,
            0.0,
            0.0,
            0.0,
            100.0,
        )
        is None
    )


def test_j2000_iso() -> None:
    assert jd_iso(2_451_545.0) == "2000-01-01 12:00:00 UTC"


def test_clamp_rate_floors_and_caps() -> None:
    assert clamp_rate(0.0) == RATE_MIN
    assert clamp_rate(1.0e20) == RATE_MAX
    assert clamp_rate(1.0) == 1.0
