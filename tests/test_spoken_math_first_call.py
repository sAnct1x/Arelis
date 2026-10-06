"""#113: spoken math must evaluate on the first calculator call.

The preinject used to arm the raw sentence. normalize_expression stripped
"what is" but left "times" / "plus" / tip filler / "?", so the first call
failed and burned a whole model round.
"""

from __future__ import annotations

import pytest

from arelis.core.turn_context import TurnContext
from arelis.core.turn_prepare import _prepare_calculator_first_move
from arelis.tools.calculator import CalculatorTool, evaluate_expression


def _ctx(text: str) -> TurnContext:
    return TurnContext(text=text, role="fast", tool_names={"calculator"})


@pytest.mark.parametrize(
    "ask,expected",
    [
        ("What is 17 times 23?", 391),
        ("what's 15% of 240 for the tip?", 36),
        ("whats 120 divided by 8", 15),
        ("how much is 45 plus 17?", 62),
    ],
)
async def test_spoken_math_first_calculator_call_succeeds(ask: str, expected: int) -> None:
    """The first armed calculator call must evaluate; it must not fail."""
    ctx = _ctx(ask)
    _prepare_calculator_first_move(ctx, ask)
    assert ctx.calculator_preinject is not None, f"should arm calculator for {ask!r}"
    expression = str(ctx.calculator_preinject.get("expression") or "")
    assert expression, "preinject must carry an expression"

    result = await CalculatorTool().run(expression=expression)
    assert result.ok, f"first call failed for {ask!r}: {result.output}"
    value = evaluate_expression(expression)
    assert float(value) == pytest.approx(float(expected), rel=1e-9)
    assert str(expected) in result.output or f"{expected}." in result.output


async def test_junk_that_cannot_become_math_is_not_preinjected() -> None:
    """A guaranteed-fail preinject is worse than letting the model write the call."""
    ask = "what is 17 times the meaning of life please?"
    ctx = _ctx(ask)
    _prepare_calculator_first_move(ctx, ask)
    # Either not armed, or armed with something that actually evaluates.
    if ctx.calculator_preinject is None:
        return
    expression = str(ctx.calculator_preinject.get("expression") or "")
    result = await CalculatorTool().run(expression=expression)
    assert result.ok, f"armed a guaranteed failure: {result.output}"
