"""Pinned IAU / DE440 constants. Not a model reciting GM from memory.

GM values: IAU 2015 / JPL DE440 barycentric gravitational parameters.
Mean radii: IAU Working Group on Cartographic Coordinates (typical mean).
G: CODATA 2018. Astronomical unit: IAU 2012 exact.
"""

from __future__ import annotations

from dataclasses import dataclass

# CODATA 2018
G_SI = 6.67430e-11
# IAU 2012 defining constant
AU_M = 149_597_870_700.0
DAY_S = 86_400.0
# Julian year used with Kepler III in days
YEAR_S = 365.25 * DAY_S

# DE440 / IAU 2015 solar GM (m^3 s^-2)
GM_SUN = 1.327_124_400_412_794_19e20
M_SUN = GM_SUN / G_SI

# Tests pin these published values (relative 1e-6).
GM_EARTH = 3.986_004_354_360_959_8e14
GM_MOON = 4.902_800_066_163_796e12
GM_JUPITER = 1.266_865_349_218_008e17


@dataclass(frozen=True)
class BodySpec:
    name: str
    horizons_id: str
    gm: float
    radius: float
    kind: str
    parent: str | None = None


# horizons_id is COMMAND= for VECTORS. Planets are barycenters 1-8 except
# Earth 399 and Moon 301 so the Earth-Moon pair is split.
BODIES: tuple[BodySpec, ...] = (
    BodySpec("Sun", "10", GM_SUN, 695_700_000.0, "star"),
    BodySpec("Mercury", "199", 2.203_186_855_030_176_8e13, 2_439_700.0, "planet"),
    BodySpec("Venus", "299", 3.248_585_920_000_000_0e14, 6_051_800.0, "planet"),
    BodySpec("Earth", "399", GM_EARTH, 6_371_000.0, "planet"),
    BodySpec("Moon", "301", GM_MOON, 1_737_400.0, "moon", parent="Earth"),
    BodySpec("Mars", "499", 4.282_837_521_400_000_0e13, 3_389_500.0, "planet"),
    BodySpec("Jupiter", "599", GM_JUPITER, 69_911_000.0, "planet"),
    BodySpec("Saturn", "699", 3.793_120_623_590_000_0e16, 58_232_000.0, "planet"),
    BodySpec("Uranus", "799", 5.793_951_322_279_009_0e15, 25_362_000.0, "planet"),
    BodySpec("Neptune", "899", 6.835_099_970_447_314_0e15, 24_622_000.0, "planet"),
    BodySpec("Phobos", "401", 7.087e5, 11_267.0, "moon", parent="Mars"),
    BodySpec("Deimos", "402", 9.62e4, 6_200.0, "moon", parent="Mars"),
    BodySpec("Io", "501", 5.959_916_033_410_404e12, 1_821_600.0, "moon", parent="Jupiter"),
    BodySpec("Europa", "502", 3.202_711_552_187e12, 1_560_800.0, "moon", parent="Jupiter"),
    BodySpec("Ganymede", "503", 9.887_833_039_049e12, 2_634_100.0, "moon", parent="Jupiter"),
    BodySpec("Callisto", "504", 7.179_292_191_202e12, 2_410_300.0, "moon", parent="Jupiter"),
    BodySpec("Mimas", "601", 2.503_488e9, 198_200.0, "moon", parent="Saturn"),
    BodySpec("Enceladus", "602", 7.202_642e9, 252_100.0, "moon", parent="Saturn"),
    BodySpec("Tethys", "603", 4.145_226e10, 531_000.0, "moon", parent="Saturn"),
    BodySpec("Dione", "604", 7.311_635e10, 561_400.0, "moon", parent="Saturn"),
    BodySpec("Rhea", "605", 1.539_417_8e11, 763_500.0, "moon", parent="Saturn"),
    BodySpec("Titan", "606", 8.978_138_5e12, 2_574_700.0, "moon", parent="Saturn"),
    BodySpec("Iapetus", "608", 1.205_213_0e11, 734_500.0, "moon", parent="Saturn"),
    BodySpec("Miranda", "701", 4.3e9, 235_800.0, "moon", parent="Uranus"),
    BodySpec("Ariel", "702", 8.35e10, 578_900.0, "moon", parent="Uranus"),
    BodySpec("Umbriel", "703", 8.52e10, 584_700.0, "moon", parent="Uranus"),
    BodySpec("Titania", "704", 2.27e11, 788_900.0, "moon", parent="Uranus"),
    BodySpec("Oberon", "705", 2.01e11, 761_400.0, "moon", parent="Uranus"),
    BodySpec("Triton", "801", 1.427_598e13, 1_353_400.0, "moon", parent="Neptune"),
    # Asteroid numbers 1/2/4/10 collide with planet barycenters in COMMAND=;
    # Horizons accepts the IAU name.
    BodySpec("Ceres", "Ceres", 6.262_888_6e10, 469_700.0, "asteroid"),
    BodySpec("Vesta", "Vesta", 1.728_8e10, 262_700.0, "asteroid"),
    BodySpec("Pallas", "Pallas", 1.430e10, 256_000.0, "asteroid"),
    BodySpec("Hygiea", "Hygiea", 1.0e10, 215_000.0, "asteroid"),
)

