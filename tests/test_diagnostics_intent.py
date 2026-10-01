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


def test_diagnostics_matches_call():
    """'call diagnostics' should match (regression for P03)."""
    assert DIAGNOSTICS.matches("call diagnostics")
    assert DIAGNOSTICS.matches("Call the diagnostics tool")
    assert DIAGNOSTICS.matches("call the diagnostics tool with target=tests/test_units_temp.py")


def test_diagnostics_matches_use():
    """'use diagnostics' should match."""
    assert DIAGNOSTICS.matches("use diagnostics")
    assert DIAGNOSTICS.matches("Use the diagnostics tool")


def test_diagnostics_matches_run_tests():
    """'run the tests' should match."""
    assert DIAGNOSTICS.matches("run the tests")
    assert DIAGNOSTICS.matches("run tests")
    assert DIAGNOSTICS.matches("run the test suite")


def test_diagnostics_matches_with_target():
    """Diagnostics prompts with target specifications should match."""
    assert DIAGNOSTICS.matches("Run the diagnostics tool with target test_units_temp and report the result.")
    assert DIAGNOSTICS.matches("Call the diagnostics tool with target=tests/test_units_temp.py and report the pass count.")


def test_diagnostics_rejects_negation():
    """Negations should not match."""
    assert not DIAGNOSTICS.matches("don't run diagnostics")
    assert not DIAGNOSTICS.matches("can't run the tests")
    assert not DIAGNOSTICS.matches("never run diagnostics")


def test_diagnostics_rejects_on_qualifier():
    """'run diagnostics on my car' should not match."""
    assert not DIAGNOSTICS.matches("run diagnostics on my car")
    assert not DIAGNOSTICS.matches("run the tests on the staging server")
