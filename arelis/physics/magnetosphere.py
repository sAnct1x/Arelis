"""Earth magnetopause sketch. Shue 1998 surface + centered dipole L-shells.

Ram pressure comes from Parker quiet wind via shue_standoff. The dipole is
a centered axial cage about ecliptic north in the Sun–Earth frame. Not IGRF.
"""

from __future__ import annotations

import math

import numpy as np

from arelis.physics.parker import shue_standoff


def earth_standoff_m(
    p_npa: float, re: float, *, bz_nt: float = 0.0
) -> tuple[float, float, float]:
    """Shue 1998 r0 in metres, r0 in Re, and flaring α."""
    r0_re, alpha = shue_standoff(float(p_npa), bz_nt=float(bz_nt))
    return r0_re * max(float(re), 1.0), r0_re, alpha

# Nose-to-flank. Shue blows up toward the tail; keep the dayside + flanks.
THETA_MAX = math.radians(120.0)
# Dense enough to read as a shell from 8 R_E, cheap next to FBO readback.
N_THETA = 48
N_PHI = 48
L_SHELLS: tuple[float, ...] = (4.0, 6.0, 8.0, 10.0)
N_DIPOLE_LON = 12
N_DIPOLE_LAT = 40


def sunward_basis(
    earth: tuple[float, float, float],
    sun: tuple[float, float, float],
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """ux toward the Sun, uz near ecliptic north, uy dawn-dusk."""
    ux = (
        sun[0] - earth[0],
        sun[1] - earth[1],
        sun[2] - earth[2],
    )
    ul = math.hypot(*ux) or 1.0
    ux = (ux[0] / ul, ux[1] / ul, ux[2] / ul)
    z_ref = (0.0, 0.0, 1.0)
    d = ux[0] * z_ref[0] + ux[1] * z_ref[1] + ux[2] * z_ref[2]
    uz = (z_ref[0] - d * ux[0], z_ref[1] - d * ux[1], z_ref[2] - d * ux[2])
    zl = math.hypot(*uz)
    if zl < 1e-9:
        uz = (0.0, 1.0, 0.0)
        zl = 1.0
    uz = (uz[0] / zl, uz[1] / zl, uz[2] / zl)
    uy = (
        uz[1] * ux[2] - uz[2] * ux[1],
        uz[2] * ux[0] - uz[0] * ux[2],
        uz[0] * ux[1] - uz[1] * ux[0],
    )
    yl = math.hypot(*uy) or 1.0
    uy = (uy[0] / yl, uy[1] / yl, uy[2] / yl)
    return ux, uy, uz


def shue_radius(r0: float, alpha: float, theta: float) -> float:
    """Shue 1998 r(θ) = r0 (2 / (1 + cos θ))^α. Zero in the deep tail."""
    den = 1.0 + math.cos(theta)
    if den < 0.14:
        return 0.0
    return float(r0) * (2.0 / den) ** float(alpha)


def shue_surface(
    r0_m: float,
    alpha: float,
    ux: tuple[float, float, float],
    uy: tuple[float, float, float],
    uz: tuple[float, float, float],
    *,
    n_theta: int = N_THETA,
    n_phi: int = N_PHI,
    theta_max: float = THETA_MAX,
) -> tuple[np.ndarray, np.ndarray]:
    """Earth-relative metres. Positions (V, 3), triangle indices."""
    nt = max(int(n_theta), 8)
    np_ = max(int(n_phi), 8)
    row = np_ + 1
    verts = np.empty(((nt + 1) * row, 3), dtype=np.float64)
    for i in range(nt + 1):
        theta = theta_max * i / nt
        cth, sth = math.cos(theta), math.sin(theta)
        r = shue_radius(r0_m, alpha, theta)
        for j in range(row):
            phi = 2.0 * math.pi * j / np_
            cph, sph = math.cos(phi), math.sin(phi)
            # Revolution about the Sun–Earth axis.
            sx = cth
            sy = sth * cph
            sz = sth * sph
            verts[i * row + j] = (
                r * (sx * ux[0] + sy * uy[0] + sz * uz[0]),
                r * (sx * ux[1] + sy * uy[1] + sz * uz[1]),
                r * (sx * ux[2] + sy * uy[2] + sz * uz[2]),
            )
    idx: list[int] = []
    for i in range(nt):
        for j in range(np_):
            a = i * row + j
            b = a + row
            idx.extend((a, b, a + 1, a + 1, b, b + 1))
    return verts, np.asarray(idx, dtype=np.uint32)


def shue_meridians(
    r0_m: float,
    alpha: float,
    ux: tuple[float, float, float],
    uy: tuple[float, float, float],
    uz: tuple[float, float, float],
    *,
    n_theta: int = 32,
    n_phi: int = 8,
    theta_max: float = THETA_MAX,
) -> list[list[tuple[float, float, float]]]:
    """Software strokes of the same Shue surface of revolution."""
    nt = max(int(n_theta), 8)
    nphi = max(int(n_phi), 3)
    out: list[list[tuple[float, float, float]]] = []
    for j in range(nphi):
        phi = 2.0 * math.pi * j / nphi
        cph, sph = math.cos(phi), math.sin(phi)
        line: list[tuple[float, float, float]] = []
        for i in range(nt + 1):
            theta = theta_max * i / nt
            cth, sth = math.cos(theta), math.sin(theta)
            r = shue_radius(r0_m, alpha, theta)
            if r <= 0.0:
                continue
            sx, sy, sz = cth, sth * cph, sth * sph
            line.append(
                (
                    r * (sx * ux[0] + sy * uy[0] + sz * uz[0]),
                    r * (sx * ux[1] + sy * uy[1] + sz * uz[1]),
                    r * (sx * ux[2] + sy * uy[2] + sz * uz[2]),
                )
            )
        if len(line) >= 2:
            out.append(line)
    return out


def dipole_L_polylines(
    re: float,
    ux: tuple[float, float, float],
    uy: tuple[float, float, float],
    uz: tuple[float, float, float],
    *,
    shells: tuple[float, ...] = L_SHELLS,
    n_lon: int = N_DIPOLE_LON,
    n_lat: int = N_DIPOLE_LAT,
) -> list[np.ndarray]:
    """Centered dipole meridians. r = L Re cos²λ, axis uz. Skip inside the globe."""
    re = max(float(re), 1.0)
    nlon = max(int(n_lon), 4)
    nlat = max(int(n_lat), 8)
    lines: list[np.ndarray] = []
    for L in shells:
        if L <= 1.02:
            continue
        lambda_max = math.acos(min(0.999, math.sqrt(1.02 / L)))
        for k in range(nlon):
            lon = 2.0 * math.pi * k / nlon
            cl, sl = math.cos(lon), math.sin(lon)
            pts: list[tuple[float, float, float]] = []
            for i in range(nlat + 1):
                lam = -lambda_max + 2.0 * lambda_max * i / nlat
                c, s = math.cos(lam), math.sin(lam)
                rr = L * re * (c * c)
                if rr < 1.02 * re:
                    if pts:
                        lines.append(np.asarray(pts, dtype=np.float64))
                        pts = []
                    continue
                rho = rr * c
                x, y, z = rho * cl, rho * sl, rr * s
                pts.append(
                    (
                        x * ux[0] + y * uy[0] + z * uz[0],
                        x * ux[1] + y * uy[1] + z * uz[1],
                        x * ux[2] + y * uy[2] + z * uz[2],
                    )
                )
            if len(pts) >= 2:
                lines.append(np.asarray(pts, dtype=np.float64))
    return lines


def dipole_segments(lines: list[np.ndarray]) -> np.ndarray | None:
    """GL_LINES pairs from dipole polylines."""
    segs: list[np.ndarray] = []
    for line in lines:
        if line.shape[0] < 2:
            continue
        a = line[:-1]
        b = line[1:]
        pair = np.empty((a.shape[0] * 2, 3), dtype=np.float64)
        pair[0::2] = a
        pair[1::2] = b
        segs.append(pair)
    if not segs:
        return None
    return np.vstack(segs)
