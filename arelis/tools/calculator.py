"""Deterministic arithmetic — so the model does not invent numbers."""

from __future__ import annotations

import ast
import math
import operator
from typing import Any

from arelis.tools.base import ToolResult

# Binary / unary ops only. No attribute access, no calls except safe math names.
_BINOPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARYOPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# send_sms argument names. Nothing here is ever part of an expression.
_SEND_KEYS = frozenset({"to", "body", "recipient", "phone", "message", "sms"})

_SAFE_FUNCS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "pi": math.pi,
    "e": math.e,
}


class CalculatorTool:
    name = "calculator"
    description = (
        "Evaluate a math expression exactly. Use for arithmetic, percentages, "
        "units of count, and simple science functions (sqrt, sin, log, …). "
        "Pass a plain expression like '2*(3+4)' or 'sqrt(2)*pi'. This is not "
        "a CAS — it cannot integrate, differentiate, or do symbolic algebra. "
        "Do not guess numeric answers when this tool can compute them."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Arithmetic expression to evaluate.",
            },
        },
        "required": ["expression"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        expression = str(kwargs.get("expression") or "").strip()
        if not expression:
            # A leftover SMS draft arriving as calculator(to=…, body=…) is not a
            # missing argument, it is the wrong tool. Saying so is the difference
            # between the model correcting itself and retrying the same call.
            stray = sorted(k for k in kwargs if k.lower() in _SEND_KEYS)
            if stray:
                return ToolResult(
                    ok=False,
                    output=(
                        f"Wrong tool: {', '.join(stray)} are send_sms arguments. "
                        "calculator only evaluates an arithmetic `expression`. "
                        "Call send_sms to text someone."
                    ),
                )
            return ToolResult(ok=False, output="Missing expression.")
        try:
            value = evaluate_expression(expression)
        except ZeroDivisionError:
            return ToolResult(ok=False, output="Division by zero.")
        except Exception as exc:
            return ToolResult(ok=False, output=f"Could not evaluate: {exc}")
        if isinstance(value, float) and value.is_integer():
            shown: Any = int(value)
        else:
            shown = value
        return ToolResult(
            ok=True,
            output=f"{expression} = {shown}",
            data={"expression": expression, "value": shown},
        )


def evaluate_expression(expression: str) -> float | int:
    """Eval a whitelist AST. Raises ValueError on anything unsafe."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression ({exc.msg})") from exc
    return _eval_node(tree.body)


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("only numbers are allowed")
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and (
            abs(float(left)) > 1e6 or abs(float(right)) > 1000
        ):
            raise ValueError("exponent too large")
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.Name):
        if node.id in _SAFE_FUNCS and not callable(_SAFE_FUNCS[node.id]):
            return _SAFE_FUNCS[node.id]
        raise ValueError(f"unknown name {node.id!r}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ValueError("only simple function calls are allowed")
        fn = _SAFE_FUNCS.get(node.func.id)
        if not callable(fn):
            raise ValueError(f"unknown function {node.func.id!r}")
        if node.keywords:
            raise ValueError("keyword arguments are not allowed")
        args = [_eval_node(a) for a in node.args]
        return fn(*args)
    raise ValueError(f"unsupported syntax: {type(node).__name__}")
