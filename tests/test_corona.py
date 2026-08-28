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
    Loop,
    dipole_line,
    dipole_radius,
    flare_gain,
    line_segments,
    loops,
    off_limb_segments,
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


def test_off_limb_hides_the_front_of_the_disc() -> None:
    loop = Loop(
        np.array(
            ((0.15, 0.0, -0.96), (-0.15, 0.0, -0.96), (0.0, 0.2, -0.94)),
            dtype=np.float64,
        ),
        0.0,
        "ar",
    )
    segs = off_limb_segments(loop, 1.0, sun_eye=np.array((0.0, 0.0, 24.0)))
    assert segs.shape[0] == 0


def test_off_limb_keeps_a_prominence() -> None:
    loop = Loop(
        np.array(
            ((1.45, 0.0, 0.0), (1.62, 0.12, 0.0), (1.45, 0.24, 0.0)),
            dtype=np.float64,
        ),
        0.0,
        "ar",
    )
    segs = off_limb_segments(loop, 1.0, sun_eye=np.array((0.0, 0.0, 24.0)))
    assert segs.shape[0] >= 2
    assert segs.shape[0] % 2 == 0


def test_glow_shader_keeps_glare_and_off_limb_loops() -> None:
    import inspect as pyinspect

    from arelis.ui import solar_gl as gl

    src = gl._FS_GLOW
    assert "sin(ang" not in src
    assert "phi * 3.0" not in src
    assert "uDisc" in src
    assert "uPole" in src
    assert "r > 0.98" in src
    assert "1.42" not in src
    assert "Baumbach" not in src
    assert "uGain" in src
    glow_src = pyinspect.getsource(gl.SolarSpaceView._draw_glow)
    loops_src = pyinspect.getsource(gl.SolarSpaceView._draw_loops)
    assert "LOOP_MIN_PX" in loops_src
    assert "off_limb_segments" in loops_src
    assert "show_magnetic" in loops_src
    assert "or not mag" in loops_src
    assert "glDisable(_GL_DEPTH_TEST)" in glow_src
    assert "glDisable(_GL_CULL_FACE)" in glow_src
    assert "uSunNdc" in gl._VS_GLOW
    assert "uClose" in gl._FS_GLOW
    assert "uClose" in gl._FS_BODY
    assert "float needle(" in src
    assert "pow(abs(dir.x)" not in src
    assert "* far" not in src
    assert LOOP_MIN_PX == 40.0


def test_glow_extent_is_pixel_capped_not_a_viewport_fill() -> None:
    from arelis.physics.star_look import star_flare
    from arelis.ui.solar_gl import glow_extent_px

    far = glow_extent_px(0.12, 1334)
    assert 12.0 <= far <= 48.0
    near = glow_extent_px(150.0, 1334)
    assert near > 150.0
    assert near < 0.22 * 1334
    point = star_flare(0.1, 1334)
    close = star_flare(160.0, 1334)
    assert point.spike_gain > 0.85
    assert close.spike_gain > 0.25
    assert close.spike_px > close.disc_px
    assert point.extent_px < 0.06 * 1334
    assert close.bloom_px < close.disc_px * 1.12
    assert close.bloom_px > close.disc_px
