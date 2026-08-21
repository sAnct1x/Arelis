"""Symbolic algebra — deterministic CAS so the model does not recite integrals.

SymPy's parse_expr uses eval. evaluate=False is not a sandbox. This tool
whitelists an AST first, then parses into a locked namespace with empty
builtins, then runs the named action under a timeout.
"""

from __future__ import annotations

import ast
import concurrent.futures
from typing import Any

from arelis.tools.base import ToolResult

_MAX_CHARS = 500
_TIMEOUT_S = 8.0
_ACTIONS = frozenset({"integrate", "diff", "simplify", "solve", "dsolve"})

_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
_UNARYOPS = (ast.UAdd, ast.USub)

# Loaded on first parse. Importing this module must not pull SymPy into a
# cold glass launch — build_tool_registry imports CasTool at startup.
sp: Any = None
parse_expr: Any = None
standard_transformations: Any = None
convert_xor: Any = None
_SAFE_SYMPY: dict[str, Any] | None = None


def _ensure_sympy() -> None:
    """Import SymPy and fill the locked parse namespace. Idempotent."""
    global sp, parse_expr, standard_transformations, convert_xor, _SAFE_SYMPY
    if _SAFE_SYMPY is not None:
        return
    import sympy as sympy_mod
    from sympy.parsing.sympy_parser import (
        convert_xor as _convert_xor,
    )
    from sympy.parsing.sympy_parser import (
        parse_expr as _parse_expr,
    )
    from sympy.parsing.sympy_parser import (
        standard_transformations as _standard_transformations,
    )

    sp = sympy_mod
    parse_expr = _parse_expr
    standard_transformations = _standard_transformations
    convert_xor = _convert_xor
    # Constructors parse_expr emits after transformations (Symbol('x'), …).
    # Users cannot pass string arguments: the AST gate rejects string constants.
    _SAFE_SYMPY = {
        "Symbol": sp.Symbol,
        "Integer": sp.Integer,
        "Float": sp.Float,
        "Rational": sp.Rational,
        "Pow": sp.Pow,
        "Mul": sp.Mul,
        "Add": sp.Add,
        "Mod": sp.Mod,
        "Tuple": sp.Tuple,
        "sin": sp.sin,
        "cos": sp.cos,
        "tan": sp.tan,
        "asin": sp.asin,
        "acos": sp.acos,
        "atan": sp.atan,
        "sinh": sp.sinh,
        "cosh": sp.cosh,
        "tanh": sp.tanh,
        "exp": sp.exp,
        "log": sp.log,
        "ln": sp.log,
        "sqrt": sp.sqrt,
        "Abs": sp.Abs,
        "abs": sp.Abs,
        "pi": sp.pi,
        "E": sp.E,
        "I": sp.I,
        "oo": sp.oo,
        "Eq": sp.Eq,
        "diff": sp.diff,
        "Derivative": sp.Derivative,
        "Function": sp.Function,
        "exp_polar": sp.exp,
        "factorial": sp.factorial,
        "gamma": sp.gamma,
        "erf": sp.erf,
        "Heaviside": sp.Heaviside,
        "Min": sp.Min,
        "Max": sp.Max,
        "floor": sp.floor,
        "ceiling": sp.ceiling,
    }


_ALLOWED_NODES = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.UAdd,
    ast.USub,
)


class CasTool:
    name = "cas"
    description = (
        "Deterministic computer algebra (SymPy). Actions: integrate, diff, "
        "simplify, solve, dsolve. Pass a plain expression like 'x**2 * sin(x)' "
        "(use ** for powers). This is the CAS — do not use calculator for "
        "integrals, derivatives, or symbolic algebra, and do not recite a "
        "closed form from memory. If there is no closed form, say so."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["integrate", "diff", "simplify", "solve", "dsolve"],
                "description": "Algebra action (default integrate)",
            },
            "expr": {
                "type": "string",
                "description": "Expression, e.g. x**2 * sin(x)",
            },
            "wrt": {
                "type": "string",
                "description": "Variable to integrate or differentiate (default x)",
            },
            "symbol": {
                "type": "string",
                "description": "Unknown to solve for (default x), or y for dsolve",
            },
            "lo": {
                "type": "string",
                "description": "Definite-integral lower limit",
            },
            "hi": {
                "type": "string",
                "description": "Definite-integral upper limit",
            },
        },
        "required": ["expr"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "integrate").strip().lower()
        if action not in _ACTIONS:
            return ToolResult(
                ok=False,
                output=(
                    f"Unknown action {action!r}. "
                    "Use integrate, diff, simplify, solve, or dsolve."
                ),
                data={"fail_class": "fail:action"},
            )
        expr = str(kwargs.get("expr") or "").strip()
        if not expr:
            return ToolResult(
                ok=False,
                output="Missing expr.",
                data={"fail_class": "fail:args"},
            )
        wrt = str(kwargs.get("wrt") or "").strip() or None
        symbol = str(kwargs.get("symbol") or "").strip() or None
        lo = str(kwargs.get("lo") or "").strip() or None
        hi = str(kwargs.get("hi") or "").strip() or None
        try:
            result = _run_timed(action, expr, wrt=wrt, symbol=symbol, lo=lo, hi=hi)
        except TimeoutError:
            return ToolResult(
                ok=False,
                output=(
                    "The CAS timed out. That usually means there is no cheap "
                    "closed form — I will not guess one."
                ),
                data={"fail_class": "fail:timeout", "action": action, "expr": expr},
            )
        except ValueError as exc:
            return ToolResult(
                ok=False,
                output=f"Could not parse that expression: {exc}",
                data={"fail_class": "fail:parse", "action": action, "expr": expr},
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                output=f"CAS failed: {exc}",
                data={"fail_class": "fail:other", "action": action, "expr": expr},
            )
        if result.unevaluated:
            return ToolResult(
                ok=False,
                output=(
                    "No closed form found. The CAS could not integrate or solve "
                    "that symbolically — I will not invent one."
                ),
                data={
                    "fail_class": "fail:no_closed_form",
                    "action": action,
                    "expr": expr,
                    "result": result.text,
                },
            )
        shown = f"{action}({expr}) = {result.text}"
        return ToolResult(
            ok=True,
            output=shown,
            data={
                "action": action,
                "expr": expr,
                "result": result.text,
            },
        )


