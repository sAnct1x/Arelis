"""OpenGL solar viewport helpers. The widget itself stays off under offscreen."""

from __future__ import annotations

import os

import pytest

from arelis.ui.solar_gl import (
    framebuffer_size,
    make_sphere,
)


def test_main_solar_gl_flag_sets_env_before_version_exits(monkeypatch) -> None:
    """The desktop shortcut cannot set env vars. --solar-gl has to do that job."""
    monkeypatch.delenv("ARELIS_SOLAR_GL", raising=False)
    from arelis.main import main

    with pytest.raises(SystemExit):
        main(["--solar-gl", "--version"])
    assert os.environ.get("ARELIS_SOLAR_GL") == "1"


def test_make_sphere_indexed() -> None:
    verts, idx = make_sphere(8, 4)
    nvert = verts.size // 8
    assert nvert == 9 * 5
    assert idx.min() == 0
    assert int(idx.max()) < nvert
    assert idx.size % 3 == 0


def test_earth_gl_cache_ignores_spin_micro_moves() -> None:
    from arelis.ui.solar_gl import earth_gl_cache_key

    base = dict(
        width=800,
        height=600,
        look=(0.0, 0.0, 0.0),
        up=(0.0, 0.0, 1.0),
        paused=False,
        fov_y=50.0,
        inspect="Earth",
    )
    a = earth_gl_cache_key(eye=(1_000_000.0, 0.0, 0.0), t=1.2, **base)
    near = earth_gl_cache_key(eye=(1_000_040.0, 0.0, 0.0), t=1.2, **base)
    far = earth_gl_cache_key(eye=(1_000_200.0, 0.0, 0.0), t=1.2, **base)
    later = earth_gl_cache_key(eye=(1_000_000.0, 0.0, 0.0), t=1.8, **base)
    next_s = earth_gl_cache_key(eye=(1_000_000.0, 0.0, 0.0), t=2.1, **base)
    hour = earth_gl_cache_key(
        eye=(1_000_000.0, 0.0, 0.0), t=29.0, t_step=30.0, **base
    )
    hour_near = earth_gl_cache_key(
        eye=(1_000_000.0, 0.0, 0.0), t=1.2, t_step=30.0, **base
    )
    assert a == near
    assert a != far
    assert a == later
    assert a != next_s
    assert hour == hour_near


def test_framebuffer_size_caps_readback() -> None:
    from arelis.ui.solar_gl import _FB_CLOSE

    assert framebuffer_size(800, 600) == (800, 600)
    # A 1440p plate renders native: upscaling a 1920 readback is the blur.
    assert framebuffer_size(2560, 1440) == (2560, 1440)
    # Concrete bounds, not _FB_CAP: comparing the cap against itself would hold
    # for any number anyone typed there, including one that stalls on readback.
    w, h = framebuffer_size(3840, 2160)
    assert 2500 < max(w, h) <= 2560
    assert w / h == pytest.approx(3840 / 2160, rel=0.02)
    assert framebuffer_size(2160, 3840)[1] == max(w, h)
    assert max(framebuffer_size(3840, 2160, cap=1920)) <= 1920
    # Inspecting no longer asks for a bigger frame than the base cap.
    assert framebuffer_size(3840, 2160, cap=_FB_CLOSE) == (w, h)


def test_earth_atmosphere_is_a_thin_shell() -> None:
    from arelis.ui.solar_gl import _ATMO, _FS_BODY

    _rgb, scale, gain = _ATMO["Earth"]
    assert scale < 1.03
    assert gain < 0.55
    assert _ATMO["Venus"][1] < 1.03
    assert "uAlpha" in _FS_BODY
    assert "0.16" in _FS_BODY


