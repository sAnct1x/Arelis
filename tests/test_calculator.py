"""The calculator had no tests at all, and two ways of being confidently wrong.

It is the tool whose whole job is "so the model does not invent numbers", and
before this file it returned `0.1 + 0.2 = 0.30000000000000004`, `100 * 1.1 =
110.00000000000001`, and `2e400 - 2e400 = nan` with ok=True. The arithmetic
tests below are the ones that matter; the parsing tests are about not wasting a
round trip on a question that has exactly one reading.
"""

from __future__ import annotations

import math

import pytest

from arelis.tools.calculator import (
    CalculatorTool,
    evaluate_expression,
    normalize_expression,
    present,
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
    [
        ("0.1 + 0.2", 0.3),
        ("0.1 + 0.2 - 0.3", 0),
        ("100 * 1.1", 110),
        ("1.1 * 1.1", 1.21),
        ("19.99 * 3", 59.97),
        ("0.1 * 3", 0.3),
        ("1.1 ** 2", 1.21),
        ("2.675 * 100", 267.5),
    ],
)
async def test_decimal_arithmetic_is_exact(calc, expression, expected):
    """Every one of these grew a binary tail before `Fraction` was used."""
    assert await _value(calc, expression) == expected


async def test_a_money_sum_does_not_grow_a_tail(calc):
    result = await calc.run(expression="24.99 + 5.01")
    assert result.output.endswith("= 30")
    assert "0000" not in result.output


async def test_the_tail_really_was_there_in_plain_python():
    """Guards the premise. If CPython ever makes 0.1+0.2 exact, the fix above
    is pointless and this file should say so rather than quietly agree."""
    assert 0.1 + 0.2 != 0.3


# --- inf and nan were successful results ------------------------------------


@pytest.mark.parametrize("expression", ["2e400", "-2e400"])
async def test_an_overflow_is_a_failure_not_an_answer(calc, expression):
    result = await calc.run(expression=expression)
    assert not result.ok
    assert "inf" not in result.output.lower().replace("infinity", "")


async def test_nan_is_never_returned(calc):
    result = await calc.run(expression="2e400 - 2e400")
    assert not result.ok
    assert "nan" not in result.output.lower()


async def test_the_overflow_message_forbids_inventing_a_number(calc):
    """The model's habit on a failed tool call is to answer from memory."""
    result = await calc.run(expression="2e400")
    assert "do not report a number" in result.output.lower()


def test_no_finite_expression_is_caught_by_the_overflow_check():
    assert math.isfinite(float(evaluate_expression("1e308")))


# --- exact arithmetic does not overflow, which is its own problem -----------


async def test_a_three_hundred_digit_answer_is_refused(calc):
    """`1e308 * 10` is no longer `inf`; it is a correct 309-digit integer and
    three hundred tokens of prompt that nobody can read."""
    result = await calc.run(expression="1e308 * 10 * 1e308")
    assert not result.ok
    assert "digits" in result.output


async def test_the_length_refusal_also_forbids_guessing(calc):
    result = await calc.run(expression="1e308 * 10 * 1e308")
    assert "from memory" in result.output


async def test_a_long_but_reasonable_answer_still_comes_back(calc):
    """factorial(100) is 158 digits and is a real answer someone asked for."""
    result = await calc.run(expression="factorial(100)")
    assert result.ok
    assert len(str(result.data["value"])) > 150


async def test_a_runaway_denominator_is_refused(calc):
    result = await calc.run(expression="1 / (3 ** 999 * 7 ** 999)")
    assert not result.ok


# --- repeating fractions ----------------------------------------------------


async def test_a_third_says_it_is_a_third(calc):
    result = await calc.run(expression="1/3")
    assert "0.3333333333333333" in result.output
    assert "exactly 1/3" in result.output


async def test_a_terminating_fraction_gets_no_note(calc):
    result = await calc.run(expression="1/4")
    assert result.output == "1/4 = 0.25"


async def test_a_whole_answer_is_shown_as_a_whole_number(calc):
    result = await calc.run(expression="10/5")
    assert result.output == "10/5 = 2"


def test_present_reduces_before_deciding():
    shown, exact = present(evaluate_expression("2/4"))
    assert shown == 0.5
    assert exact == ""


# --- the shapes people type -------------------------------------------------


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("15% of 84", 12.6),
        ("50% of 30", 15),
        ("30% off 59.99", 41.993),
        ("10% off 200", 180),
        ("$45.00 + $12.50", 57.5),
        ("1,250 + 300", 1550),
        ("20 x 5", 100),
        ("what is 8*7", 56),
        ("3 + 4 =", 7),
        ("calculate 6*7", 42),
        ("2 + 2 = ?", 4),
    ],
)
async def test_the_ways_people_write_it(calc, expression, expected):
    assert await _value(calc, expression) == expected


