"""Mesh, projection, and Earth-frame helpers for solar GL.

SolarSpaceView, stars_only, and the desktop-GL opt-in stay in solar_gl.py.
A photoreal miss must not set host.failed — that contract lives on the
widget / host side, not here.
"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtGui import QMatrix4x4
from shiboken6 import VoidPtr

from arelis.physics.attitude import body_frame_ecliptic


def _enum_name(value: object) -> str:
    """PySide6 enums are not ints. Logging must not crash realize()."""
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name
    return str(value)


def describe_gl_format(got: object) -> str:
    """One breadcrumb line. Never raise: this used to abort GPU init."""
    try:
        return (
            f"got context {got.majorVersion()}.{got.minorVersion()} "
            f"profile={_enum_name(got.profile())} "
            f"renderable={_enum_name(got.renderableType())} "
            f"samples={got.samples()}"
        )
    except Exception:
        return "got context (could not describe format)"


def gl_offset(byte_offset: int) -> object:
    """GLvoid* for QOpenGLFunctions. A Python int is rejected (mesh-upload crash)."""
    return VoidPtr(int(byte_offset))


def uniform_is_int(value: object) -> bool:
    """True only for Python int. 4e14 as float must not take the int uniform path."""
    return type(value) is int

_GL_CCW = 0x0901
_FOV_Y = 0.70
_FAR_M = 4.0e14
_FB_CAP = 2560

def framebuffer_size(
    width: int, height: int, *, cap: int = _FB_CAP
) -> tuple[int, int]:
    """Readback size. Full window toImage at 4K is the 5 Hz path."""
    w, h = max(int(width), 1), max(int(height), 1)
    long_edge = max(w, h)
    if long_edge <= cap:
        return w, h
    scale = cap / long_edge
    return max(1, int(w * scale)), max(1, int(h * scale))


def projection(fb_w: int, fb_h: int, *, fov_y: float | None = None) -> QMatrix4x4:
    """Perspective with clip Y negated.

    glReadPixels hands back rows bottom-up, so rendering upside down is what
    makes the readback come out the right way round without copying the whole
    frame through QImage.mirrored() every paint. The reflection also reverses
    triangle winding, which is why realize() sets FRONT_FACE.
    """
    fov = float(fov_y) if fov_y is not None else _FOV_Y
    proj = QMatrix4x4()
    proj.perspective(
        math.degrees(fov), fb_w / max(fb_h, 1), 1.0e3, _FAR_M
    )
    proj.scale(1.0, -1.0, 1.0)
    return proj


# view_from_basis has determinant -1 and projection() adds another reflection,
# so front faces come back round to counter-clockwise.
FRONT_FACE = _GL_CCW


def glow_extent_px(sun_px: float, fb_h: int) -> float:
    """Pixel radius of the flare quad. See arelis.physics.star_look."""
    from arelis.physics.star_look import star_flare

    return star_flare(sun_px, fb_h).extent_px


def view_from_basis(
    fx: tuple[float, float, float],
    fy: tuple[float, float, float],
    fz: tuple[float, float, float],
) -> QMatrix4x4:
    """Eye-space matching Camera.project.

    Rows fx, fy, -fz have det -1, so winding is reversed here and again by the
    clip-Y flip in projection(). FRONT_FACE carries the net result. Qt lookAt
    would keep winding and mirror X against the overlay.
    """
    return QMatrix4x4(
        fx[0],
        fx[1],
        fx[2],
        0.0,
        fy[0],
        fy[1],
        fy[2],
        0.0,
        -fz[0],
        -fz[1],
        -fz[2],
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def earth_mesh_to_ecef() -> QMatrix4x4:
    """Mesh UV → ECEF so NASA plate-carrée lines up with overlays.

    make_sphere: u=0 is +Z, u=0.5 is −Z, +Y is the north pole. NASA
    Blue Marble has u=0 at the antimeridian and u=0.5 at Greenwich, so
    mesh −Z must be ECEF +X and mesh +Y must be ECEF +Z.
    """
    return QMatrix4x4(
        0.0,
        0.0,
        -1.0,
        0.0,
        -1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def earth_spin_matrix(jd: float) -> QMatrix4x4:
    """ECLIPJ2000 from a unit mesh point. Same axes as ecef_to_ecliptic."""
    frame = body_frame_ecliptic("Earth", jd)
    assert frame is not None
    return _frame_matrix(frame) * earth_mesh_to_ecef()


def _frame_matrix(frame) -> QMatrix4x4:
    xx, yx, zx = frame
    return QMatrix4x4(
        xx[0],
        yx[0],
        zx[0],
        0.0,
        xx[1],
        yx[1],
        zx[1],
        0.0,
        xx[2],
        yx[2],
        zx[2],
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def make_sphere(slices: int = 96, stacks: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """Unit sphere, +Y pole. Interleaved pos, normal, uv. Clockwise? CCW with +Y."""
    verts: list[float] = []
    for i in range(stacks + 1):
        v = i / stacks
        phi = v * math.pi
        sp, cp = math.sin(phi), math.cos(phi)
        for j in range(slices + 1):
            u = j / slices
            th = u * 2.0 * math.pi
            st, ct = math.sin(th), math.cos(th)
            x, y, z = st * sp, cp, ct * sp
            verts.extend((x, y, z, x, y, z, u, 1.0 - v))
    idx: list[int] = []
    row = slices + 1
    for i in range(stacks):
        for j in range(slices):
            a = i * row + j
            b = a + row
            idx.extend((a, b, a + 1, a + 1, b, b + 1))
    return (
        np.asarray(verts, dtype=np.float32),
        np.asarray(idx, dtype=np.uint32),
    )


def make_stars(count: int = 9000, seed: int = 20260824) -> np.ndarray:
    """Unit directions + 0..1 brightness. Denser along a tilted band (illustration)."""
    rng = np.random.default_rng(seed)
    n = int(count)
    field = rng.normal(size=(n, 3))
    field /= np.linalg.norm(field, axis=1, keepdims=True).clip(1e-9)
    pole = np.array([0.18, 0.48, 0.86], dtype=np.float64)
    pole /= np.linalg.norm(pole)
    extra = int(n * 0.35)
    band = rng.normal(size=(extra, 3))
    band -= (band @ pole)[:, None] * pole
    band += pole * rng.normal(scale=0.12, size=(extra, 1))
    band /= np.linalg.norm(band, axis=1, keepdims=True).clip(1e-9)
    dirs = np.vstack((field, band))
    mag = rng.random(len(dirs)) ** 2.4
    mag[:80] = np.linspace(0.75, 1.0, 80)
    out = np.zeros((len(dirs), 4), dtype=np.float32)
    out[:, :3] = dirs.astype(np.float32)
    out[:, 3] = mag.astype(np.float32)
    return out


def make_ring(inner: float, outer: float, steps: int = 96) -> np.ndarray:
    """XY annulus triangle strip. Ecliptic plane; +Z north."""
    verts: list[float] = []
    for i in range(steps + 1):
        ang = 2.0 * math.pi * i / steps
        c, s = math.cos(ang), math.sin(ang)
        verts.extend((inner * c, inner * s, 0.0, 0.0, 0.0, 1.0, 0.0, 0.5))
        verts.extend((outer * c, outer * s, 0.0, 0.0, 0.0, 1.0, 1.0, 0.5))
    return np.asarray(verts, dtype=np.float32)

