"""Deterministic arithmetic — so the model does not invent numbers.

Arithmetic runs on `Fraction`, not `float`. The docstring above has always said
"exactly", and on binary floats it was not: `0.1 + 0.2` came back as
`0.30000000000000004`, `100 * 1.1` as `110.00000000000001`, and
`0.1 + 0.2 - 0.3` as `5.55e-17` rather than zero. Those are the answers this
tool exists to stop the model producing, and it was producing them itself. A
decimal literal is read as the decimal that was written — `Fraction(str(0.1))`
is one tenth — so the sums come out right and money stops growing a tail.

Floats are still used the moment a real function is involved: `sqrt`, `sin` and
`log` have no rational answer and pretending otherwise would be a different
lie. What is refused outright is `inf` and `nan`, which used to be returned as
successful results.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from fractions import Fraction
from typing import Any

from arelis.tools.base import ToolResult

# Binary / unary ops only. No attribute access, no calls except safe math names.
_BINOPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: lambda a, b: _divide(a, b),
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
    "ln": math.log,
    "factorial": math.factorial,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "pi": math.pi,
    "e": math.e,
    "radians": math.radians,
    "degrees": math.degrees,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "hypot": math.hypot,
}


class CalculatorTool:
    name = "calculator"
    description = (
        "Evaluate a math expression exactly — decimals are exact, so money "
        "does not grow a floating-point tail. Use for arithmetic, percentages, "
        "units of count, and simple science functions (sqrt, sin, log, …). "
        "Understands '15% of 84', '30% off 59.99', '$4.50 + $2', '1,250 + 300'. "
        "Pass a plain expression like '2*(3+4)' or 'sqrt(2)*pi'. No import, no "
        "assignments. Unit conversion is the units tool, not this one. "
        "For a Python script (projectile motion, named variables) "
        "use the python tool. This is not a CAS — it cannot integrate or solve "
        "symbolically. Do not guess numeric answers when this tool can compute them."
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
            hint = _script_hint(expression)
            return ToolResult(ok=False, output=f"Could not evaluate: {exc}{hint}")
        shown, exact = present(value)
        note = f" (exactly {exact})" if exact else ""
        # Echo what was evaluated, not what was typed, when normalisation
        # changed it. "3 + 4 = = 7" reads like a bug; showing the rewrite also
        # lets the reader check that "30% off 59.99" was understood the way
        # they meant it.
        echo = normalize_expression(expression)
        if echo.strip() == expression.strip():
            echo = expression
        return ToolResult(
            ok=True,
            output=f"{echo} = {shown}{note}",
            data={"expression": expression, "value": shown},
        )


def present(value: Any) -> tuple[Any, str]:
    """Turn the internal number into what the model should read.

    Returns the value to show and, for a repeating fraction, the exact form
    alongside it. `1/3 = 0.3333333333333333 (exactly 1/3)` stops the model
    treating the decimal as the whole truth and rounding it into a wrong
    third place, which is the arithmetic mistake it makes most often.
    """
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return int(value), ""
        # A denominator made only of 2s and 5s terminates in base ten, so it
        # can be written out in full with nothing lost.
        residue = value.denominator
        for factor in (2, 5):
            while residue % factor == 0:
                residue //= factor
        if residue == 1:
            from decimal import Decimal

            exact = Decimal(value.numerator) / Decimal(value.denominator)
            return float(exact), ""
        return float(value), f"{value.numerator}/{value.denominator}"
    if isinstance(value, float) and value.is_integer():
        # Only where a float really is that integer. `hypot(1e308, 1e308)`
        # satisfies is_integer(), and int() on it spells out 309 digits —
        # every one after the seventeenth invented by the binary
        # representation. Printing them claims a precision the number does not
        # have, which is the same failure as returning nan with ok=True.
        if abs(value) < 2**53:
            return int(value), ""
        return value, ""
    return value, ""


_BANG_FACT = re.compile(r"(?<![\w.])(\d+)\s*!")


# The shapes people and models actually type. Each one used to come back as
# "invalid expression (invalid syntax)", which tells the model nothing it can
# act on, so it either retried the same call or answered from its own head.
_LEAD_WORDS = re.compile(r"(?i)^\s*(what\s+is|whats|what's|calculate|compute|eval)\b[:\s]*")
_TRAILING_EQ = re.compile(r"\s*=\s*\??\s*$")
_CURRENCY = re.compile(r"[$£€¥]")
_PERCENT_OFF = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*%\s*off\s+(\S+)")
_PERCENT_OF = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*%\s*of\s+")
_TIMES_X = re.compile(r"(?<=[\d)])\s*[xX]\s*(?=[\d(])")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")

# "5 miles in km" is a real question with a real tool behind it.
_UNIT_ASK = re.compile(
    r"(?i)\b\d+(?:\.\d+)?\s*[a-z°]+\s*(?:in|to|into|as)\s+[a-z°]",
)


def normalize_expression(text: str) -> str:
    """Rewrite the common surface forms into something ast can parse.

    None of this changes what the arithmetic means. `15% of 84` has exactly one
    reading, and refusing it bought nothing except a wasted round trip.
    """
    source = _LEAD_WORDS.sub("", text or "")
    source = _TRAILING_EQ.sub("", source)
    source = _CURRENCY.sub("", source)
    if "(" not in source:
        # Only outside a call. `max(1,250)` is two arguments and stripping the
        # comma there would silently change the answer, which is far worse than
        # failing to read a thousands separator.
        source = _THOUSANDS.sub("", source)
    source = _PERCENT_OFF.sub(r"(\2) * (1 - \1/100)", source)
    source = _PERCENT_OF.sub(r"(\1/100) * ", source)
    source = _TIMES_X.sub("*", source)
    # People write 17^2. Python wants **. This tool has no bitwise XOR.
    source = source.replace("^", "**")
    return _BANG_FACT.sub(r"factorial(\1)", source)


def evaluate_expression(expression: str) -> float | int:
    """Eval a whitelist AST. Raises ValueError on anything unsafe."""
    source = normalize_expression(expression)
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression ({exc.msg})") from exc
    value = _eval_node(tree.body)
    if isinstance(value, (int, Fraction)):
        # Exact arithmetic has no overflow, which is a new problem rather than
        # a solved one: `1e308 * 10` used to be `inf` and is now a genuinely
        # correct 309-digit integer. Correct, and useless — it is three hundred
        # tokens of prompt that no one can read. Bounded here rather than in
        # `present`, so the refusal says why instead of silently truncating.
        digits = len(str(abs(int(value)))) if _is_whole_number(value) else 0
        if digits > _MAX_DIGITS or _denominator(value) > 10**_MAX_DIGITS:
            raise ValueError(
                f"the exact result has about {max(digits, _MAX_DIGITS)} digits, "
                "which is too long to be a useful answer. Use the python tool "
                "if you need it, and do not round it from memory."
            )
    if isinstance(value, float) and not math.isfinite(value):
        # This used to be returned with ok=True. `2e400 - 2e400 = nan` is not a
        # computed answer, and handing it to a model that was called precisely
        # so it would not invent a number is the worst possible result.
        raise ValueError(
            "the result overflowed to "
            + ("infinity" if math.isinf(value) else "an undefined value")
            + " — the numbers are too large for exact arithmetic. "
            "Say the result is out of range; do not report a number."
        )
    return value


def _eval_node(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numbers are allowed")
        if isinstance(node.value, int):
            return node.value
        if not math.isfinite(node.value):
            # `1e400` parses to inf before a single operator has run. The same
            # "do not report a number" wording as the overflow check below, on
            # purpose: both end with the model holding no answer, and that is
            # exactly when it reaches for one of its own.
            raise ValueError(
                "that number is too large to represent. Say it is out of "
                "range; do not report a number."
            )
        # str() first, deliberately. Fraction(0.1) is the exact binary value,
        # 3602879701896397/36028797018963968, which is the problem rather than
        # the fix. Python's float repr round-trips to the shortest decimal that
        # reads back the same, so str() recovers the literal as written.
        return Fraction(str(node.value))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(float(left)) > 1e6 or abs(float(right)) > 1000:
                raise ValueError("exponent too large")
            return _power(left, right)
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
        if node.func.id == "factorial":
            # math.factorial refuses a Fraction even when it is a whole number.
            args = [int(a) if _is_whole(a) else a for a in args]
        return fn(*args)
    raise ValueError(f"unsupported syntax: {type(node).__name__}")


def _divide(left: Any, right: Any) -> Any:
    """`1/3` stays a third rather than becoming 0.3333333333333333.

    Integer literals are kept as `int` so that `factorial`, indices and the
    exponent rule keep working, which means plain `int / int` would fall
    through to Python's float division. Division is where precision is lost, so
    it is the one operator worth converting for.
    """
    if isinstance(left, (int, Fraction)) and isinstance(right, (int, Fraction)):
        if right == 0:
            raise ZeroDivisionError("division by zero")
        return Fraction(left) / Fraction(right)
    return operator.truediv(left, right)


# Generous — factorial(170) is 307 digits and is a real answer someone wants —
# but bounded, so an exact result cannot become a page of prompt.
_MAX_DIGITS = 500


def _is_whole(value: Any) -> bool:
    return isinstance(value, Fraction) and value.denominator == 1


def _is_whole_number(value: Any) -> bool:
    return isinstance(value, int) or _is_whole(value)


def _denominator(value: Any) -> int:
    return value.denominator if isinstance(value, Fraction) else 1


def _power(left: Any, right: Any) -> Any:
    """Keep an exact base exact when the exponent is a whole number.

    `Fraction ** Fraction` falls back to float even for `(1/2) ** 2`, so the
    integer case is pulled out by hand. It is the common one: `1.1 ** 2` is a
    compound-interest question, and `1.2100000000000002` is the wrong shape of
    answer for it.
    """
    if isinstance(left, Fraction) and _is_whole(right):
        return left ** int(right)
    if isinstance(left, Fraction) and isinstance(right, int):
        return left**right
    return operator.pow(left, right)


def _script_hint(expression: str) -> str:
    """Name the tool that can do it, rather than only refusing.

    The same move `analyze` makes for a PDF. A bare "invalid syntax" leaves the
    model with no next step but to answer from memory, which is the one
    outcome this tool exists to prevent.
    """
    if _UNIT_ASK.search(expression):
        return (
            " That is a unit conversion, not arithmetic. "
            "Call units(action=convert, expression=…) instead."
        )
    if re.search(r"(?i)\b(solve|integrate|derivative|differentiate|simplify)\b", expression):
        return " That is symbolic maths. Call cas with the matching action."
    if re.search(r"(?i)\bchoose\b|\bnCr\b|\bpermutations?\b", expression):
        return " For combinations write it out: factorial(n) / (factorial(k) * factorial(n-k))."
    # The script check comes before the '=' rule below, because an assignment
    # is the most common reason a script contains one and "call cas
    # action=solve" is useless advice for `v = 3; print(v*2)`.
    try:
        ast.parse(expression, mode="eval")
        return ""
    except SyntaxError:
        pass
    try:
        ast.parse(expression, mode="exec")
    except SyntaxError:
        pass
    else:
        return (
            " This looks like a Python script, not one expression. "
            "Call the python tool with that code."
        )
    if "=" in expression and not expression.rstrip().endswith("="):
        return (
            " There is an '=' in the middle. This tool evaluates one "
            "expression; it does not solve equations. Call cas action=solve."
        )
    return ""
