"""A date or event written with slashes must never be computed as division."""
from __future__ import annotations

import re

import pytest

from arelis.core.turn_context import TurnContext
from arelis.core.turn_prepare import (
    _prepare_calculator_first_move,
    calculator_blocked_for_date_ask,
)
from arelis.tools.calculator import CalculatorTool, evaluate_expression

_NUMERIC_RESULT = re.compile(r"=\s*-?\d")


def _armed_division(ask: str) -> bool:
    ctx = TurnContext(text=ask, role="fast", tool_names={"calculator"})
    _prepare_calculator_first_move(ctx, ask)
    if ctx.calculator_preinject is None:
        return False
    try:
        evaluate_expression(str(ctx.calculator_preinject.get("expression") or ""))
    except Exception:
        return False
    return True


def _no_numeric_eval(expression: str) -> None:
    with pytest.raises(ValueError):
        evaluate_expression(expression)


async def _tool_refuses(expression: str) -> None:
    result = await CalculatorTool().run(expression=expression)
    assert result.ok is False, f"{expression!r} returned ok=True: {result.output}"
    assert "0.818" not in (result.output or "")
    assert not _NUMERIC_RESULT.search(result.output or ""), (
        f"{expression!r} still showed a numeric result: {result.output}"
    )


@pytest.mark.parametrize(
    "ask",
    [
        "what was 9/11",
        "what was 9/11?",
        "what was 12/25",
        "what was 7/4/1776?",
        "what was 10/5/2026",
    ],
)
def test_past_tense_date_or_event_is_not_computed(ask: str) -> None:
    assert not _armed_division(ask), f"{ask!r} was armed as division"
    _no_numeric_eval("9/11")


def _preinject_armed(ask: str) -> bool:
    ctx = TurnContext(text=ask, role="fast", tool_names={"calculator"})
    _prepare_calculator_first_move(ctx, ask)
    return ctx.calculator_preinject is not None


@pytest.mark.parametrize(
    "ask",
    [
        "what is 9/11",
        "what is 9/11?",
        "what is 12/25?",
    ],
)
def test_what_is_month_day_event_is_not_computed(ask: str, monkeypatch: pytest.MonkeyPatch) -> None:
    # Force evaluable so the preinject skip is the guard under test, not the
    # calculator refuse (the live path still needs both).
    monkeypatch.setattr(
        "arelis.tools.calculator.expression_is_evaluable",
        lambda _text: True,
    )
    assert not _preinject_armed(ask), f"{ask!r} was armed as division"
    monkeypatch.undo()
    _no_numeric_eval(ask)


@pytest.mark.parametrize(
    "ask",
    [
        "what happened on 9/11",
        "what happened on 9/11?",
    ],
)
def test_what_happened_on_slash_is_not_computed(ask: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "arelis.tools.calculator.expression_is_evaluable",
        lambda _text: True,
    )
    assert not _preinject_armed(ask), f"{ask!r} was armed as division"
    monkeypatch.undo()
    _no_numeric_eval("9/11")


@pytest.mark.parametrize("expression", ["9/11", "12/25", "7/4/1776"])
async def test_bare_calendar_slash_tool_refuses(expression: str) -> None:
    await _tool_refuses(expression)


async def test_percent_of_still_computes() -> None:
    ask = "What was 17% of 240 back then?"
    assert _armed_division(ask), f"{ask!r} should still arm calculator"
    value = evaluate_expression(ask)
    assert float(value) == pytest.approx(40.8, rel=1e-9)
    result = await CalculatorTool().run(expression=ask)
    assert result.ok
    assert "40.8" in result.output


@pytest.mark.parametrize(
    "ask",
    [
        "what is 22/7?",
        "what is 3/4 as a fraction?",
        "what is 22 divided by 7",
    ],
)
def test_plain_fraction_ask_still_computes(ask: str) -> None:
    assert _armed_division(ask), f"{ask!r} should still compute as a fraction"
    value = evaluate_expression(ask)
    assert float(value) > 0


@pytest.mark.parametrize("ask", ["what is 10/5/2026", "10/5/2026", "what is 10/5/2026?"])
def test_three_part_date_is_not_computed(ask: str) -> None:
    assert not _armed_division(ask), f"{ask!r} was armed as division"

def test_spoken_divided_by_calendar_slash_is_refused() -> None:
    with pytest.raises(ValueError, match='calendar date'):
        evaluate_expression('9 divided by 11')

@pytest.mark.parametrize(
    "ask,expr",
    [
        ("what is 9/11?", "9/11"),
        ("what is 9/11?", "9/11 as a decimal"),
        ("what is 9/11?", "9 divided by 11"),
        ("what was 9/11", "9/11"),
        ("what happened on 9/11", "9/11 as a fraction"),
    ],
)
def test_date_ask_blocks_ratio_even_with_math_cue(ask: str, expr: str) -> None:
    msg = calculator_blocked_for_date_ask(ask, expr)
    assert msg, f"expected block for {ask!r} / {expr!r}"
    assert "0.818" not in msg


def test_explicit_fraction_ask_is_not_blocked() -> None:
    assert calculator_blocked_for_date_ask("what is 9/11 as a decimal?", "9/11") is None

