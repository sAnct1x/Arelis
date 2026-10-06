"""A date or event written with slashes must never be computed as division."""
from __future__ import annotations

import pytest

from arelis.core.turn_context import TurnContext
from arelis.core.turn_prepare import _prepare_calculator_first_move
from arelis.tools.calculator import evaluate_expression


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


@pytest.mark.parametrize("ask", ["what is 10/5/2026", "10/5/2026", "what is 10/5/2026?"])
def test_three_part_date_is_not_computed(ask: str) -> None:
    assert not _armed_division(ask), f"{ask!r} was armed as division"


@pytest.mark.parametrize("ask", ["what is 3/4", "what is 3/4?", "what is 22/7?"])
def test_plain_fraction_ask_still_computes(ask: str) -> None:
    assert _armed_division(ask)
