"""Symbolic algebra — deterministic CAS so the model does not recite integrals.

SymPy's parse_expr uses eval. evaluate=False is not a sandbox. This tool
whitelists an AST first, then parses into a locked namespace with empty
builtins, then runs the named action under a timeout.
"""

from __future__ import annotations

import ast
import concurrent.futures
import re
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
        "(use ** for powers). For solve, an equation is fine: "
        "'-4*x + 7 = 15'. Result includes ascii, a unicode pretty form, and "
        "a latex: line — quote that latex inside $$ $$; do not rewrite it. "
        "This is the CAS — do not use calculator for integrals, derivatives, "
        "or symbolic algebra, and do not recite a closed form from memory. "
        "If there is no closed form, say so."
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
                "description": (
                    "Expression, e.g. x**2 * sin(x). For solve, "
                    "'-4*x + 7 = 15' or Eq(-4*x + 7, 15) is fine."
                ),
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
            "n": {
                "type": "integer",
                "description": (
                    "How many times to integrate the same variable "
                    "(default 1; use 2 for a double integral dx dx)"
                ),
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
        n: int | None = None
        n_raw = kwargs.get("n")
        if n_raw is not None and str(n_raw).strip() != "":
            try:
                n = int(n_raw)
            except (TypeError, ValueError):
                return ToolResult(
                    ok=False,
                    output="n must be an integer 1–4.",
                    data={"fail_class": "fail:args", "action": action, "expr": expr},
                )
        try:
            result = _run_timed(
                action, expr, wrt=wrt, symbol=symbol, lo=lo, hi=hi, n=n
            )
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
        shown = f"{action}({expr}) =\n{result.text}"
        return ToolResult(
            ok=True,
            output=shown,
            data={
                "action": action,
                "expr": expr,
                "result": result.ascii,
                "latex": result.latex,
            },
        )


class _CasResult:
    __slots__ = ("text", "ascii", "latex", "unevaluated")

    def __init__(
        self,
        text: str,
        *,
        ascii: str = "",
        latex: str = "",
        unevaluated: bool = False,
    ) -> None:
        self.text = text
        self.ascii = ascii or text
        self.latex = latex
        self.unevaluated = unevaluated


def _pack_result(obj: Any, *, unevaluated: bool = False) -> _CasResult:
    """Ascii + unicode pretty + latex so the chat bubble is not a rewrite."""
    ascii_text = str(obj)
    pretty = ascii_text
    latex = ascii_text
    try:
        pretty = str(sp.pretty(obj, use_unicode=True))
    except Exception:
        pass
    try:
        latex = str(sp.latex(obj))
    except Exception:
        pass
    lines = [ascii_text]
    if pretty.strip() and pretty.strip() != ascii_text.strip():
        lines.extend(["", "pretty:", pretty])
    if latex.strip() and latex.strip() != ascii_text.strip():
        lines.extend(["", f"latex: {latex}"])
    return _CasResult(
        "\n".join(lines),
        ascii=ascii_text,
        latex=latex,
        unevaluated=unevaluated,
    )


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


_SUPER_POWER = {
    "⁰": "**0",
    "¹": "**1",
    "²": "**2",
    "³": "**3",
    "⁴": "**4",
    "⁵": "**5",
    "⁶": "**6",
    "⁷": "**7",
    "⁸": "**8",
    "⁹": "**9",
}
# OCR often drops the superscript: (a-b)2 from (a-b)².
_PAREN_DIGIT_POWER = re.compile(r"\)([2-9])(?!\d)")


def _preprocess(expression: str) -> str:
    text = (expression or "").strip()
    if not text:
        raise ValueError("empty expression")
    if len(text) > _MAX_CHARS:
        raise ValueError("expression too long")
    if any(ord(ch) < 32 and ch not in "\t" for ch in text):
        raise ValueError("control characters are not allowed")
    for glyph, power in _SUPER_POWER.items():
        text = text.replace(glyph, power)
    text = text.replace("^", "**").replace("·", "*")
    text = _PAREN_DIGIT_POWER.sub(r")**\1", text)
    return _as_equation_expr(text)


def _as_equation_expr(text: str) -> str:
    """Turn 'lhs = rhs' into Eq((lhs), (rhs)). AST eval cannot parse '='."""
    raw = text.strip()
    if "<=" in raw or ">=" in raw or "!=" in raw:
        return raw
    if "==" in raw:
        if raw.count("==") != 1:
            return raw
        left, right = raw.split("==", 1)
    elif raw.count("=") == 1:
        left, right = raw.split("=", 1)
    else:
        return raw
    left, right = left.strip(), right.strip()
    if not left or not right:
        return raw
    return f"Eq(({left}), ({right}))"


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
    n: int | None,
) -> _CasResult:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            _compute, action, expr, wrt=wrt, symbol=symbol, lo=lo, hi=hi, n=n
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
    n: int | None = None,
) -> _CasResult:
    parsed = parse_cas_expr(expr)
    if action == "simplify":
        return _pack_result(sp.simplify(parsed))
    if action == "diff":
        var = parse_cas_expr(wrt or "x")
        return _pack_result(sp.diff(parsed, var))
    if action == "solve":
        unknown = parse_cas_expr(symbol or "x")
        solutions = sp.solve(parsed, unknown)
        return _pack_result(solutions)
    if action == "dsolve":
        func = _ode_function(symbol)
        solved = sp.dsolve(parsed, func)
        text = str(solved)
        if "dsolve" in text.lower() and "Eq" not in text:
            return _pack_result(solved, unevaluated=True)
        return _pack_result(solved)
    var = parse_cas_expr(wrt or "x")
    times = 1 if n is None else int(n)
    if times < 1 or times > 4:
        raise ValueError("n must be 1–4")
    if lo is not None or hi is not None:
        if times != 1:
            raise ValueError("definite integrals do not take n>1")
        lower = parse_cas_expr(lo or "0")
        upper = parse_cas_expr(hi or "1")
        out = sp.integrate(parsed, (var, lower, upper))
    else:
        out = parsed
        for _ in range(times):
            out = sp.integrate(out, var)
        out = sp.simplify(out)
    if isinstance(out, sp.Integral) or out.has(sp.Integral):
        return _pack_result(out, unevaluated=True)
    return _pack_result(out)


def _ode_function(symbol: str | None) -> Any:
    _ensure_sympy()
    name = (symbol or "y").strip() or "y"
    if not name.isidentifier() or name.startswith("_"):
        raise ValueError("dsolve symbol must be a plain name like y")
    return sp.Function(name)(sp.Symbol("x"))
