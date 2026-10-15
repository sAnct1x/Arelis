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


# --- slashes that are not division ------------------------------------------


@pytest.mark.parametrize(
    ("ask", "reply"),
    [('what was 9/11', 'It was an attack on a city.'), ("what's the plot of 1984", 'A clerk rewrites history under constant watch.')],
)
def test_dates_titles_and_store_hours_are_not_math(ask: str, reply: str) -> None:
    assert not detect_math_ask(ask)
    assert not detect_exactness_need(ask).needs_calculator
    refuse = _finish(ask, reply)
    assert refuse is None
    assert "calculator" not in (refuse or "").lower()


def test_divided_by_is_still_division() -> None:
    ask = "what is 9 divided by 11"
    assert detect_math_ask(ask)
    value = float(evaluate_expression(ask))
    assert value == pytest.approx(9 / 11, rel=1e-9)


# --- unit phrases that fell through to the filler line ----------------------


def test_how_many_km_is_five_miles() -> None:
    ask = "how many km is 5 miles"
    assert detect_units_ask(ask)
    line = asyncio.run(_spoken_units(ask))
    assert "8.05" in line
    assert "kilometer" in line
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


# --- a year at the start of a reply is not list item 1 ----------------------


