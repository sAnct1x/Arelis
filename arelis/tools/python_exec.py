"""Short scientific Python — kinematics, scripts, sympy, not a shell.

The pocket calculator is one expression. Physics is a few lines with names.
This tool runs that cell: assignments, prints, math, sympy, numpy. It is not
a general interpreter. os, subprocess, sockets, and files stay out.
"""

from __future__ import annotations

import ast
import concurrent.futures
import io
from typing import Any

from arelis.tools.base import ToolResult

_MAX_CHARS = 8_000
_MAX_OUTPUT = 8_000
_TIMEOUT_S = 10.0

_ALLOWED_IMPORTS = frozenset(
    {
        "math",
        "cmath",
        "statistics",
        "fractions",
        "decimal",
        "itertools",
        "functools",
        "collections",
        "operator",
        "copy",
        "json",
        "re",
        "datetime",
        "sympy",
        "numpy",
        "scipy",
        "mpmath",
    }
)

_CHART_IMPORTS = frozenset(
    {"matplotlib", "pyplot", "pylab", "seaborn", "plotly"}
)


def _import_refusal(name: str) -> str:
    if name in _CHART_IMPORTS:
        return (
            f"import {name!r} is not allowed in this cell. "
            "Compute xs and ys here (print comma-separated numbers), "
            "then call plot with those series and out='name.png'. "
            "path= is a CSV table, not the PNG."
        )
    return (
        f"import {name!r} is not allowed. "
        "math/sympy/numpy are preloaded; os/subprocess are not."
    )

_FORBIDDEN_CALLS = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "input",
        "breakpoint",
        "help",
        "exit",
        "quit",
        "memoryview",
        "classmethod",
        "staticmethod",
        "type",
        "super",
    }
)

_MATH_TOP = (
    "sin",
    "cos",
    "tan",
    "asin",
    "acos",
    "atan",
    "atan2",
    "sqrt",
    "log",
    "log10",
    "exp",
    "radians",
    "degrees",
    "hypot",
    "floor",
    "ceil",
    "pi",
    "e",
)


class PythonTool:
    name = "python"
    description = (
        "Run a short Python cell for numerics, kinematics, linear algebra, or "
        "a multi-step derivation. math is preloaded (sin, cos, radians, sqrt, "
        "pi). sympy is `sp`, numpy is `np` when installed. Assignments and "
        "print() work; the last expression is shown. Do not import os, "
        "subprocess, or open files. Timeout 10s. Use calculator for a single "
        "arithmetic expression; use cas for one symbolic integrate/diff/solve; "
        "use this when you need a script (projectile range, quadratic time of "
        "flight, systems of equations). matplotlib is not allowed — print "
        "comma-separated xs and ys, then call plot with those numbers and "
        "out='name.png' (path= is a CSV, not the picture)."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Python source. Example: g=9.81; v=5; th=radians(45); "
                    "then print the range."
                ),
            },
            "source": {
                "type": "string",
                "description": "Alias for code.",
            },
            "script": {
                "type": "string",
                "description": "Alias for code.",
            },
        },
        "required": ["code"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        code = str(
            kwargs.get("code") or kwargs.get("source") or kwargs.get("script") or ""
        ).strip()
        if not code:
            return ToolResult(
                ok=False,
                output="Missing code. Pass a Python snippet in `code`.",
            )
        if len(code) > _MAX_CHARS:
            return ToolResult(
                ok=False,
                output=f"Code is longer than {_MAX_CHARS} characters.",
            )
        try:
            text = _run_timed(code)
        except TimeoutError:
            return ToolResult(
                ok=False,
                output="The Python cell timed out (10s). I will not guess the result.",
            )
        except ValueError as exc:
            return ToolResult(ok=False, output=f"Python refused: {exc}")
        except SyntaxError as exc:
            return ToolResult(
                ok=False,
                output=f"Python syntax error: {exc.msg}",
            )
        except Exception as exc:
            return ToolResult(ok=False, output=f"Python failed: {exc}")
        return ToolResult(
            ok=True,
            output=text,
            data={"code": code, "result": text},
        )


def _run_timed(code: str) -> str:
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_cell, code)
        try:
            return future.result(timeout=_TIMEOUT_S)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError("python timeout") from exc


