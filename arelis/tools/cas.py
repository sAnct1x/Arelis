"""Symbolic algebra — deterministic CAS so the model does not recite integrals.

SymPy's parse_expr uses eval. evaluate=False is not a sandbox. This tool
whitelists an AST first, then parses into a locked namespace with empty
builtins, then runs the named action under a timeout.
"""

from __future__ import annotations

import ast
import asyncio
import multiprocessing
import re
from typing import Any

from arelis.tools.base import ToolResult

_MAX_CHARS = 500
_TIMEOUT_S = 8.0
_ACTIONS = frozenset(
    {
        "integrate",
        "diff",
        "simplify",
        "solve",
        "dsolve",
        "limit",
        "series",
        "sum",
        "gradient",
        "directional",
        "factor",
        "expand",
    }
)
# Only these can pin a core for minutes. Solve/diff stay in-process.
_SPAWN_ACTIONS = frozenset({"integrate", "dsolve", "sum"})

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
        "e": sp.E,
        "I": sp.I,
        "oo": sp.oo,
        "inf": sp.oo,
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
        "factor": sp.factor,
        "expand": sp.expand,
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
        "simplify, solve, dsolve, limit, series, sum, gradient, directional, "
        "factor, expand. "
        "Pass a plain expression like 'x**2 * sin(x)' (use ** for powers). "
        "For solve, an equation is fine: '-4*x + 7 = 15'. "
        "gradient/directional take wrt='x,y,z', at='1,-1,2', dir='1,2,-2'. "
        "Result includes ascii, a unicode pretty form, and a latex: line — "
        "quote that latex inside $$ $$; do not rewrite it. "
        "This is the CAS — do not use calculator for integrals, derivatives, "
        "or symbolic algebra, and do not recite a closed form from memory. "
        "A timeout or an unevaluated Integral is not a proof none exists — "
        "do not invent a decimal or claim there is no closed form."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "integrate",
                    "diff",
                    "simplify",
                    "solve",
                    "dsolve",
                    "limit",
                    "series",
                    "sum",
                    "gradient",
                    "directional",
                    "factor",
                    "expand",
                ],
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
                "description": (
                    "Variable, or comma list for gradient/directional "
                    "(default x, or x,y,z)"
                ),
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
                    "Order: diff n=100 is the 100th derivative; "
                    "integrate n=2 is a double integral dx dx (max 4)"
                ),
            },
            "at": {
                "type": "string",
                "description": (
                    "Evaluate at this point (0, or 1,-1,2 for several vars)"
                ),
            },
            "dir": {
                "type": "string",
                "description": (
                    "Direction vector for directional, e.g. 1,2,-2. "
                    "Normalized automatically."
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
                    "Use integrate, diff, simplify, solve, dsolve, "
                    "limit, series, sum, gradient, directional, "
                    "factor, or expand."
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
        at = str(kwargs.get("at") or "").strip() or None
        n: int | None = None
        n_raw = kwargs.get("n")
        if n_raw is not None and str(n_raw).strip() != "":
            try:
                n = int(n_raw)
            except (TypeError, ValueError):
                return ToolResult(
                    ok=False,
                    output="n must be an integer.",
                    data={"fail_class": "fail:args", "action": action, "expr": expr},
                )
            if action == "diff" and not (1 <= n <= 200):
                return ToolResult(
                    ok=False,
                    output="n must be 1–200 for diff.",
                    data={"fail_class": "fail:args", "action": action, "expr": expr},
                )
            if action == "integrate" and not (1 <= n <= 4):
                return ToolResult(
                    ok=False,
                    output="n must be 1–4 for integrate.",
                    data={"fail_class": "fail:args", "action": action, "expr": expr},
                )
            if action == "series" and not (1 <= n <= 20):
                return ToolResult(
                    ok=False,
                    output="n must be 1–20 for series.",
                    data={"fail_class": "fail:args", "action": action, "expr": expr},
                )
        direction = str(kwargs.get("dir") or "").strip() or None
        try:
            result = await asyncio.to_thread(
                _run_timed,
                action,
                expr,
                wrt=wrt,
                symbol=symbol,
                lo=lo,
                hi=hi,
                n=n,
                at=at,
                direction=direction,
            )
        except TimeoutError:
            return ToolResult(
                ok=False,
                output=(
                    "The CAS did not finish. That is not a proof there is no "
                    "closed form. Do not invent a decimal or a formula."
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
                    "The CAS left this unevaluated. That is not a proof none "
                    "exists — I will not invent a closed form or a decimal."
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
    __slots__ = ("ascii", "latex", "text", "unevaluated")

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
    text = _as_ode_primes(text)
    return _as_equation_expr(text)


_ODE_PRIME3 = re.compile(r"\b([A-Za-z]\w*)'''")
_ODE_PRIME2 = re.compile(r"\b([A-Za-z]\w*)''")
_ODE_PRIME1 = re.compile(r"\b([A-Za-z]\w*)'(?![A-Za-z'])")


def _as_ode_primes(text: str) -> str:
    """y'' + y = 0 → Derivative(y(x), x, 2) + y(x) = 0 for dsolve."""
    if "'" not in text:
        return text
    names: set[str] = set()

    def _sub(pattern: re.Pattern[str], n: int, src: str) -> str:
        def repl(match: re.Match[str]) -> str:
            names.add(match.group(1))
            if n == 1:
                return f"Derivative({match.group(1)}(x), x)"
            return f"Derivative({match.group(1)}(x), x, {n})"

        return pattern.sub(repl, src)

    out = _sub(_ODE_PRIME3, 3, text)
    out = _sub(_ODE_PRIME2, 2, out)
    out = _sub(_ODE_PRIME1, 1, out)
    for name in names:
        out = re.sub(rf"\b{re.escape(name)}\b(?!\s*\()", f"{name}(x)", out)
    return out


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
    at: str | None = None,
    direction: str | None = None,
) -> _CasResult:
    """Run SymPy in a child we can kill.

    A thread timeout cannot stop integrate(). The old pool then waited
    for that thread on shutdown — glass froze, Stop did nothing, CPU
    stayed at one core until SymPy finished or the process was killed.
    Cheap solve/diff stay in this process so a quadratic is not a 2s spawn.
    Definite integrals try numeric+identify first — full integrate() often
    hunts the indefinite (dilogs) and never notices the bounds collapse.
    """
    if action == "integrate" and (lo is not None or hi is not None):
        hit = _identify_definite(expr, wrt=wrt, lo=lo, hi=hi)
        if hit is not None:
            return hit
    if action in _SPAWN_ACTIONS:
        return _run_in_process(
            _compute_to_queue,
            action,
            expr,
            wrt,
            symbol,
            lo,
            hi,
            n,
            timeout=_TIMEOUT_S,
        )
    return _compute(
        action,
        expr,
        wrt=wrt,
        symbol=symbol,
        lo=lo,
        hi=hi,
        n=n,
        at=at,
        direction=direction,
    )


def _run_in_process(target: Any, *args: Any, timeout: float = _TIMEOUT_S) -> _CasResult:
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue(maxsize=1)
    proc = ctx.Process(target=target, args=(queue, *args), daemon=True)
    try:
        proc.start()
        proc.join(timeout=max(0.1, float(timeout)))
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=1.0)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=0.5)
            raise TimeoutError("cas timeout")
        try:
            payload = queue.get(timeout=1.0)
        except Exception as exc:
            raise RuntimeError("CAS worker returned nothing") from exc
    finally:
        try:
            queue.close()
        except Exception:
            pass
        if proc.exitcode is not None:
            try:
                proc.close()
            except Exception:
                pass
    kind = payload[0]
    if kind == "err":
        _name, message = payload[1], payload[2]
        if _name == "ValueError":
            raise ValueError(message)
        raise RuntimeError(message)
    _ok, ascii_text, latex, text, unevaluated = payload
    return _CasResult(
        text, ascii=ascii_text, latex=latex, unevaluated=bool(unevaluated)
    )


def _compute_to_queue(
    queue: Any,
    action: str,
    expr: str,
    wrt: str | None,
    symbol: str | None,
    lo: str | None,
    hi: str | None,
    n: int | None,
) -> None:
    try:
        result = _compute(action, expr, wrt=wrt, symbol=symbol, lo=lo, hi=hi, n=n)
        queue.put(("ok", result.ascii, result.latex, result.text, result.unevaluated))
    except Exception as exc:
        queue.put(("err", type(exc).__name__, str(exc)))


def _identify_definite(
    expr: str,
    *,
    wrt: str | None,
    lo: str | None,
    hi: str | None,
) -> _CasResult | None:
    """High-precision quadrature + nsimplify. None if it does not lock."""
    try:
        parsed = parse_cas_expr(expr)
        var = parse_cas_expr(wrt or "x")
        lower = parse_cas_expr(lo or "0")
        upper = parse_cas_expr(hi or "1")
    except Exception:
        return None
    hit = _identify_parsed_definite(parsed, var, lower, upper)
    if hit is None:
        return None
    return _pack_result(hit)


def _n_definite(func: Any, var: Any, lower: Any, upper: Any) -> Any:
    """40-digit Integral; split 0→∞ when an endpoint blows up (ln x at 0)."""
    try:
        numeric = _collapse_erf(sp.N(sp.Integral(func, (var, lower, upper)), 40))
    except Exception:
        numeric = None
    if numeric is not None and getattr(numeric, "is_finite", False):
        return numeric
    try:
        if lower == 0 and upper == sp.oo:
            left = _collapse_erf(
                sp.N(sp.Integral(func, (var, sp.exp(-20), 1)), 40)
            )
            right = _collapse_erf(
                sp.N(sp.Integral(func, (var, 1, sp.exp(20))), 40)
            )
            if (
                left is not None
                and right is not None
                and getattr(left, "is_finite", False)
                and getattr(right, "is_finite", False)
            ):
                return left + right
    except Exception:
        return None
    return None


def _identify_parsed_definite(func: Any, var: Any, lower: Any, upper: Any) -> Any:
    """Return a closed form if a 40-digit numeric matches known constants."""
    _ensure_sympy()
    numeric = _n_definite(func, var, lower, upper)
    if numeric is None or not getattr(numeric, "is_finite", False):
        return None
    try:
        if abs(float(sp.N(sp.im(numeric)))) > 1e-18:
            return None
    except Exception:
        return None
    # Keep the 40-digit Float. complex() would drop to 53-bit and
    # nsimplify then invents a huge rational.
    target = sp.re(numeric) if numeric.is_real is False else numeric
    constants = [
        sp.pi,
        sp.E,
        sp.log(2),
        sp.log(3),
        sp.log(5),
        sp.Catalan,
        sp.sqrt(2),
        sp.sqrt(3),
        sp.GoldenRatio,
    ]
    try:
        guess = sp.nsimplify(target, constants=constants, tolerance=1e-28)
    except Exception:
        return None
    if guess is None or guess.has(sp.Float):
        return None
    if guess.is_rational:
        try:
            if abs(int(sp.numer(sp.together(guess)))) > 10**8:
                return None
        except Exception:
            return None
    try:
        err = abs(complex(sp.N(guess - target, 25)))
    except Exception:
        return None
    if err > 1e-25:
        return None
    return sp.simplify(guess)


def _as_factorial(expr: Any) -> Any | None:
    """-50! instead of a 65-digit blob (or that blob factored as odd*2^k)."""
    try:
        if not expr.is_number or not expr.is_integer:
            return None
        n = int(sp.Integer(expr))
        sign = -1 if n < 0 else 1
        absn = abs(n)
        fact = 1
        for k in range(1, 201):
            fact *= k
            if fact == absn:
                term = sp.factorial(k, evaluate=False)
                return term if sign > 0 else sp.Mul(-1, term, evaluate=False)
            if fact > absn:
                return None
    except Exception:
        return None
    return None


def _factor_pow2(expr: Any) -> Any:
    """9900*2**98 instead of a 34-digit blob."""
    try:
        if not expr.is_number or not expr.is_integer:
            return expr
        n = sp.Integer(expr)
        exp = 0
        while n.is_even:
            n = n // 2
            exp += 1
        if exp < 8:
            return expr
        return sp.Mul(n, sp.Pow(2, exp, evaluate=False), evaluate=False)
    except Exception:
        return expr


def _as_exp(expr: Any) -> Any:
    """E**u → exp(u) so diff does not emit log(E)."""
    return expr.replace(
        lambda e: bool(getattr(e, "is_Pow", False) and e.base == sp.E),
        lambda e: sp.exp(e.exp),
    )


def _collapse_erf(expr: Any) -> Any:
    """erf(∞)=1 so ∫ e^{-x²} dx over the line is √π, not √π·erf(∞)."""
    try:
        return expr.subs({sp.erf(sp.oo): 1, sp.erf(-sp.oo): -1})
    except Exception:
        return expr


def _csv_exprs(raw: str) -> list[Any]:
    parts = [p.strip() for p in (raw or "").split(",") if p.strip()]
    if not parts:
        raise ValueError("expected a comma-separated list")
    return [parse_cas_expr(p) for p in parts]


def _wrt_symbols(wrt: str | None, expr: Any) -> list[Any]:
    if wrt and wrt.strip():
        return _csv_exprs(wrt)
    free = sorted(expr.free_symbols, key=str)
    if not free:
        raise ValueError("no symbols to differentiate")
    return free


def _compute(
    action: str,
    expr: str,
    *,
    wrt: str | None,
    symbol: str | None,
    lo: str | None,
    hi: str | None,
    n: int | None = None,
    at: str | None = None,
    direction: str | None = None,
) -> _CasResult:
    parsed = _as_exp(parse_cas_expr(expr))
    if action == "simplify":
        # The 9B writes factor(...) inside simplify. simplify() would
        # expand that product back to the polynomial.
        if expr.strip().lower().startswith("factor("):
            return _pack_result(parsed)
        return _pack_result(sp.simplify(parsed))
    if action == "factor":
        return _pack_result(sp.factor(parsed))
    if action == "expand":
        return _pack_result(sp.expand(parsed))
    if action == "diff":
        var = parse_cas_expr(wrt or "x")
        times = 1 if n is None else int(n)
        if times < 1 or times > 200:
            raise ValueError("n must be 1–200")
        out = sp.simplify(sp.diff(parsed, var, times))
        if at is not None:
            out = sp.simplify(out.subs(var, parse_cas_expr(at)))
            fact = _as_factorial(out)
            out = fact if fact is not None else _factor_pow2(out)
        return _pack_result(out)
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
    if action == "limit":
        var = parse_cas_expr(wrt or "x")
        point = parse_cas_expr(at if at is not None else (hi or lo or "0"))
        return _pack_result(sp.limit(parsed, var, point))
    if action == "series":
        var = parse_cas_expr(wrt or "x")
        point = parse_cas_expr(at or "0")
        times = 6 if n is None else int(n)
        if times < 1 or times > 20:
            raise ValueError("n must be 1–20")
        out = parsed.series(var, point, times)
        try:
            out = out.removeO()
        except Exception:
            pass
        return _pack_result(sp.simplify(out))
    if action == "sum":
        var = parse_cas_expr(wrt or symbol or "n")
        lower = parse_cas_expr(lo or "1")
        upper = parse_cas_expr(hi or "oo")
        out = sp.summation(parsed, (var, lower, upper))
        if out.has(sp.Sum):
            return _pack_result(out, unevaluated=True)
        return _pack_result(sp.simplify(out))
    if action in {"gradient", "directional"}:
        vars_ = _wrt_symbols(wrt, parsed)
        grad = [sp.simplify(sp.diff(parsed, v)) for v in vars_]
        if at is not None:
            pts = _csv_exprs(at)
            if len(pts) != len(vars_):
                raise ValueError("at= needs one value per variable")
            subs = dict(zip(vars_, pts, strict=True))
            grad = [sp.simplify(g.subs(subs)) for g in grad]
        if action == "gradient":
            return _pack_result(sp.Matrix(grad))
        vec = _csv_exprs(direction or "")
        if len(vec) != len(vars_):
            raise ValueError("dir= needs one component per variable")
        mat = sp.Matrix(vec)
        norm = sp.sqrt(sum(c**2 for c in mat))
        if norm == 0:
            raise ValueError("direction vector is zero")
        unit = mat / norm
        out = sp.simplify(sp.Matrix(grad).dot(unit))
        return _pack_result(out)
    var = parse_cas_expr(wrt or "x")
    times = 1 if n is None else int(n)
    if times < 1 or times > 4:
        raise ValueError("n must be 1–4")
    if lo is not None or hi is not None:
        if times != 1:
            raise ValueError("definite integrals do not take n>1")
        lower = parse_cas_expr(lo or "0")
        upper = parse_cas_expr(hi or "1")
        identified = _identify_parsed_definite(parsed, var, lower, upper)
        if identified is not None:
            return _pack_result(identified)
        out = _collapse_erf(sp.integrate(parsed, (var, lower, upper)))
        out = sp.simplify(out)
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
