"""Dipole corona sketch: r = L sin²θ, IAU pole, waiting-time flares."""

from __future__ import annotations

import math

import numpy as np
import pytest

from arelis.physics.attitude import spin_caption, sun_frame_ecliptic, sun_pole_ecliptic
from arelis.physics.constants import BODY_BY_NAME, SUN_POLE_DEC_DEG, SUN_POLE_RA_DEG
from arelis.physics.corona import (
    CITE,
    L_MAX,
    LOOP_MIN_PX,
    dipole_line,
    dipole_radius,
    flare_gain,
    line_segments,
    loops,
)


def test_dipole_equator_is_l() -> None:
    assert dipole_radius(2.0, math.pi / 2.0) == pytest.approx(2.0)


def test_dipole_footpoints_sit_on_the_photosphere() -> None:
    pts = dipole_line(1.8, 0.4)
    r = np.sqrt((pts * pts).sum(axis=1))
    assert r[0] == pytest.approx(1.0, rel=1e-6)
    assert r[-1] == pytest.approx(1.0, rel=1e-6)
    assert r.min() == pytest.approx(1.0, rel=1e-6)
    assert r.max() == pytest.approx(1.8, rel=1e-6)


def test_dipole_l_is_capped() -> None:
    pts = dipole_line(80.0, 0.0)
    r = np.sqrt((pts * pts).sum(axis=1))
    assert r.max() <= L_MAX + 1e-9


def test_sun_pole_is_unit_and_iau() -> None:
    x, y, z = sun_pole_ecliptic()
    assert math.sqrt(x * x + y * y + z * z) == pytest.approx(1.0)
    assert z > 0.4
    assert SUN_POLE_RA_DEG == 286.13
    assert SUN_POLE_DEC_DEG == 63.87


def test_sun_frame_is_orthonormal() -> None:
    xx, yx, zx = sun_frame_ecliptic(2_451_545.0)
    for a, b in ((xx, yx), (xx, zx), (yx, zx)):
        assert abs(sum(i * j for i, j in zip(a, b, strict=True))) < 1e-9
    pole = sun_pole_ecliptic()
    assert sum(a * b for a, b in zip(zx, pole, strict=True)) == pytest.approx(
        1.0, abs=1e-6
    )


def test_flare_gain_is_deterministic_and_bounded() -> None:
    a = flare_gain(3.0, 7)
    b = flare_gain(3.0, 7)
    assert a == b
    assert 0.0 <= a <= 1.0
    assert 0.0 <= flare_gain(1e6, 99) <= 1.0


def test_flare_gain_is_mostly_quiet() -> None:
    hits = sum(1 for t in range(400) if flare_gain(float(t), 7) > 0.08)
    assert hits < 80
    assert any(flare_gain(float(t), 7) > 0.5 for t in range(400))


def test_loops_stay_outside_the_photosphere() -> None:
    r_sun = BODY_BY_NAME["Sun"].radius
    rows = loops(r_sun, 2_451_545.0, 12.0)
    assert len(rows) > 10
    for loop in rows:
        r = np.sqrt((loop.points * loop.points).sum(axis=1))
        assert r.min() >= r_sun * 0.99
        assert r.max() <= r_sun * (L_MAX + 0.05)
        segs = line_segments(loop)
        assert segs.shape[0] >= 2
        assert segs.shape[0] % 2 == 0


def test_cite_does_not_claim_sdo() -> None:
    low = CITE.lower()
    assert "dipole" in low
    assert "not sdo" in low
    assert "not mhd" in low
    assert spin_caption("Sun").lower().startswith("photosphere has no map")


def test_glow_shader_has_no_sixfold_spikes() -> None:
    import inspect as pyinspect

    from arelis.ui import solar_gl as gl

    src = gl._FS_GLOW
    assert "sin(ang" not in src
    assert "uDisc" in src
    assert "uPole" in src
    assert "r > 1.0" in src
    assert "uGran" in gl._FS_BODY
    loops_src = pyinspect.getsource(gl.SolarSpaceView._draw_loops)
    assert "LOOP_MIN_PX" in loops_src
    assert LOOP_MIN_PX == 40.0
