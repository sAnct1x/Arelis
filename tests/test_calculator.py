"""The calculator had no tests at all, and two ways of being confidently wrong.

It is the tool whose whole job is "so the model does not invent numbers", and
before this file it returned `0.1 + 0.2 = 0.30000000000000004`, `100 * 1.1 =
110.00000000000001`, and `2e400 - 2e400 = nan` with ok=True. The arithmetic
tests below are the ones that matter; the parsing tests are about not wasting a
round trip on a question that has exactly one reading.
"""

from __future__ import annotations

import pytest

from arelis.tools.calculator import (
    CalculatorTool,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def calc() -> CalculatorTool:
    return CalculatorTool()


async def _value(calc: CalculatorTool, expression: str):
    result = await calc.run(expression=expression)
    assert result.ok, result.output
    return result.data["value"]


# --- the answers that used to be wrong --------------------------------------


@pytest.mark.parametrize(
    "expression,expected",
    [('0.1 + 0.2', 0.3), ('0.1 + 0.2 - 0.3', 0)],
)
async def test_decimal_arithmetic_is_exact(calc, expression, expected):
    """Every one of these grew a binary tail before `Fraction` was used."""
    assert await _value(calc, expression) == expected


# --- inf and nan were successful results ------------------------------------


@pytest.mark.parametrize("expression", ["2e400", "-2e400"])
async def test_an_overflow_is_a_failure_not_an_answer(calc, expression):
    result = await calc.run(expression=expression)
    assert not result.ok
    assert "inf" not in result.output.lower().replace("infinity", "")


# --- exact arithmetic does not overflow, which is its own problem -----------


async def test_a_three_hundred_digit_answer_is_refused(calc):
    """`1e308 * 10` is no longer `inf`; it is a correct 309-digit integer and
    three hundred tokens of prompt that nobody can read."""
    result = await calc.run(expression="1e308 * 10 * 1e308")
    assert not result.ok
    assert "digits" in result.output


@pytest.mark.parametrize("expression", ["sqrt(1e308)*1e300"])
async def test_the_float_path_can_still_overflow_and_is_still_caught(calc, expression):
    """Found by mutation: disabling the isfinite check broke nothing, because
    Fraction catches the obvious overflows at the literal. This one goes through
    a real function, comes back as float, and is why that check is not dead code."""
    result = await calc.run(expression=expression)
    assert not result.ok
    assert "range" in result.output or "overflow" in result.output


# --- repeating fractions ----------------------------------------------------


# --- the shapes people type -------------------------------------------------


# --- normalisation must not change an answer --------------------------------


# --- naming the tool that can do it -----------------------------------------


@pytest.mark.parametrize(
    "expression,wanted",
    [('5 miles in km', 'units'), ('1 GB to MB', 'units')],
)
async def test_a_refusal_names_the_next_step(calc, expression, wanted):
    """A bare "invalid syntax" leaves answering from memory as the only move."""
    result = await calc.run(expression=expression)
    assert not result.ok
    assert wanted in result.output


# --- the safety rules that were already there -------------------------------


@pytest.mark.parametrize(
    "expression",
    ["__import__('os').system('echo hi')", '().__class__'],
)
async def test_the_sandbox_still_refuses_code(calc, expression):
    result = await calc.run(expression=expression)
    assert not result.ok


async def test_a_huge_exponent_is_refused(calc):
    result = await calc.run(expression="9**99999")
    assert not result.ok
    assert "exponent" in result.output


# --- the everyday cases, so none of this broke them -------------------------


@pytest.mark.parametrize(
    "expression,expected",
    [('2*(3+4)', 14), ('2^10', 1024)],
)
async def test_the_ordinary_cases_still_answer(calc, expression, expected):
    assert await _value(calc, expression) == expected


