"""Sparks, gas copies, and the orbit ring from the approved renderer."""

from __future__ import annotations

import numpy as np

from arelis.ui.persona_face.nebula_src import hexrgb, lerpc


def gasify(pts, n_per, jit, rng, noise=None, nd=0.0):
    pts = np.repeat(pts, n_per, 0)
    jit = np.repeat(np.broadcast_to(jit, (len(pts) // n_per,)), n_per)
    pts = pts + rng.normal(0, 1, pts.shape) * jit[:, None]
    if noise is not None and nd:
        cx, cy = noise.curl(pts[:, 0], pts[:, 1])
        pts = pts + np.stack([cx, cy], 1) * nd
    return pts


def sparkle(cv, c, size, color, strength=1.0):
    cv.blob(c, size * 0.12, color, 2.2 * strength)
    cv.blob(c, size * 0.45, color, 0.35 * strength)
    t = np.linspace(-size, size, 1200)
    f = np.exp(-np.abs(t) / (size * 0.22))
    for ang, s in ((0, 1.0), (np.pi / 2, 1.0), (np.pi / 4, 0.35), (-np.pi / 4, 0.35)):
        xy = np.stack([c[0] + t * np.cos(ang) * s, c[1] + t * np.sin(ang) * s], 1)
        cv.splat(xy, f * 0.5 * strength, color, sigma=0.9)


def orbit_ring(
    cv, pal, noise, r, strength=1.0, c=(0.0, 0.27), rx=0.80, ry=0.19, tilt=-0.17, open_=1.0
):
    n = 70000
    a = r.random(n) * 2 * np.pi
    nv = noise.val(np.cos(a) * 1.3 + 0.3, np.sin(a) * 1.3)
    k = 1 + r.normal(0, 0.006, n) + nv * 0.012
    ex, ey = np.cos(a) * rx * k, np.sin(a) * ry * k
    x = c[0] + ex * np.cos(tilt) - ey * np.sin(tilt)
    y = c[1] + ex * np.sin(tilt) + ey * np.cos(tilt)
    br = (0.35 + 0.9 * np.clip(nv + 0.3, 0, 1)) * strength
    back = np.sin(a) < 0
    br = np.where(back & (np.abs(x) < 0.44), br * 0.08, br)
    br = np.where(back, br * 0.6, br)
    xy = np.stack([x, y], 1)
    cv.splat(xy, 0.008 * br, lerpc(pal["ring"], pal["face"], 0.3), 0.8)
    cv.splat(xy[::3], 0.012 * br[::3], hexrgb(pal["ring"]), 3.5)
