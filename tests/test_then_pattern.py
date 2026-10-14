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