def _run_cell(code: str) -> str:
    tree = ast.parse(code, mode="exec")
    _assert_safe(tree)
    namespace = _namespace()
    buf = io.StringIO()

    def _print(*args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("file", buf)
        print(*args, **kwargs)

    namespace["print"] = _print
    builtins = namespace["__builtins__"]
    if isinstance(builtins, dict):
        builtins["print"] = _print

    body = list(tree.body)
    last_value: Any = None
    if body and isinstance(body[-1], ast.Expr):
        last = body.pop()
        if body:
            exec(
                compile(
                    ast.Module(body=body, type_ignores=[]),
                    "<python>",
                    "exec",
                ),
                namespace,
                namespace,
            )
        last_value = eval(
            compile(ast.Expression(last.value), "<python>", "eval"),
            namespace,
            namespace,
        )
    else:
        exec(compile(tree, "<python>", "exec"), namespace, namespace)

    out = buf.getvalue()
    if last_value is not None:
        shown = str(last_value)
        if out and not out.endswith("\n"):
            out += "\n"
        out += shown
    text = (out or "").strip() or (
        "(no output — print the result, or leave a final expression)"
    )
    if len(text) > _MAX_OUTPUT:
        text = text[:_MAX_OUTPUT] + "\n…(truncated)"
    return text


def _assert_safe(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".", 1)[0] for alias in node.names]
            else:
                root = (node.module or "").split(".", 1)[0]
                if root:
                    names = [root]
            for name in names:
                if name not in _ALLOWED_IMPORTS:
                    raise ValueError(_import_refusal(name))
        if isinstance(node, ast.Attribute) and str(node.attr).startswith("_"):
            raise ValueError("private attributes are not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError(f"name {node.id!r} is not allowed")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_CALLS:
                raise ValueError(f"call {node.func.id!r} is not allowed")
        if isinstance(
            node,
            (
                ast.AsyncFunctionDef,
                ast.AsyncFor,
                ast.AsyncWith,
                ast.Await,
                ast.Yield,
                ast.YieldFrom,
            ),
        ):
            raise ValueError("async/yield is not allowed")


def _safe_import(
    name: str,
    globals: Any = None,
    locals: Any = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    if level:
        raise ValueError("relative imports are not allowed")
    root = str(name or "").split(".", 1)[0]
    if root not in _ALLOWED_IMPORTS:
        raise ValueError(_import_refusal(root))
    return __import__(name, globals, locals, fromlist, 0)


def _namespace() -> dict[str, Any]:
    import cmath
    import collections
    import copy
    import datetime
    import decimal
    import fractions
    import functools
    import itertools
    import json
    import math
    import operator
    import re
    import statistics

    safe_builtins: dict[str, Any] = {
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "complex": complex,
        "dict": dict,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "format": format,
        "frozenset": frozenset,
        "int": int,
        "isinstance": isinstance,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "pow": pow,
        "print": print,
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "zip": zip,
        "True": True,
        "False": False,
        "None": None,
        "Exception": Exception,
        "ValueError": ValueError,
        "TypeError": TypeError,
        "ZeroDivisionError": ZeroDivisionError,
        "ArithmeticError": ArithmeticError,
        "__import__": _safe_import,
    }
    ns: dict[str, Any] = {
        "__builtins__": safe_builtins,
        "math": math,
        "cmath": cmath,
        "statistics": statistics,
        "fractions": fractions,
        "decimal": decimal,
        "itertools": itertools,
        "functools": functools,
        "collections": collections,
        "operator": operator,
        "copy": copy,
        "json": json,
        "re": re,
        "datetime": datetime,
    }
    for name in _MATH_TOP:
        ns[name] = getattr(math, name)
    try:
        import sympy as sympy_mod

        ns["sympy"] = sympy_mod
        ns["sp"] = sympy_mod
    except ImportError:
        pass
    try:
        import numpy as np

        ns["numpy"] = np
        ns["np"] = np
    except ImportError:
        pass
    try:
        import scipy

        ns["scipy"] = scipy
    except ImportError:
        pass
    try:
        import mpmath

        ns["mpmath"] = mpmath
    except ImportError:
        pass
    return ns