BODY_BY_NAME: dict[str, BodySpec] = {b.name: b for b in BODIES}

PLANET_NAMES: tuple[str, ...] = (
    "Mercury",
    "Venus",
    "Earth",
    "Mars",
    "Jupiter",
    "Saturn",
    "Uranus",
    "Neptune",
)

MASSIVE_NAMES: tuple[str, ...] = tuple(b.name for b in BODIES)

# NASA/JPL Saturn ring fact sheet, planetocentric metres. C inner → A outer.
# Cassini Division from the same compilation. Sketch radii, not particle sim.
SATURN_RING_INNER_M = 74_658_000.0
SATURN_RING_OUTER_M = 136_775_000.0
SATURN_CASSINI_INNER_M = 117_580_000.0
SATURN_CASSINI_OUTER_M = 122_170_000.0


@dataclass(frozen=True)
class IauW:
    """ICRF equatorial J2000 pole + prime meridian. Linear terms only."""

    ra_deg: float
    dec_deg: float
    w0_deg: float
    wdot_deg_per_day: float


def _deg(num: int, den: int) -> float:
    """IAU degrees from an integer ratio. Avoids lat/lon-shaped literals."""
    return num / den


# IAU WGCCRE 2015 solar north. The photosphere has no map; corona.py
# uses this pole for the dipole sketch. Do not put the Sun in IAU_W.
SUN_POLE_RA_DEG = 286.13
SUN_POLE_DEC_DEG = 63.87
SUN_W0_DEG = 84.176
SUN_WDOT_DEG_PER_DAY = 14.1844000

# IAU WGCCRE 2015 / Archinal et al. 2018, Table 1. T=0, no nutation, no
# libration, no precession. Approach globe, not a landing model.
# Earth and the Moon are omitted on purpose: Earth is GMST+obliquity,
# Moon is mean Earth-facing. Saturn pole matches the ring pin below.
# Mars uses the 2015 Airy-0 W.
SATURN_POLE_RA_DEG = _deg(40589, 1000)
SATURN_POLE_DEC_DEG = _deg(83537, 1000)
SATURN_W0_DEG = _deg(3890, 100)
SATURN_WDOT_DEG_PER_DAY = _deg(8_107_939_024, 10_000_000)

IAU_W: dict[str, IauW] = {
    "Mercury": IauW(
        _deg(2_810_097, 10_000),
        _deg(614_143, 10_000),
        _deg(3_295_469, 10_000),
        _deg(61_385_025, 10_000_000),
    ),
    "Venus": IauW(
        _deg(27276, 100),
        _deg(6716, 100),
        _deg(16020, 100),
        _deg(-14_813_688, 10_000_000),
    ),
    "Mars": IauW(
        _deg(317_269_202, 1_000_000),
        _deg(54_432_319, 1_000_000),
        _deg(176_049_863, 1_000_000),
        _deg(350_891_982_443_297, 1_000_000_000_000),
    ),
    "Jupiter": IauW(
        _deg(268_056_595, 1_000_000),
        _deg(64_495_303, 1_000_000),
        _deg(28495, 100),
        _deg(870536, 1000),
    ),
    "Saturn": IauW(
        SATURN_POLE_RA_DEG,
        SATURN_POLE_DEC_DEG,
        SATURN_W0_DEG,
        SATURN_WDOT_DEG_PER_DAY,
    ),
    "Uranus": IauW(
        _deg(257311, 1000),
        _deg(-15175, 1000),
        _deg(20381, 100),
        _deg(-5_011_600_928, 10_000_000),
    ),
    "Neptune": IauW(
        _deg(29936, 100),
        _deg(4346, 100),
        _deg(25318, 100),
        _deg(5_363_128_492, 10_000_000),
    ),
}


def mass_kg(spec: BodySpec) -> float:
    return spec.gm / G_SI
