"""Catalog stop-spheres. No rebound, no death.

clip_relative / first_hit_on_segment are the math, not a live vehicle.
"""

from __future__ import annotations

from arelis.physics.clocks import RATE_MAX, RATE_MIN, clamp_rate
from arelis.physics.collision import (
    clip_relative,
    first_hit_on_segment,
)


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


def test_clamp_rate_floors_and_caps() -> None:
    assert clamp_rate(0.0) == RATE_MIN
    assert clamp_rate(1.0e20) == RATE_MAX
    assert clamp_rate(1.0) == 1.0
