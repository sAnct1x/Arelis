"""Circular restricted three-body Lagrange points. Labeled CR3BP, not N-body."""

from __future__ import annotations

import math


def mass_parameter(m1: float, m2: float) -> float:
    tot = m1 + m2
    if tot <= 0.0:
        return 0.0
    return m2 / tot


def collinear_offsets(mu: float) -> tuple[float, float, float]:
    """Approximate L1, L2, L3 x-offsets from the barycenter in units of R.

    Secondary is at (1-mu), primary at (-mu). Series in mu^(1/3) as in
    Szebehely. Good enough to place a marker; HUD must say CR3BP circular.
    """
    mu = min(0.49, max(1e-12, float(mu)))
    g = (mu / 3.0) ** (1.0 / 3.0)
    # Distance from secondary toward/away from primary
    d12 = g * (1.0 + g / 3.0 - g * g / 9.0)
    x1 = (1.0 - mu) - d12
    x2 = (1.0 - mu) + d12
    x3 = -1.0 - mu * 5.0 / 12.0
    return (x1, x2, x3)


def sun_planet_l_points(
    r_planet: tuple[float, float, float],
    m_sun: float,
    m_planet: float,
    v_planet: tuple[float, float, float] | None = None,
) -> dict[str, tuple[float, float, float]]:
    """Place L1-L5. Collinear from CR3BP; L4/L5 are +/-60 deg in the orbital plane."""
    rx, ry, rz = r_planet
    r = math.sqrt(rx * rx + ry * ry + rz * rz)
    if r < 1.0:
        return {}
    ux, uy, uz = rx / r, ry / r, rz / r
    mu = mass_parameter(m_sun, m_planet)
    x1, x2, x3 = collinear_offsets(mu)

    def along(frac: float) -> tuple[float, float, float]:
        return (frac * r * ux, frac * r * uy, frac * r * uz)

    out = {"L1": along(x1), "L2": along(x2), "L3": along(x3)}
    if v_planet is None:
        return out
    vx, vy, vz = v_planet
    hx = ry * vz - rz * vy
    hy = rz * vx - rx * vz
    hz = rx * vy - ry * vx
    h = math.sqrt(hx * hx + hy * hy + hz * hz)
    if h < 1e-12:
        return out
    kx, ky, kz = hx / h, hy / h, hz / h
    out["L4"] = _rodrigues((rx, ry, rz), (kx, ky, kz), math.pi / 3.0)
    out["L5"] = _rodrigues((rx, ry, rz), (kx, ky, kz), -math.pi / 3.0)
    return out


def _rodrigues(
    v: tuple[float, float, float],
    k: tuple[float, float, float],
    ang: float,
) -> tuple[float, float, float]:
    cx, sx = math.cos(ang), math.sin(ang)
    vx, vy, vz = v
    kx, ky, kz = k
    dot = kx * vx + ky * vy + kz * vz
    cxv = (ky * vz - kz * vy, kz * vx - kx * vz, kx * vy - ky * vx)
    om = 1.0 - cx
    return (
        vx * cx + cxv[0] * sx + kx * dot * om,
        vy * cx + cxv[1] * sx + ky * dot * om,
        vz * cx + cxv[2] * sx + kz * dot * om,
    )
