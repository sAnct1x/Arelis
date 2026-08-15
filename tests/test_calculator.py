"""AST-safe calculator tool — exact math, no filesystem or network."""

from __future__ import annotations

import math

import pytest

from arelis.tools import build_tool_registry
from arelis.tools.calculator import CalculatorTool, evaluate_expression
from arelis.workspace import WorkspaceRoots


def test_evaluate_basic_ops() -> None:
    assert evaluate_expression("2+3*4") == 14
    assert evaluate_expression("(2+3)*4") == 20
    assert evaluate_expression("2**3") == 8
    assert evaluate_expression("10%4") == 2
    assert evaluate_expression("10//3") == 3
    assert evaluate_expression("-5 + 2") == -3


def test_evaluate_safe_math_names() -> None:
    assert evaluate_expression("sqrt(9)") == 3.0
    assert abs(evaluate_expression("sin(pi/2)") - 1.0) < 1e-9
    assert evaluate_expression("abs(-3)") == 3
    assert evaluate_expression("round(2.6)") == 3


def test_rejects_unsafe_syntax() -> None:
    with pytest.raises(ValueError):
        evaluate_expression("__import__('os').system('echo hi')")
    with pytest.raises(ValueError):
        evaluate_expression("open('/etc/passwd')")
    with pytest.raises(ValueError):
        evaluate_expression("(lambda x: x)(1)")
    with pytest.raises(ValueError):
        evaluate_expression("''.join('ab')")


def test_rejects_huge_exponent() -> None:
    with pytest.raises(ValueError, match="exponent"):
        evaluate_expression("10**10000")


@pytest.mark.asyncio
async def test_tool_formats_integer_results() -> None:
    tool = CalculatorTool()
    result = await tool.run(expression="2*(3+4)")
    assert result.ok
    assert result.output == "2*(3+4) = 14"
    assert result.data["value"] == 14


@pytest.mark.asyncio
async def test_tool_reports_division_by_zero() -> None:
    tool = CalculatorTool()
    result = await tool.run(expression="1/0")
    assert not result.ok
    assert "zero" in result.output.lower()


@pytest.mark.asyncio
async def test_tool_missing_expression() -> None:
    tool = CalculatorTool()
    result = await tool.run()
    assert not result.ok


def test_calculator_is_always_registered(tmp_path) -> None:
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    registry = build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert registry.get("calculator") is not None
    assert not registry.needs_confirm("calculator", {"expression": "1+1"})


def test_float_near_integer_is_shown_as_int() -> None:
    assert math.isclose(float(evaluate_expression("0.1+0.2")), 0.3, rel_tol=1e-9)
