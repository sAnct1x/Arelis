"""Hohmann transfer between two circular coplanar orbits. Vis-viva only."""

from __future__ import annotations

import math
from dataclasses import dataclass

from arelis.physics.elements import kepler_period, vis_viva


@dataclass(frozen=True)
class Hohmann:
    r1: float
    r2: float
    a_t: float
    dv1: float
    dv2: float
    tof_s: float


def hohmann(r1: float, r2: float, mu: float) -> Hohmann:
    r1 = float(r1)
    r2 = float(r2)
    if r1 <= 0.0 or r2 <= 0.0 or mu <= 0.0:
        raise ValueError("Hohmann needs positive r1, r2, mu.")
    a_t = 0.5 * (r1 + r2)
    v1 = vis_viva(r1, r1, mu)
    v2 = vis_viva(r2, r2, mu)
    vp = vis_viva(r1, a_t, mu)
    va = vis_viva(r2, a_t, mu)
    tof = 0.5 * kepler_period(a_t, mu)
    return Hohmann(
        r1=r1,
        r2=r2,
        a_t=a_t,
        dv1=abs(vp - v1),
        dv2=abs(v2 - va),
        tof_s=tof,
    )


def circular_speed(r: float, mu: float) -> float:
    return math.sqrt(mu / r)
