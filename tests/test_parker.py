"""Parker 1958 quiet wind + Shue ram pressure. Not MHD, not ENLIL."""

from __future__ import annotations

import math

import pytest

from arelis.physics.attitude import sun_pole_ecliptic
from arelis.physics.constants import AU_M, BODY_BY_NAME
from arelis.physics.parker import (
    CITE,
    HELIOPAUSE_AU,
    R_SOURCE_RSUN,
    dynamic_pressure_npa,
    heliopause_ring,
    shue_standoff,
    spiral_points,
)


def test_quiet_ram_at_1au_is_a_few_npa() -> None:
    p = dynamic_pressure_npa(AU_M)
    assert 1.0 < p < 3.0


def test_shue_quiet_standoff_near_10_re() -> None:
    r0, alpha = shue_standoff(2.0, bz_nt=0.0)
    assert r0 == pytest.approx(10.3, abs=0.4)
    assert 0.5 < alpha < 0.7


def test_spiral_lies_in_the_solar_equator() -> None:
    r_sun = BODY_BY_NAME["Sun"].radius
    pts = spiral_points(0.0, R_SOURCE_RSUN * r_sun, AU_M, 2_451_545.0)
    pole = sun_pole_ecliptic()
    assert pts.shape[0] >= 8
    for row in pts:
        radial = math.hypot(*row)
        assert radial > 0.0
        assert abs(sum(a * b for a, b in zip(row, pole, strict=True))) < 1e-6 * radial


def test_heliopause_is_voyager_scale() -> None:
    assert HELIOPAUSE_AU == 120.0
    ring = heliopause_ring(HELIOPAUSE_AU * AU_M, 2_451_545.0)
    r = math.hypot(*ring[0])
    assert r == pytest.approx(HELIOPAUSE_AU * AU_M, rel=1e-6)


def test_cite_does_not_claim_mhd_or_enlil() -> None:
    low = CITE.lower()
    assert "parker 1958" in low
    assert "not mhd" in low
    assert "not enlil" in low
    assert "voyager" in low
