"""Offline ICs for pytest. Not a product load path."""

from __future__ import annotations

import math

from arelis.physics.constants import (
    AU_M,
    BODIES,
    BODY_BY_NAME,
    GM_SUN,
    PLANET_NAMES,
)
from arelis.physics.horizons import VectorState

# Mean heliocentric a. IAU / typical osculating, rounded. Pytest only.
_PLANET_A_AU: dict[str, float] = {
    "Mercury": 0.387099,
    "Venus": 0.723332,
    "Earth": 1.000000,
    "Mars": 1.523679,
    "Jupiter": 5.204267,
    "Saturn": 9.582017,
    "Uranus": 19.191264,
    "Neptune": 30.068963,
    "Ceres": 2.7675,
    "Vesta": 2.3615,
    "Pallas": 2.7721,
    "Hygiea": 3.139,
}

# Mean planetocentric a. IAU / typical. Pytest only.
_MOON_A_M: dict[str, float] = {
    "Moon": 384_399_000.0,
    "Phobos": 9_376_000.0,
    "Deimos": 23_463_000.0,
    "Io": 421_800_000.0,
    "Europa": 671_100_000.0,
    "Ganymede": 1_070_400_000.0,
    "Callisto": 1_882_700_000.0,
    "Mimas": 185_539_000.0,
    "Enceladus": 237_948_000.0,
    "Tethys": 294_619_000.0,
    "Dione": 377_396_000.0,
    "Rhea": 527_108_000.0,
    "Titan": 1_221_870_000.0,
    "Iapetus": 3_560_820_000.0,
    "Miranda": 129_390_000.0,
    "Ariel": 191_020_000.0,
    "Umbriel": 266_000_000.0,
    "Titania": 435_910_000.0,
    "Oberon": 583_520_000.0,
    "Triton": 354_759_000.0,
}


def sun_at_origin() -> VectorState:
    return VectorState(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, units="SI")


def circular_around_sun(name: str, a: float, *, nu: float = 0.0) -> VectorState:
    del name
    v = math.sqrt(GM_SUN / a)
    c, s = math.cos(nu), math.sin(nu)
    return VectorState(a * c, a * s, 0.0, -v * s, v * c, 0.0, units="SI")


def _around_parent(parent: VectorState, a: float, mu: float, nu: float) -> VectorState:
    v = math.sqrt(mu / max(a, 1.0))
    c, s = math.cos(nu), math.sin(nu)
    return VectorState(
        parent.x + a * c,
        parent.y + a * s,
        parent.z,
        parent.vx - v * s,
        parent.vy + v * c,
        parent.vz,
        units="SI",
    )


def sun_and_planet(name: str = "Earth", a: float = AU_M) -> dict[str, VectorState]:
    return {"Sun": sun_at_origin(), name: circular_around_sun(name, a)}


def circular_system() -> dict[str, VectorState]:
    """Sun, planets, catalog moons. Coplanar circles. Not Horizons."""
    states: dict[str, VectorState] = {"Sun": sun_at_origin()}
    for i, name in enumerate(PLANET_NAMES):
        a = _PLANET_A_AU[name] * AU_M
        nu = 2.0 * math.pi * i / len(PLANET_NAMES)
        states[name] = circular_around_sun(name, a, nu=nu)
    for name, a_au in _PLANET_A_AU.items():
        if name in states:
            continue
        spec = BODY_BY_NAME.get(name)
        if spec is None or spec.kind != "asteroid":
            continue
        nu = (sum(ord(c) for c in name) % 360) * math.pi / 180.0
        states[name] = circular_around_sun(name, a_au * AU_M, nu=nu)
    for spec in BODIES:
        if spec.kind != "moon" or spec.parent is None:
            continue
        parent = states.get(spec.parent)
        a = _MOON_A_M.get(spec.name)
        if parent is None or a is None:
            continue
        nu = (sum(ord(c) for c in spec.name) % 360) * math.pi / 180.0
        states[spec.name] = _around_parent(parent, a, spec_mu(spec.parent), nu)
    return states


def spec_mu(name: str) -> float:
    return BODY_BY_NAME[name].gm


def two_body_period(name: str, a: float) -> float:
    spec = BODY_BY_NAME[name]
    mu = GM_SUN + spec.gm
    return 2.0 * math.pi * math.sqrt(a**3 / mu)
