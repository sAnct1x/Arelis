"""Regression test for temperature conversion refusal bug.

User report: "Convert 90 degrees Fahrenheit to Celsius." called units then
calculator, and the final answer was the refusal message "The units tool
couldn't convert or look that up. I will not recite CODATA or invent a
conversion." Expected answer is ~32.2°C.
"""

from __future__ import annotations

import asyncio

from arelis.core.claims import detect_exactness_need, detect_math_ask, detect_units_ask
from arelis.core.evidence import EvidenceLedger
from arelis.tools.calculator import CalculatorTool
from arelis.tools.units import UnitsTool


def test_temperature_conversion_detection() -> None:
    """Temperature conversion should detect as units, not math."""
    # "Convert..." phrasing
    text1 = "Convert 90 degrees Fahrenheit to Celsius."
    assert detect_units_ask(text1), "Should detect as units ask"
    assert not detect_math_ask(text1), "Should NOT detect as math ask"
    
    need1 = detect_exactness_need(text1)
    assert need1.needs_units, "Should need units"
    assert not need1.needs_calculator, "Should NOT need calculator"
    assert need1.kinds == ("units",), f"Expected ('units',), got {need1.kinds}"
    
    # "What is..." phrasing (previously detected as math, causing the bug)
    text2 = "What is 90 degrees Fahrenheit in Celsius?"
    assert detect_units_ask(text2), "Should detect as units ask"
    # This also matches math patterns, but conflict resolution should choose units
    
    need2 = detect_exactness_need(text2)
    assert need2.needs_units, "Should need units"
    assert not need2.needs_calculator, "Should NOT need calculator (units wins conflict)"
    assert need2.kinds == ("units",), f"Expected ('units',), got {need2.kinds}"


def test_units_tool_converts_temperature() -> None:
    """Units tool should successfully convert temperature."""
    tool = UnitsTool()
    
    # Test with separate arguments
    result = asyncio.run(
        tool.run(action="convert", quantity="90 degrees Fahrenheit", to="Celsius")
    )
    assert result.ok, f"Units should succeed, got: {result.output}"
    assert "32.2" in result.output, f"Should contain 32.2, got: {result.output}"
    assert result.data.get("value") is not None, "Should have value in data"
    value = float(result.data["value"])
    assert 32.0 < value < 32.5, f"Value should be ~32.2°C, got {value}"


def test_calculator_cannot_convert_temperature() -> None:
    """Calculator should fail on temperature conversion text."""
    tool = CalculatorTool()
    
    result = asyncio.run(
        tool.run(expression="Convert 90 degrees Fahrenheit to Celsius")
    )
    assert not result.ok, "Calculator should fail on temperature conversion text"


def test_units_succeeds_despite_calculator_failure() -> None:
    """Even if calculator is called and fails, units success should satisfy exactness."""
    text = "Convert 90 degrees Fahrenheit to Celsius."
    
    # Create ledger simulating both tools being called
    ledger = EvidenceLedger()
    
    # Units succeeds
    ledger.add(source="units", kind="units", span="32.22", ok=True)
    
    # Calculator fails
    ledger.add(source="calculator", kind="calc", span="invalid syntax", ok=False)
    
    # Get exactness need
    need = detect_exactness_need(text)
    assert need.kinds == ("units",), f"Expected ('units',), got {need.kinds}"
    
    # Check if exactness is satisfied
    assert ledger.has_ok("units"), "Ledger should have successful units"
    missing = ledger.missing_kinds(need.kinds)
    assert not missing, f"Units should satisfy exactness, but missing: {missing}"


def test_units_with_wrong_action_fails() -> None:
    """Units called with action=constant for a conversion should fail."""
    tool = UnitsTool()
    
    # If model calls units with wrong action
    result = asyncio.run(
        tool.run(action="constant", name="90 degrees Fahrenheit to Celsius")
    )
    assert not result.ok, "Units with action=constant should fail on conversions"
    assert "not" in result.output.lower() and "constant" in result.output.lower()
