"""Spoken year / day / orbital-period asks must go through real arithmetic.

Night-theme social check: Kepler years from the calculator, then a days
figure (4307) that was 11.8*365, not 11.86*365.25, plus an unsolicited
Martian-birthday story. These tests pin the deterministic path, not a
prompt patch for Jupiter or Mars.
"""

from __future__ import annotations

import math

import pytest

from arelis.core.claims import (
    detect_exactness_need,
    detect_math_ask,
)
from arelis.core.evidence import EvidenceLedger
from arelis.core.loop_helpers import _exactness_finish_refuse
from arelis.tools.calculator import (
    evaluate_expression,
    normalize_expression,
    rewrite_spoken_duration,
)

# Mean heliocentric a (AU) for anonymous "planet at N AU" Kepler-III only.
_JULIAN_DAYS = 365.25
_EARTH_SIDEREAL_DAYS = 365.256
# NASA planetary fact sheet sidereal orbit periods, Earth days.
# https://nssdc.gsfc.nasa.gov/planetary/factsheet/
_NASA_SIDEREAL_DAYS: dict[str, float] = {
    "mercury": 87.969,
    "venus": 224.701,
    "mars": 686.980,
    "jupiter": 4332.589,
    "saturn": 10759.22,
    "uranus": 30685.4,
    "neptune": 60189,
    "pluto": 90560,
}


def _kepler_years(a_au: float) -> float:
    return math.sqrt(a_au**3)


def _kepler_days(a_au: float) -> float:
    return _kepler_years(a_au) * _JULIAN_DAYS


# --- ask-side detection -----------------------------------------------------


@pytest.mark.parametrize(
    "ask",
    ['how many days is a year on jupiter', 'if i was born on march 3 2004 how old am i in mars years'],
)
def test_spoken_orbit_and_duration_asks_are_math(ask: str) -> None:
    """Natural duration / age / year-day / orbital asks must arm exactness.

    Measured False on this checkout before the fix: detect_math_ask never
    treated these as calculator asks, so calculator-first never fired.
    """
    assert detect_math_ask(ask)
    need = detect_exactness_need(ask)
    assert need.needs_calculator
    assert "math" in need.kinds


def test_a_rant_about_days_is_still_not_math() -> None:
    """'2-3 days' in a story is not a year conversion."""
    rant = (
        "everytime i come up with a plan it takes like an hour and then "
        "2-3 days of testing. how old is this codebase anyway."
    )
    assert not detect_math_ask(rant)
    assert not detect_exactness_need(rant).needs_calculator


# --- calculator evaluation --------------------------------------------------


def test_saturn_year_days_is_nasa_sidereal_not_kepler_mean_a() -> None:
    """Mean-a Kepler is ~10833.7 d; NASA sidereal is 10759.22 d."""
    saturn_a = 9.582017
    kepler_days = _kepler_days(saturn_a)
    value = float(evaluate_expression("how many days is a year on saturn"))
    assert abs(kepler_days - 10759.22) > 50
    assert abs(value - kepler_days) > 50
    assert value == pytest.approx(10759.22, rel=1e-9)


def test_raw_math_expression_is_not_rewritten_by_spoken_duration() -> None:
    assert rewrite_spoken_duration("11.86*365.25") is None
    assert rewrite_spoken_duration("sqrt(5.2**3)") is None
    assert normalize_expression("11.86*365.25") == "11.86*365.25"
    assert normalize_expression("sqrt(5.2**3)") == "sqrt(5.2**3)"


# --- answer-side: invented secondary days -----------------------------------


def test_finish_refuses_an_invented_year_to_day_figure() -> None:
    from arelis.core.claims import ExactnessNeed

    ledger = EvidenceLedger()
    ledger.add(source="calculator", kind="calc", span="11.86", ok=True)
    refuse = _exactness_finish_refuse(
        "The calculator gave 11.86 years (≈4,307 days).",
        exact_need=ExactnessNeed(True, False, False, False, kinds=("math",)),
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
    )
    assert refuse is not None
    assert "calculator" in refuse.lower() or "don't know" in refuse.lower()
    assert "4307" not in refuse
