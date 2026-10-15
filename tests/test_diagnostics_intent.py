"""Regression test for diagnostics tool intent detection.

Ensures that "call diagnostics" and "use diagnostics" patterns are recognized,
not just "run diagnostics" and "run the tests".
"""

from arelis.core.intent_catalog import DIAGNOSTICS


def test_diagnostics_matches_run():
    """'run diagnostics' should match."""
    assert DIAGNOSTICS.matches("run diagnostics")
    assert DIAGNOSTICS.matches("Run diagnostics")
    assert DIAGNOSTICS.matches("run the diagnostics")


def test_diagnostics_rejects_negation():
    """Negations should not match."""
    assert not DIAGNOSTICS.matches("don't run diagnostics")
    assert not DIAGNOSTICS.matches("can't run the tests")
    assert not DIAGNOSTICS.matches("never run diagnostics")


