"""Dipole corona sketch. Not MHD, not SDO, not a photosphere map.

Closed lines of a centred dipole obey r = L sin²θ in magnetic colatitude.
The pole is IAU WGCCRE 2015 solar north. Compact loops use the same law at
low L and ride the Carrington rate (IAU W).

Flares are a waiting-time sketch on wall seconds so the star still moves
while IAS15 is paused. Quiet most of the time; not a GOES catalog, not SDO.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from arelis.physics.attitude import sun_frame_ecliptic

# Typical granule scale. The shader draws fewer cells so they read at approach.
GRANULE_KM = 1000.0
# Linear limb-darkening coefficient ~500 nm (Pierce & Slaughter / Neckel).
LIMB_U = 0.56
# Closed-line cap. Helmet streamers on a dipole are a few solar radii, not AU.
L_MAX = 3.4
# Loops are a close-approach sketch. From 1 AU they are spaghetti on a 6 px disc.
LOOP_MIN_PX = 40.0
CITE = (
    "Photosphere: limb-darkened, no map. Corona: centred dipole + Carrington "
    "compact loops. Flares: waiting-time sketch on wall clock. Not SDO, not MHD."
)


@dataclass(frozen=True)
class Loop:
    """Sun-relative metres. flare is 0..1 from the waiting-time sketch."""

    points: np.ndarray
    flare: float
    kind: str


def dipole_radius(L: float, theta: float) -> float:
    """r/R_sun along a dipole line. L is the equatorial crossing in R_sun."""
    s = math.sin(float(theta))
    return float(L) * s * s


def dipole_line(
    L: float,
    phi: float,
    *,
    n: int = 65,
) -> np.ndarray:
    """Unit-sphere magnetic-frame points, r ≥ 1. Footpoints sit on the photosphere."""
    L = min(max(float(L), 1.02), L_MAX)
    s0 = math.sqrt(1.0 / L)
    s0 = min(0.999, max(0.05, s0))
    t0 = math.asin(s0)
    thetas = np.linspace(t0, math.pi - t0, max(int(n), 8), dtype=np.float64)
    st = np.sin(thetas)
    ct = np.cos(thetas)
    r = L * st * st
    cp, sp = math.cos(phi), math.sin(phi)
    x = r * st * cp
    y = r * st * sp
    z = r * ct
    return np.stack((x, y, z), axis=1)


def flare_gain(wall_s: float, seed: int) -> float:
    """One slow gaussian pulse per waiting-time draw. Mean wait ~50 s of wall."""
    u = _hash01(seed)
    period = 36.0 + 48.0 * u
    width = 2.6 + 1.1 * u
    phase = (float(wall_s) + 47.0 * u) % period
    x = (phase - 0.18 * period) / width
    if abs(x) > 3.2:
        return 0.0
    return math.exp(-x * x)


def loops(
    radius_m: float,
    jd: float,
    wall_s: float,
) -> list[Loop]:
    """Sun-relative metres in ECLIPJ2000. Photosphere radius is radius_m."""
    r_sun = max(float(radius_m), 1.0)
    xx, yx, zx = sun_frame_ecliptic(jd)
    out: list[Loop] = []
    seed = 0
    for L100 in (165, 205, 255, 315):
        for k in range(4):
            phi = (k + 0.12) * math.pi / 2.0
            pts = _to_world(dipole_line(L100 / 100.0, phi), xx, yx, zx, r_sun)
            out.append(Loop(pts, flare_gain(wall_s, seed), "dipole"))
            seed += 1
    for L100 in (109, 116, 126, 138):
        for k in range(4):
            phi = (k * 1.256637 + 0.31) % (2.0 * math.pi)
            pts = _to_world(dipole_line(L100 / 100.0, phi, n=49), xx, yx, zx, r_sun)
            out.append(Loop(pts, flare_gain(wall_s, seed + 40), "ar"))
            seed += 1
    return out


def line_segments(loop: Loop) -> np.ndarray:
    """(N, 3) pairs for GL_LINES."""
    pts = loop.points
    if pts.shape[0] < 2:
        return np.empty((0, 3), dtype=np.float64)
    segs = np.empty((2 * (pts.shape[0] - 1), 3), dtype=np.float64)
    segs[0::2] = pts[:-1]
    segs[1::2] = pts[1:]
    return segs


def _to_world(
    mag: np.ndarray,
    xx: tuple[float, float, float],
    yx: tuple[float, float, float],
    zx: tuple[float, float, float],
    r_sun: float,
) -> np.ndarray:
    x = mag[:, 0] * xx[0] + mag[:, 1] * yx[0] + mag[:, 2] * zx[0]
    y = mag[:, 0] * xx[1] + mag[:, 1] * yx[1] + mag[:, 2] * zx[1]
    z = mag[:, 0] * xx[2] + mag[:, 1] * yx[2] + mag[:, 2] * zx[2]
    return np.stack((x * r_sun, y * r_sun, z * r_sun), axis=1)


def _hash01(seed: int) -> float:
    x = (int(seed) * 1_103_515_245 + 12_345) & 0x7FFFFFFF
    return x / 2_147_483_647.0