class _CasResult:
    __slots__ = ("text", "unevaluated")

    def __init__(self, text: str, *, unevaluated: bool = False) -> None:
        self.text = text
        self.unevaluated = unevaluated


def parse_cas_expr(expression: str) -> Any:
    """Parse a CAS expression after an AST whitelist. Raises ValueError."""
    _ensure_sympy()
    raw = _preprocess(expression)
    try:
        tree = ast.parse(raw, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression ({exc.msg})") from exc
    _assert_safe_ast(raw)
    local_dict = dict(_SAFE_SYMPY or {})
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id not in local_dict and not node.func.id.startswith("_"):
                local_dict[node.func.id] = sp.Function(node.func.id)
    return parse_expr(
        raw,
        local_dict=local_dict,
        global_dict={"__builtins__": {}},
        transformations=(*standard_transformations, convert_xor),
        evaluate=True,
    )


def _preprocess(expression: str) -> str:
    text = (expression or "").strip()
    if not text:
        raise ValueError("empty expression")
    if len(text) > _MAX_CHARS:
        raise ValueError("expression too long")
    if any(ord(ch) < 32 and ch not in "\t" for ch in text):
        raise ValueError("control characters are not allowed")
    return text.replace("^", "**").replace("·", "*")


def _assert_safe_ast(expression: str) -> None:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"invalid expression ({exc.msg})") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, complex)) and not isinstance(
                node.value, bool
            ):
                continue
            raise ValueError("only numbers and names are allowed")
        if isinstance(node, ast.Name):
            if node.id.startswith("_") or node.id in {
                "open",
                "eval",
                "exec",
                "compile",
                "getattr",
                "globals",
                "locals",
                "vars",
                "input",
                "help",
                "breakpoint",
                "memoryview",
                "classmethod",
                "staticmethod",
                "property",
                "super",
                "type",
                "object",
                "print",
            }:
                raise ValueError(f"name {node.id!r} is not allowed")
            continue
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("only simple function calls are allowed")
            if node.keywords:
                raise ValueError("keyword arguments are not allowed")
            continue
        if isinstance(node, ast.BinOp) and isinstance(node.op, _BINOPS):
            continue
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, _UNARYOPS):
            continue
        if type(node) in _ALLOWED_NODES:
            continue
        raise ValueError(f"unsupported syntax: {type(node).__name__}")


def _run_timed(
    action: str,
    expr: str,
    *,
    wrt: str | None,
    symbol: str | None,
    lo: str | None,
    hi: str | None,
) -> _CasResult:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            _compute, action, expr, wrt=wrt, symbol=symbol, lo=lo, hi=hi
        )
        try:
            return future.result(timeout=_TIMEOUT_S)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError("cas timeout") from exc


def _compute(
    action: str,
    expr: str,
    *,
    wrt: str | None,
    symbol: str | None,
    lo: str | None,
    hi: str | None,
) -> _CasResult:
    parsed = parse_cas_expr(expr)
    if action == "simplify":
        return _CasResult(str(sp.simplify(parsed)))
    if action == "diff":
        var = parse_cas_expr(wrt or "x")
        return _CasResult(str(sp.diff(parsed, var)))
    if action == "solve":
        unknown = parse_cas_expr(symbol or "x")
        solutions = sp.solve(parsed, unknown)
        return _CasResult(str(solutions))
    if action == "dsolve":
        func = _ode_function(symbol)
        solved = sp.dsolve(parsed, func)
        text = str(solved)
        if "dsolve" in text.lower() and "Eq" not in text:
            return _CasResult(text, unevaluated=True)
        return _CasResult(text)
    var = parse_cas_expr(wrt or "x")
    if lo is not None or hi is not None:
        lower = parse_cas_expr(lo or "0")
        upper = parse_cas_expr(hi or "1")
        out = sp.integrate(parsed, (var, lower, upper))
    else:
        out = sp.integrate(parsed, var)
    if isinstance(out, sp.Integral) or out.has(sp.Integral):
        return _CasResult(str(out), unevaluated=True)
    return _CasResult(str(out))


def _ode_function(symbol: str | None) -> Any:
    _ensure_sympy()
    name = (symbol or "y").strip() or "y"
    if not name.isidentifier() or name.startswith("_"):
        raise ValueError("dsolve symbol must be a plain name like y")
    return sp.Function(name)(sp.Symbol("x"))
