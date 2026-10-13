"""Small math, unit, and reply misfires from the checklist.

The ask strings are the ones a person actually typed. Nothing in them names
a tool. Each test drives the parser, the detector, or the reply finisher.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from arelis.core.claims import detect_exactness_need, detect_math_ask, detect_units_ask
from arelis.core.evidence import EvidenceLedger
from arelis.core.failure_copy import chat_followup_from_tool
from arelis.core.loop_helpers import _exactness_finish_refuse
from arelis.tools.calculator import CalculatorTool, evaluate_expression
from arelis.tools.units import UnitsTool
from arelis.ui.markdown import render_markdown

_READY = "Ready when you are"


def _visible(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return (
        text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&").replace("&quot;", '"')
    )


async def _calc_value(expression: str):
    result = await CalculatorTool().run(expression=expression)
    assert result.ok, result.output
    return result.data["value"]


def _finish(ask: str, reply: str) -> str | None:
    return _exactness_finish_refuse(
        reply,
        exact_need=detect_exactness_need(ask),
        ledger=EvidenceLedger(),
        numeric_gate=True,
        evidence_gate=True,
    )


async def _spoken_units(ask: str) -> str:
    result = await UnitsTool().run(action="convert", quantity=ask)
    assert result.ok, result.output
    return chat_followup_from_tool("units", result.output, ask=ask)


# --- everyday phrasings -----------------------------------------------------


@pytest.mark.parametrize(
    ("ask", "expected"),
    [
        ("half of 250", 125),
        ("what is the square root of 144", 12),
        ("what is 2 to the power of 10", 1024),
        ("how many days in 3 weeks", 21),
    ],
)
async def test_everyday_math_phrasing_answers_on_the_first_try(ask: str, expected: int) -> None:
    assert await _calc_value(ask) == expected


def test_days_in_weeks_counts_as_math() -> None:
    ask = "how many days in 3 weeks"
    assert detect_math_ask(ask)
    assert detect_exactness_need(ask).needs_calculator


@pytest.mark.parametrize(
    "ask",
    [
        "what is 1500 + 2000",
        "1999 x 2",
        "square root of 1600",
        "what is 3/4",
        "what is 1/2",
        "what is 5/8",
    ],
)
def test_ordinary_sums_fractions_and_roots_stay_math(ask: str) -> None:
    """A year-shaped number or a short fraction is still arithmetic."""
    assert detect_math_ask(ask)


# --- slashes that are not division ------------------------------------------


@pytest.mark.parametrize(
    ("ask", "reply"),
    [
        ("what was 9/11", "It was an attack on a city."),
        ("what's the plot of 1984", "A clerk rewrites history under constant watch."),
        ("what is 10/12/2025", "That is a date in December."),
        ("is the store open 24/7?", "Yes, they stay open all day and all night."),
    ],
)
def test_dates_titles_and_store_hours_are_not_math(ask: str, reply: str) -> None:
    assert not detect_math_ask(ask)
    assert not detect_exactness_need(ask).needs_calculator
    refuse = _finish(ask, reply)
    assert refuse is None
    assert "calculator" not in (refuse or "").lower()


def test_a_clear_decimal_ask_still_divides() -> None:
    """Already true on this checkout. Guard so the slash skip does not eat it."""
    ask = "what's 9/11 as a decimal"
    assert detect_math_ask(ask)
    value = float(evaluate_expression(ask))
    assert value == pytest.approx(9 / 11, rel=1e-9)


def test_divided_by_is_still_division() -> None:
    ask = "what is 9 divided by 11"
    assert detect_math_ask(ask)
    value = float(evaluate_expression(ask))
    assert value == pytest.approx(9 / 11, rel=1e-9)


def test_a_plain_fraction_that_is_not_a_date_still_divides() -> None:
    value = float(evaluate_expression("what is 22/7?"))
    assert value == pytest.approx(22 / 7, rel=1e-9)


def test_a_log_question_is_still_math() -> None:
    assert detect_math_ask("what's log base 10 of 1000")


# --- unit phrases that fell through to the filler line ----------------------


def test_five_miles_in_km_is_a_real_answer() -> None:
    ask = "5 miles in km"
    assert detect_units_ask(ask)
    line = asyncio.run(_spoken_units(ask))
    assert line == "That works out to about 8.05 kilometers."
    assert _READY not in line


def test_how_many_km_is_five_miles() -> None:
    ask = "how many km is 5 miles"
    assert detect_units_ask(ask)
    line = asyncio.run(_spoken_units(ask))
    assert "8.05" in line
    assert "kilometer" in line
    assert _READY not in line


def test_how_many_centuries_is_three_hundred_years() -> None:
    ask = "how many centuries is 300 years?"
    assert detect_units_ask(ask)
    line = asyncio.run(_spoken_units(ask))
    assert line == "That works out to 3 centuries."
    assert _READY not in line


def test_how_far_is_a_light_year_in_km() -> None:
    ask = "how far is a light year in km?"
    assert detect_units_ask(ask)
    line = asyncio.run(_spoken_units(ask))
    assert line == "That works out to about 9.46 trillion kilometers."
    assert _READY not in line


def test_one_au_to_km_is_astronomical_not_absorbance() -> None:
    ask = "1 AU to km"
    assert detect_units_ask(ask)
    line = asyncio.run(_spoken_units(ask))
    assert line == "That works out to about 149.6 million kilometers."
    assert "absorbance" not in line.lower()
    assert _READY not in line


# --- the person's own numbers beat the Mars year ----------------------------


def test_mars_year_keeps_the_division_they_wrote() -> None:
    ask = "what is 687 days divided by 7 for a Mars year"
    value = float(evaluate_expression(ask))
    assert value == pytest.approx(687 / 7, rel=1e-9)
    assert abs(value - 686.98) > 10
    result = asyncio.run(CalculatorTool().run(expression=ask))
    assert result.ok, result.output
    line = chat_followup_from_tool("calculator", result.output, ask=ask)
    assert "98.1" in line
    assert "Earth days" not in line
    assert "686" not in line


def test_a_plain_mars_year_in_days_is_still_the_orbit() -> None:
    value = float(evaluate_expression("how many days is a year on Mars?"))
    assert value == pytest.approx(686.98, rel=1e-6)


# --- a year at the start of a reply is not list item 1 ----------------------


@pytest.mark.parametrize(
    ("src", "year", "rest"),
    [
        ("2026. That was the year...", "2026", "That was the year"),
        ("1969. That's when Apollo 11 landed.", "1969", "Apollo 11"),
    ],
)
def test_a_reply_that_starts_with_a_year_keeps_the_year(src: str, year: str, rest: str) -> None:
    html = render_markdown(src)
    visible = _visible(html)
    assert year in visible
    assert rest in visible
    assert "<ol" not in html


def test_a_real_numbered_list_is_still_a_list() -> None:
    html = render_markdown("1. Preheat the oven\n2. Mix the flour\n3. Bake")
    assert "<ol" in html
    assert html.count("<li>") == 3
    visible = _visible(html)
    assert "Preheat the oven" in visible
