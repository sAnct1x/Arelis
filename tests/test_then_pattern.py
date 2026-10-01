"""Test that 'then' checks don't block non-chaining uses."""

import re


def test_then_pattern_for_chaining() -> None:
    """The improved 'then' pattern should only match actual chaining."""
    pattern = re.compile(r"(?:[,;]\s+then\b|,\s+and\s+then\b)", re.I)

    # Should match: actual chaining
    assert pattern.search("Check inbox, then send email")
    assert pattern.search("Do X, then do Y")
    assert pattern.search("Calculate this; then plot it")
    assert pattern.search("Search, and then summarize")

    # Should NOT match: ordinary uses of "then"
    assert not pattern.search("What was the weather then?")
    assert not pattern.search("If so then calculate")
    assert not pattern.search("Since then the value changed")
    assert not pattern.search("Back then it was different")
    assert not pattern.search("Now and then check")
    assert not pattern.search("Search and then summarize")  # no comma before "and"

    # Edge case: "and then" WITH comma before should match
    assert pattern.search("Do this, and then do that")


def test_calculator_preinject_not_blocked_by_ordinary_then() -> None:
    """Calculator preinjection should work for non-chaining 'then' sentences."""
    from arelis.core.turn_context import TurnContext
    from arelis.core.turn_prepare import _prepare_calculator_first_move

    # Text with "then" but not chaining
    text = "What was 17% of 240 back then?"

    ctx = TurnContext(
        text=text,
        role="fast",
        speak=False,
        tool_names={"calculator"},
    )

    _prepare_calculator_first_move(ctx, text)

    # Should have calculator preinjection since it's not actually chaining
    assert ctx.calculator_preinject is not None, "Calculator should be preinjected for non-chaining 'then'"
    assert ctx.calculator_preinject.get("expression") == text


def test_calculator_preinject_blocked_by_chaining_then() -> None:
    """Calculator preinjection should be blocked for actual chaining."""
    from arelis.core.turn_context import TurnContext
    from arelis.core.turn_prepare import _prepare_calculator_first_move

    # Actual chaining
    text = "Summarize the CSV, then what is 10% of the row count?"

    ctx = TurnContext(
        text=text,
        role="fast",
        speak=False,
        tool_names={"calculator", "analyze"},
    )

    _prepare_calculator_first_move(ctx, text)

    # Should NOT have calculator preinjection for chaining
    assert ctx.calculator_preinject is None, "Calculator should not be preinjected for chaining 'then'"
