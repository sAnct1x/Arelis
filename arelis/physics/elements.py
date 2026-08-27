"""Osculating Keplerian elements, Hill radius, sphere of influence."""

from __future__ import annotations

import math
from dataclasses import dataclass

from arelis.physics.constants import AU_M, GM_SUN


@dataclass(frozen=True)
class Elements:
    a: float
    e: float
    i: float
    raan: float
    argp: float
    true_anomaly: float
    period_s: float


def vis_viva(r: float, a: float, mu: float) -> float:
    return math.sqrt(max(0.0, mu * (2.0 / r - 1.0 / a)))


def kepler_period(a: float, mu: float) -> float:
    return 2.0 * math.pi * math.sqrt(max(a, 0.0) ** 3 / mu)


def hill_radius(a: float, m: float, m_star: float) -> float:
    """Circular Hill radius a (m_p / 3 M_star)^(1/3)."""
    if m_star <= 0.0 or m <= 0.0 or a <= 0.0:
        return 0.0
    return a * (m / (3.0 * m_star)) ** (1.0 / 3.0)


def sphere_of_influence(a: float, m: float, m_star: float) -> float:
    """Laplace SOI a (m / M_star)^(2/5)."""
    if m_star <= 0.0 or m <= 0.0 or a <= 0.0:
        return 0.0
    return a * (m / m_star) ** 0.4


def position_at_true_anomaly(el: Elements, nu: float) -> tuple[float, float, float]:
    """Inertial position on the osculating ellipse, same frame as the state."""
    p = el.a * (1.0 - el.e * el.e)
    r = p / (1.0 + el.e * math.cos(nu))
    cw = math.cos(el.argp + nu)
    sw = math.sin(el.argp + nu)
    c_om, s_om = math.cos(el.raan), math.sin(el.raan)
    ci, si = math.cos(el.i), math.sin(el.i)
    return (
        r * (c_om * cw - s_om * sw * ci),
        r * (s_om * cw + c_om * sw * ci),
        r * (sw * si),
    )


def osculating(
    r: tuple[float, float, float],
    v: tuple[float, float, float],
    mu: float = GM_SUN,
) -> Elements | None:
    """Heliocentric osculating elements. None if degenerate (escape, zero r)."""
    rx, ry, rz = r
    vx, vy, vz = v
    rmag = math.sqrt(rx * rx + ry * ry + rz * rz)
    v2 = vx * vx + vy * vy + vz * vz
    if rmag < 1.0 or mu <= 0.0:
        return None
    hx = ry * vz - rz * vy
    hy = rz * vx - rx * vz
    hz = rx * vy - ry * vx
    h = math.sqrt(hx * hx + hy * hy + hz * hz)
    if h < 1e-12:
        return None
    inc = math.acos(max(-1.0, min(1.0, hz / h)))
    n = math.sqrt(hx * hx + hy * hy)
    raan = math.atan2(hx, -hy) if n > 1e-12 else 0.0
    energy = v2 / 2.0 - mu / rmag
    if energy >= 0.0:
        return None
    a = -mu / (2.0 * energy)
    ex = (v2 - mu / rmag) * rx - (rx * vx + ry * vy + rz * vz) * vx
    ey = (v2 - mu / rmag) * ry - (rx * vx + ry * vy + rz * vz) * vy
    ez = (v2 - mu / rmag) * rz - (rx * vx + ry * vy + rz * vz) * vz
    ex /= mu
    ey /= mu
    ez /= mu
    e = math.sqrt(ex * ex + ey * ey + ez * ez)
    if n > 1e-12 and e > 1e-12:
        argp = math.atan2((hx * ey - hy * ex) / n, (hx * ex + hy * ey) * hz / (n * h) + ez)
    else:
        argp = 0.0
    if e > 1e-12:
        ta = math.acos(max(-1.0, min(1.0, (ex * rx + ey * ry + ez * rz) / (e * rmag))))
        if rx * vx + ry * vy + rz * vz < 0.0:
            ta = 2.0 * math.pi - ta
    else:
        ta = 0.0
    return Elements(
        a=a,
        e=e,
        i=inc,
        raan=raan,
        argp=argp,
        true_anomaly=ta,
        period_s=kepler_period(a, mu),
    )


def tisserand_jupiter(
    a: float,
    e: float,
    inc: float,
    a_jup: float = 5.203_363_01 * AU_M,
) -> float:
    """Tisserand parameter vs Jupiter (circular Jupiter)."""
    if a <= 0.0 or a_jup <= 0.0:
        return float("nan")
    return a_jup / a + 2.0 * math.sqrt(a / a_jup * max(0.0, 1.0 - e * e)) * math.cos(inc)
