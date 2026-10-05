"""Spoken year / day / orbital-period asks must go through real arithmetic.

Night-theme social check: Kepler years from the calculator, then a days
figure (4307) that was 11.8*365, not 11.86*365.25, plus an unsolicited
Martian-birthday story. These tests pin the deterministic path, not a
prompt patch for Jupiter or Mars.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from arelis.core.claims import (
    detect_exactness_need,
    detect_math_ask,
    duration_days_claim_missing_kinds,
)
from arelis.core.evidence import EvidenceLedger
from arelis.core.loop_helpers import _exactness_finish_refuse
from arelis.core.turn_context import TurnContext
from arelis.core.turn_prepare import _prepare_calculator_first_move
from arelis.tools.calculator import evaluate_expression

# Mean heliocentric a (AU). Same Kepler-III rewrite the calculator must use;
# tests compute days from this, they do not pin 4332 or 687 as literals.
_MARS_A_AU = 1.523679
_JUPITER_A_AU = 5.204267
_JULIAN_DAYS = 365.25


def _kepler_years(a_au: float) -> float:
    return math.sqrt(a_au**3)


def _kepler_days(a_au: float) -> float:
    return _kepler_years(a_au) * _JULIAN_DAYS


def _ctx(text: str) -> TurnContext:
    return TurnContext(
        text=text,
        role="fast",
        tool_names={"calculator"},
    )


# --- ask-side routing -------------------------------------------------------


@pytest.mark.parametrize(
    "ask",
    [
        "how many days is a year on jupiter",
        "if i was born on march 3 2004 how old am i in mars years",
        (
            "ok so like how long would a year feel if you lived on a planet "
            "out at 5.2 AU, in days i mean"
        ),
        "don't guess, how many earth days is 11.86 years",
        "that days number was wrong last time, how many days is 11.86 years",
        "how long is a year on a planet that's 5.2 AU from the sun?",
        "how long is a year on mars?",
    ],
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


def test_how_many_days_until_a_meeting_is_not_math() -> None:
    """Calendar waiting is not years-to-days arithmetic."""
    ask = "how many days until the review meeting on friday"
    assert not detect_math_ask(ask)


def test_calculator_preinjects_a_spoken_jupiter_year() -> None:
    text = "how many days is a year on jupiter"
    ctx = _ctx(text)
    _prepare_calculator_first_move(ctx, text)
    assert ctx.calculator_preinject == {"expression": text}


# --- calculator evaluation --------------------------------------------------


def test_eleven_point_eight_six_years_in_days_is_not_four_three_oh_seven() -> None:
    """11.86*365.25, not 11.8*365. The 4307 figure had no calculator warrant."""
    value = float(evaluate_expression("don't guess, how many earth days is 11.86 years"))
    expected = 11.86 * _JULIAN_DAYS
    assert value == pytest.approx(expected, rel=1e-9)
    assert abs(value - 4307) > 10


def test_kepler_days_at_five_point_two_au_come_from_sqrt() -> None:
    ask = (
        "ok so like how long would a year feel if you lived on a planet "
        "out at 5.2 AU, in days i mean"
    )
    value = float(evaluate_expression(ask))
    assert value == pytest.approx(_kepler_days(5.2), rel=1e-9)


def test_a_named_planet_year_in_days_uses_kepler_not_a_memorized_count() -> None:
    jupiter = float(evaluate_expression("how many days is a year on jupiter"))
    mars_years = float(evaluate_expression("how long is a year on mars?"))
    assert jupiter == pytest.approx(_kepler_days(_JUPITER_A_AU), rel=1e-6)
    assert mars_years == pytest.approx(_kepler_years(_MARS_A_AU), rel=1e-6)
    other = float(
        evaluate_expression(
            "how many days is a year on a planet that's 7.0 AU from the sun"
        )
    )
    assert other == pytest.approx(_kepler_days(7.0), rel=1e-9)


def test_mars_age_from_a_birthdate_divides_earth_years_by_the_kepler_year() -> None:
    ask = "if i was born on march 3 2004 how old am i in mars years"
    value = float(evaluate_expression(ask))
    earth_days = (date.today() - date(2004, 3, 3)).days
    expected = earth_days / (_JULIAN_DAYS * _kepler_years(_MARS_A_AU))
    assert value == pytest.approx(expected, rel=1e-9)


# --- answer-side: invented secondary days -----------------------------------


def test_a_days_parenthetical_without_a_tool_number_is_unsupported() -> None:
    """Screenshot: '11.86 years (≈4,307 days)' while the tool only had years."""
    missing = duration_days_claim_missing_kinds(
        "The calculator gave 11.86 years (≈4,307 days).",
        warrant_text="11.86",
    )
    assert missing == ["math"]
    missing_ok = duration_days_claim_missing_kinds(
        "The calculator gave 11.86 years (about 4332 days).",
        warrant_text="4331.865",
    )
    assert missing_ok == []


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
