"""OpenGL solar viewport helpers. The widget itself stays off under offscreen."""

from __future__ import annotations

import os

import numpy as np
import pytest

from arelis.ui.solar_gl import (
    describe_gl_format,
    framebuffer_size,
    gl_offset,
    gl_wanted,
    make_ring,
    make_sphere,
    make_stars,
    prepare_desktop_gl,
    uniform_is_int,
    view_from_basis,
)


def test_gl_wanted_off_when_offscreen(monkeypatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.delenv("ARELIS_SOLAR_GL", raising=False)
    assert gl_wanted() is False


def test_gl_wanted_off_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ARELIS_SOLAR_GL", raising=False)
    monkeypatch.setenv("QT_QPA_PLATFORM", "windows")
    assert gl_wanted() is False


def test_gl_wanted_opt_out(monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_SOLAR_GL", "0")
    monkeypatch.setenv("QT_QPA_PLATFORM", "windows")
    assert gl_wanted() is False


def test_prepare_desktop_gl_is_opt_in() -> None:
    env: dict[str, str] = {}
    prepare_desktop_gl(env)
    assert "QT_OPENGL" not in env
    env = {"ARELIS_SOLAR_GL": "1"}
    prepare_desktop_gl(env)
    assert env["QT_OPENGL"] == "desktop"


def test_gl_wanted_on_for_desktop(monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_SOLAR_GL", "1")
    monkeypatch.setenv("QT_QPA_PLATFORM", "windows")
    assert gl_wanted() is True


def test_describe_gl_format_does_not_int_pyside_enums() -> None:
    class _Profile:
        name = "CompatibilityProfile"

    class _Renderable:
        pass

    class _Fmt:
        def majorVersion(self) -> int:
            return 4

        def minorVersion(self) -> int:
            return 6

        def profile(self) -> _Profile:
            return _Profile()

        def renderableType(self) -> _Renderable:
            return _Renderable()

        def samples(self) -> int:
            return 0

    text = describe_gl_format(_Fmt())
    assert "4.6" in text
    assert "CompatibilityProfile" in text
    assert describe_gl_format(object()) == "got context (could not describe format)"


def test_view_from_basis_matches_pinhole_axes() -> None:
    from PySide6.QtGui import QVector3D

    from arelis.physics.camera import look_basis

    fx, fy, fz = look_basis((0.0, 0.0, 0.0), (0.0, 0.0, 10.0))
    view = view_from_basis(fx, fy, fz)
    ahead = view.map(QVector3D(0.0, 0.0, 10.0))
    assert ahead.z() < 0.0
    right = view.map(QVector3D(fx[0], fx[1], fx[2]))
    assert right.x() > 0.5


def test_far_plane_is_a_float_uniform() -> None:
    assert uniform_is_int(0) is True
    assert uniform_is_int(4.0e14) is False
    assert uniform_is_int(4e14) is False


def test_gl_offset_is_not_a_plain_int() -> None:
    ptr = gl_offset(12)
    assert not isinstance(ptr, int)
    assert gl_offset(0) is not None


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


def test_make_stars_unit_directions() -> None:
    stars = make_stars(200, seed=1)
    norms = np.linalg.norm(stars[:, :3], axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)
    assert stars[:, 3].min() >= 0.0
    assert stars[:, 3].max() <= 1.0


def test_make_ring_lies_in_ecliptic_xy() -> None:
    ring = make_ring(111 / 100, 227 / 100, steps=8)
    pts = ring.reshape(-1, 8)
    assert np.allclose(pts[:, 2], 0.0, atol=1e-6)
    radii = np.hypot(pts[:, 0], pts[:, 1])
    assert radii.min() >= 1.10
    assert radii.max() <= 2.28


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


def test_projection_flips_clip_y_for_bottom_up_readback() -> None:
    """glReadPixels is bottom-up, so the render is deliberately upside down."""
    import math

    from PySide6.QtGui import QMatrix4x4, QVector3D

    from arelis.ui.solar_gl import projection

    plain = QMatrix4x4()
    plain.perspective(math.degrees(0.70), 1600 / 900, 1.0e3, 4.0e14)
    flipped = projection(1600, 900)
    point = QVector3D(3.0e6, 1.0e6, -1.0e7)
    assert plain.map(point).y() > 0.0
    assert flipped.map(point).y() == pytest.approx(-plain.map(point).y())
    assert flipped.map(point).x() == pytest.approx(plain.map(point).x())


def test_front_face_matches_the_winding_the_matrices_actually_produce() -> None:
    """Cull the wrong set and every planet disappears.

    view_from_basis reflects once and projection() reflects again, so the answer
    is derived here from the real mesh through the real matrices. Asserting
    FRONT_FACE against its own value would pass either way round.
    """
    from arelis.physics.camera import look_basis
    from arelis.ui.solar_gl import _GL_CCW, _GL_CW, FRONT_FACE, projection

    verts, idx = make_sphere(16, 8)
    rows = verts.reshape(-1, 8)
    eye = (0.0, 0.0, 0.0)
    cx, cy, cz = 0.0, 0.0, 5.0e7
    radius = 1.0e7
    clip = projection(1600, 900) * view_from_basis(*look_basis(eye, (cx, cy, cz)))
    r0, r1, r3 = clip.row(0), clip.row(1), clip.row(3)

    def world(i: int) -> tuple[float, float, float]:
        n = rows[i, 3:6]
        return (
            cx + radius * float(n[0]),
            cy + radius * float(n[1]),
            cz + radius * float(n[2]),
        )

    def outward(i: int) -> bool:
        n = rows[i, 3:6]
        wx, wy, wz = world(i)
        return (
            float(n[0]) * (eye[0] - wx)
            + float(n[1]) * (eye[1] - wy)
            + float(n[2]) * (eye[2] - wz)
        ) > 0.0

    def screen(i: int) -> tuple[float, float]:
        wx, wy, wz = world(i)

        def dot(row) -> float:
            return row.x() * wx + row.y() * wy + row.z() * wz + row.w()

        w = dot(r3)
        assert w > 0.0
        return dot(r0) / w, dot(r1) / w

    assert FRONT_FACE in (_GL_CW, _GL_CCW)
    checked = 0
    for t in range(0, int(idx.size), 3):
        a, b, c = int(idx[t]), int(idx[t + 1]), int(idx[t + 2])
        if not (outward(a) and outward(b) and outward(c)):
            continue
        ax, ay = screen(a)
        bx, by = screen(b)
        cxx, cyy = screen(c)
        # Signed area in a y-up frame: positive is counter-clockwise, which is
        # the same sign convention glFrontFace uses on window coordinates.
        area = (bx - ax) * (cyy - ay) - (by - ay) * (cxx - ax)
        if abs(area) < 1e-15:
            continue
        assert (area > 0.0) == (FRONT_FACE == _GL_CCW), (
            "a triangle whose normal faces the eye must not be culled"
        )
        checked += 1
    assert checked > 20


def test_earth_atmosphere_is_a_thin_shell() -> None:
    from arelis.ui.solar_gl import _ATMO, _FS_BODY

    rgb, scale, gain = _ATMO["Earth"]
    assert scale < 1.03
    assert gain < 0.55
    assert _ATMO["Venus"][1] < 1.03
    assert "uAlpha" in _FS_BODY
    assert "0.16" in _FS_BODY


def test_solar_panel_skips_gl_offscreen(qt_app) -> None:
    from arelis.physics.runtime import set_system
    from arelis.ui.panels.solar import SolarPanel

    set_system(None)
    panel = SolarPanel()
    assert panel._space is None
    panel.resize(320, 240)
    panel.show()
    qt_app.processEvents()
    panel.hide()