async def test_the_echo_shows_what_was_actually_computed(calc):
    """So a misread "30% off" is visible rather than hidden behind the input."""
    result = await calc.run(expression="30% off 100")
    assert "1 - 30/100" in result.output
    assert result.output.endswith("= 70")


async def test_an_unchanged_expression_is_echoed_as_typed(calc):
    result = await calc.run(expression="2*(3+4)")
    assert result.output == "2*(3+4) = 14"


# --- normalisation must not change an answer --------------------------------


async def test_a_comma_inside_a_call_is_still_an_argument(calc):
    """`max(1,250)` is two arguments. Reading it as 1250 would be silent and
    wrong, which is worse than not understanding a thousands separator."""
    assert await _value(calc, "max(1,250)") == 250
    assert await _value(calc, "round(1,250)") == 1


def test_thousands_stripping_only_happens_outside_a_call():
    assert normalize_expression("1,250 + 300") == "1250 + 300"
    assert "1,250" in normalize_expression("max(1,250) + 1")


def test_an_x_between_numbers_is_multiplication_not_a_name():
    assert normalize_expression("20 x 5") == "20*5"


def test_an_x_inside_a_word_is_left_alone():
    assert normalize_expression("exp(2)") == "exp(2)"
    assert normalize_expression("max(3,4)") == "max(3,4)"


def test_percent_of_binds_the_whole_right_hand_side():
    assert evaluate_expression("10% of 50 + 50") == 55
    assert evaluate_expression("10% of (50 + 50)") == 10


# --- naming the tool that can do it -----------------------------------------


@pytest.mark.parametrize(
    "expression,wanted",
    [
        ("5 miles in km", "units"),
        ("1 GB to MB", "units"),
        ("solve x**2 - 4", "cas"),
        ("integrate x**2", "cas"),
        ("12 choose 3", "factorial"),
        ("2*x + 3 = 7", "cas"),
    ],
)
async def test_a_refusal_names_the_next_step(calc, expression, wanted):
    """A bare "invalid syntax" leaves answering from memory as the only move."""
    result = await calc.run(expression=expression)
    assert not result.ok
    assert wanted in result.output


async def test_a_script_still_points_at_python(calc):
    result = await calc.run(expression="v = 3\nprint(v*2)")
    assert not result.ok
    assert "python tool" in result.output


async def test_an_assignment_is_a_script_not_an_equation(calc):
    """`x = 4 + 1` exec-parses, so it is someone writing Python, not someone
    asking to solve for x. The script hint has to win over the '=' hint."""
    result = await calc.run(expression="x = 4 + 1")
    assert not result.ok
    assert "python tool" in result.output


async def test_send_arguments_still_name_send_sms(calc):
    result = await calc.run(to="someone", body="hi")
    assert not result.ok
    assert "send_sms" in result.output


# --- the safety rules that were already there -------------------------------


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo hi')",
        "().__class__",
        "open('x')",
        "eval('1')",
        "[1,2][0]",
        "lambda: 1",
        "print(1)",
    ],
)
async def test_the_sandbox_still_refuses_code(calc, expression):
    result = await calc.run(expression=expression)
    assert not result.ok


async def test_a_huge_exponent_is_refused(calc):
    result = await calc.run(expression="9**99999")
    assert not result.ok
    assert "exponent" in result.output


async def test_division_by_zero_is_named(calc):
    result = await calc.run(expression="1/0")
    assert not result.ok
    assert "zero" in result.output.lower()


async def test_division_by_zero_survives_the_fraction_path(calc):
    """Fraction raises its own ZeroDivisionError; the handler must still see
    one rather than a bare ValueError."""
    result = await calc.run(expression="5/(2-2)")
    assert not result.ok
    assert "zero" in result.output.lower()


# --- the everyday cases, so none of this broke them -------------------------


@pytest.mark.parametrize(
    "expression,expected",
    [
        ("2*(3+4)", 14),
        ("2^10", 1024),
        ("5!", 120),
        ("factorial(5)", 120),
        ("10 % 3", 1),
        ("-7 // 2", -4),
        ("abs(-3)", 3),
        ("min(4, 9)", 4),
        ("round(3.14159, 2)", 3.14),
        ("1e3 + 1", 1001),
        ("log(8, 2)", 3),
    ],
)
async def test_the_ordinary_cases_still_answer(calc, expression, expected):
    assert await _value(calc, expression) == expected


async def test_irrational_functions_still_give_floats(calc):
    value = await _value(calc, "sqrt(2)*pi")
    assert abs(value - 4.442882938158366) < 1e-12


async def test_the_result_is_json_safe(calc):
    """`data` is published on the event bus; a Fraction would not survive it."""
    import json

    for expression in ["1/3", "0.1+0.2", "7", "sqrt(2)"]:
        result = await calc.run(expression=expression)
        json.dumps(result.data)
