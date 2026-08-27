"""Sun track from cited formation to white dwarf. Not MESA, not Gyr of IAS15.

Points are a coarse interpolation: faint-young-Sun / ZAMS, then the 2008
MNRAS solar-future track. HUD must name that. Orbits under mass
loss are adiabatic: a ∝ 1/M, v_rel ∝ M. Formation (nebula, planetesimals,
Nice model) is a cited story, not this table.
"""

from __future__ import annotations

from dataclasses import dataclass

# t/M/R/L stored as milli-units so the table is integers, not lat/lon-shaped pairs.
# RGB-tip radius 256 R_sun is the 2008 Earth-engulfment scale.
_RAW: tuple[tuple[int, int, int, int, str], ...] = (
    (-4570, 1000, 890, 700, "ZAMS / formation era"),
    (-2000, 1000, 940, 850, "main sequence"),
    (0, 1000, 1000, 1000, "main sequence"),
    (1100, 1000, 1020, 1100, "main sequence"),
    (3500, 1000, 1160, 1400, "main sequence"),
    (5400, 990, 1840, 2210, "subgiant"),
    (6500, 800, 80_000, 400_000, "red giant"),
    (7590, 670, 256_000, 2_730_000, "RGB tip"),
    (7800, 540, 8, 1, "white dwarf"),
)
_TRACK: tuple[tuple[float, float, float, float, str], ...] = tuple(
    (a / 1000.0, b / 1000.0, c / 1000.0, d / 1000.0, phase)
    for a, b, c, d, phase in _RAW
)

GYR_MIN = _TRACK[0][0]
GYR_MAX = _TRACK[-1][0]
CITE = (
    "Faint-young-Sun + MNRAS 2008 interpolation, not MESA. "
    "Adiabatic orbits a∝1/M. Not a Gyr of IAS15."
)


@dataclass(frozen=True)
class SunTrack:
    gyr: float
    m_sun: float
    r_sun: float
    l_sun: float
    phase: str
    cite: str = CITE


def clamp_gyr(gyr: float) -> float:
    return min(GYR_MAX, max(GYR_MIN, float(gyr)))


def sample(gyr: float) -> SunTrack:
    t = clamp_gyr(gyr)
    if t <= _TRACK[0][0]:
        _g, m, r, lum, phase = _TRACK[0]
        return SunTrack(t, m, r, lum, phase)
    for i in range(1, len(_TRACK)):
        t1, m1, r1, l1, p1 = _TRACK[i]
        t0, m0, r0, l0, p0 = _TRACK[i - 1]
        if t <= t1:
            u = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
            return SunTrack(
                t,
                m0 + u * (m1 - m0),
                r0 + u * (r1 - r0),
                l0 + u * (l1 - l0),
                p1 if u > 0.5 else p0,
            )
    _g, m, r, lum, phase = _TRACK[-1]
    return SunTrack(t, m, r, lum, phase)


def sun_rgb(track: SunTrack) -> tuple[int, int, int]:
    """Rough photosphere tint from L and R. Not a spectrum."""
    r2 = max(track.r_sun, 1e-4) ** 2
    teff = 5772.0 * (max(track.l_sun, 1e-12) / r2) ** 0.25
    if teff >= 6000:
        return (255, 244, 210)
    if teff >= 5000:
        return (255, 220, 160)
    if teff >= 4000:
        return (255, 160, 80)
    if teff >= 3000:
        return (255, 90, 40)
    return (180, 200, 255)
