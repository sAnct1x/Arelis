"""Sun as a finite disk. Umbra, penumbra, earthshine."""

from __future__ import annotations

from arelis.physics.constants import AU_M, BODY_BY_NAME
from arelis.physics.light import earthshine_scale, occluders_for, sun_lit_at

R_SUN = BODY_BY_NAME["Sun"].radius
R_EARTH = BODY_BY_NAME["Earth"].radius
R_MOON = BODY_BY_NAME["Moon"].radius
_LUNAR_M = 384_399_000.0


def test_no_occluder_is_full_sun() -> None:
    assert sun_lit_at((AU_M, 0.0, 0.0), (0.0, 0.0, 0.0), []) == 1.0


def test_lunar_alignment_is_umbra() -> None:
    sun = (0.0, 0.0, 0.0)
    earth = (AU_M, 0.0, 0.0)
    moon = (AU_M + _LUNAR_M, 0.0, 0.0)
    frac = sun_lit_at(moon, sun, [(*earth, R_EARTH)])
    assert frac < 0.02


def test_quadrature_moon_is_fully_lit() -> None:
    sun = (0.0, 0.0, 0.0)
    earth = (AU_M, 0.0, 0.0)
    moon = (AU_M, _LUNAR_M, 0.0)
    frac = sun_lit_at(moon, sun, [(*earth, R_EARTH)])
    assert frac == 1.0


def test_penumbra_is_partial() -> None:
    sun = (0.0, 0.0, 0.0)
    earth = (AU_M, 0.0, 0.0)
    moon = (AU_M + _LUNAR_M, 6.5e6, 0.0)
    frac = sun_lit_at(moon, sun, [(*earth, R_EARTH)])
    assert 0.02 < frac < 0.98


def test_earthshine_is_bright_at_new_moon_and_dark_at_full() -> None:
    sun = (0.0, 0.0, 0.0)
    earth = (AU_M, 0.0, 0.0)
    new = (AU_M - _LUNAR_M, 0.0, 0.0)
    full = (AU_M + _LUNAR_M, 0.0, 0.0)
    assert earthshine_scale(new, earth, sun) > 0.02
    assert earthshine_scale(full, earth, sun) < 0.002


def test_occluders_keep_earth_for_the_moon() -> None:
    class _P:
        def __init__(self, name, x, y, z, radius, *, parent=None, tracer=False):
            self.name = name
            self.x, self.y, self.z = x, y, z
            self.radius = radius
            self.parent = parent
            self.tracer = tracer

    sun = _P("Sun", 0.0, 0.0, 0.0, R_SUN)
    earth = _P("Earth", AU_M, 0.0, 0.0, R_EARTH)
    moon = _P("Moon", AU_M + _LUNAR_M, 0.0, 0.0, R_MOON, parent="Earth")
    jup = _P("Jupiter", 5.2 * AU_M, 0.0, 0.0, BODY_BY_NAME["Jupiter"].radius)
    occ = occluders_for(
        "Moon",
        (moon.x, moon.y, moon.z),
        [sun, earth, moon, jup],
        sun,
        parent="Earth",
    )
    assert occ and occ[0][3] == R_EARTH
