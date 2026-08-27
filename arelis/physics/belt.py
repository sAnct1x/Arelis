"""Main-belt tracers: debiased a,e,i with Kirkwood gaps. Massless. Not named rocks."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from arelis.physics.constants import AU_M, GM_JUPITER, GM_SUN

# Jupiter semi-major axis (AU), DE440-ish
A_JUPITER_AU = 5.20336301
# Mean-motion resonances n/n_J = p/q → a = a_J * (q/p)^(2/3)
KIRKWOOD_AU: tuple[float, ...] = tuple(
    A_JUPITER_AU * (q / p) ** (2.0 / 3.0)
    for p, q in ((3, 1), (5, 2), (7, 3), (2, 1))
)
GAP_WIDTH_AU = 0.045
A_MIN_AU = 2.10
A_MAX_AU = 3.30


@dataclass(frozen=True)
class Tracer:
    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    a: float
    e: float
    i: float
    label: str


def _in_gap(a_au: float) -> bool:
    return any(abs(a_au - gap) < GAP_WIDTH_AU for gap in KIRKWOOD_AU)


def sample_elements(rng: random.Random) -> tuple[float, float, float]:
    """a (m), e, i (rad). Rejects Kirkwood corridors."""
    for _ in range(10_000):
        a_au = rng.uniform(A_MIN_AU, A_MAX_AU)
        if _in_gap(a_au):
            continue
        e = min(0.35, abs(rng.gauss(0.12, 0.08)))
        i = abs(rng.gauss(math.radians(8.0), math.radians(6.0)))
        i = min(i, math.radians(30.0))
        return a_au * AU_M, e, i
    raise RuntimeError("belt sampler could not miss Kirkwood gaps")


def state_from_elements(
    a: float,
    e: float,
    inc: float,
    *,
    raan: float,
    argp: float,
    ta: float,
    mu: float = GM_SUN,
) -> tuple[float, float, float, float, float, float]:
    p = a * (1.0 - e * e)
    r = p / (1.0 + e * math.cos(ta))
    x_orb = r * math.cos(ta)
    y_orb = r * math.sin(ta)
    vr = math.sqrt(mu / p) * e * math.sin(ta)
    vth = math.sqrt(mu / p) * (1.0 + e * math.cos(ta))
    # Perifocal to ecliptic
    cw, sw = math.cos(argp), math.sin(argp)
    ci, si = math.cos(inc), math.sin(inc)
    co, so = math.cos(raan), math.sin(raan)
    r11 = co * cw - so * sw * ci
    r12 = -co * sw - so * cw * ci
    r21 = so * cw + co * sw * ci
    r22 = -so * sw + co * cw * ci
    r31 = sw * si
    r32 = cw * si
    x = r11 * x_orb + r12 * y_orb
    y = r21 * x_orb + r22 * y_orb
    z = r31 * x_orb + r32 * y_orb
    vx_o = vr * math.cos(ta) - vth * math.sin(ta)
    vy_o = vr * math.sin(ta) + vth * math.cos(ta)
    vx = r11 * vx_o + r12 * vy_o
    vy = r21 * vx_o + r22 * vy_o
    vz = r31 * vx_o + r32 * vy_o
    return x, y, z, vx, vy, vz


def generate_tracers(n: int = 800, *, seed: int = 20260824) -> list[Tracer]:
    rng = random.Random(int(seed))
    n = min(max(int(n), 0), 5_000)
    out: list[Tracer] = []
    for k in range(n):
        a, e, inc = sample_elements(rng)
        raan = rng.uniform(0.0, 2.0 * math.pi)
        argp = rng.uniform(0.0, 2.0 * math.pi)
        ta = rng.uniform(0.0, 2.0 * math.pi)
        x, y, z, vx, vy, vz = state_from_elements(
            a, e, inc, raan=raan, argp=argp, ta=ta
        )
        out.append(
            Tracer(
                x=x,
                y=y,
                z=z,
                vx=vx,
                vy=vy,
                vz=vz,
                a=a,
                e=e,
                i=inc,
                label=f"belt particle {k}",
            )
        )
    return out


def kirkwood_au() -> tuple[float, ...]:
    return KIRKWOOD_AU


def jupiter_gm() -> float:
    return GM_JUPITER
