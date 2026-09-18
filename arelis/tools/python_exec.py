"""Short scientific Python — kinematics, scripts, sympy, not a shell.

The pocket calculator is one expression. Physics is a few lines with names.
This tool runs that cell: assignments, prints, math, sympy, numpy. It is not
a general interpreter. os, subprocess, sockets, and files stay out.

Two layers do that work, and it is worth knowing which one to trust.

The AST rules came first: an import allowlist, no leading underscores, a list
of forbidden calls, and a list of attribute names that mean "evaluate this
text" or "touch the disk". They are useful and they are *not* sufficient,
which is not a guess — it is the history of this file. The list shipped with
`savetxt` and `save` on it, and `scipy.io.savemat`, `scipy.io.wavfile.write`
and `from scipy.io import savemat` all wrote real files to the repo root. Fix
those three names and the next library arrives with three more. A denylist of
names is always one import behind.

So the promise above is kept by an audit hook instead. `sys.addaudithook`
fires on the *operation* — the `open`, the `Popen`, the `connect` — no matter
which function was spelled to reach it, and the hook refuses any of them on a
thread that is running a cell. There is only one `open`. The AST rules stay as
defence in depth and as better error messages, but the hook is the boundary.

One honest asymmetry: writes are structural, reads are not. Blocking read-mode
`open` would stop the import machinery, and a cell that cannot `import sympy`
is not a tool, so reads rest on the name denylist alone. See
`test_reading_a_file_is_refused_too`.

The string rule is worth its own line, because it is what the AST rules kept
missing: they inspect `Import`, `Attribute` and `Name` nodes, so a dunder or a
payload spelled inside a *string constant* was invisible to all of them.
`sympy.sympify` is `eval` with a friendlier name and is preloaded here,
because symbolic maths is the point of the tool, and it read those strings
quite happily. A string literal may therefore not contain `__`.

The 10s limit is two layers, because a Python thread cannot be killed from
outside. A line tracer raises inside the cell, which stops any loop written in
Python; a `while True: pass` used to hang the assistant outright, forever, with
the tool description still advertising a timeout. If the cell is wedged inside
one long C call instead, no line event fires, so the future gives up two
seconds later and abandons the thread rather than joining it.
"""

from __future__ import annotations

import ast
import concurrent.futures
import io
import sys
import threading
import time
from typing import Any

from arelis.tools.base import ToolResult

_MAX_CHARS = 8_000
_MAX_OUTPUT = 8_000
_TIMEOUT_S = 10.0
# How long past the tracer's own deadline the future waits before giving up on
# the thread entirely. Only reached when the cell is stuck inside a single C
# call, where no line event ever fires for the tracer to act on.
_TIMEOUT_GRACE_S = 2.0

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

# Attribute names that mean "evaluate this text" or "touch the disk", reachable
# on modules the allowlist deliberately permits. The import allowlist cannot
# help here: `sympy` is the whole point of the tool, and `sympy.sympify` is
# `eval` with a friendly name — `sp.sympify("__import__('os').name")` returned
# the platform string before this list existed.
#
# `compile` is absent on purpose: the bare builtin is already blocked as a Name,
# and `re.compile` is an ordinary thing to write.
_FORBIDDEN_ATTR_CALLS = frozenset(
    {
        # Text in, code out.
        "sympify",
        "parse_expr",
        "parse_latex",
        "lambdify",
        "S",
        "eval",
        "exec",
        "evalf_",
        "preview",  # sympy: shells out to LaTeX and writes an image
        "run",
        "system",
        "popen",
        "spawn",
        "check_output",
        "check_call",
        # An attribute named by a string sidesteps the dunder rule below even
        # with it in place, because the name need not be a dunder to be useful.
        "attrgetter",
        "methodcaller",
        # The disk. The module docstring promises files stay out; numpy and
        # friends did not know that.
        "save",
        "savetxt",
        "savez",
        "savez_compressed",
        "load",
        "loadtxt",
        "genfromtxt",
        "fromfile",
        "tofile",
        "memmap",
        "savemat",
        "mmwrite",
        "write",
        "writeto",
        "imsave",
        "imwrite",
        "savefig",
        "to_csv",
        "to_excel",
        "to_pickle",
        "dump",
        "open",
        "mkdir",
        "makedirs",
        "remove",
        "unlink",
        "rename",
        "rmtree",
    }
)

# Checking only the call form leaves two ways round it: `from sympy import
# sympify` makes it a bare Name, and `f = s.sympify` makes the call site a name
# the checker has never heard of. So the reference itself is refused, wherever
# it appears — you cannot even hold one of these.
#
# `S` is the exception, and it earns it: `sympy.S("1+1")` sympifies, but
# `sympy.S.Half` is an everyday singleton. Only the call form is refused.
_ATTR_CALL_ONLY = frozenset({"S"})
_FORBIDDEN_ATTRS_ANYWHERE = _FORBIDDEN_ATTR_CALLS - _ATTR_CALL_ONLY

_ATTR_REFUSAL = (
    "{name!r} is not allowed here — it evaluates text or touches the disk. "
    "Compute with expressions, and use the workspace tool for files."
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
        "subprocess, or open files. sympify/lambdify/parse_expr are refused — "
        "build expressions from sp.Symbol, not from strings. Timeout 10s. "
        "Use calculator for a single "
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


class _CellBlocked(BaseException):
    """Raised by the audit hook when the cell attempts a forbidden operation.

    `BaseException` for the same reason as `_CellDeadline`: `except
    Exception` in the model's own code must not be able to swallow it.
    """


# Audit events with no honest use inside a numerics cell. This is the layer
# that actually keeps the docstring's promise, because it fires on the
# *operation* rather than on the name someone spelled to reach it.
#
# The name denylist below could not do that, and the proof is in the history:
# it was written with `savetxt` and `save` on it, and `scipy.io.savemat`,
# `scipy.io.wavfile.write` and `from scipy.io import savemat` all still wrote
# real files to the repo root. Every denylist of names is one library away
# from being wrong; there is only one `open`.
_BLOCKED_AUDIT_EVENTS = frozenset(
    {
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.remove",
        "os.rename",
        "os.mkdir",
        "os.rmdir",
        "os.chmod",
        "os.link",
        "os.symlink",
        "os.truncate",
        # os.putenv / os.unsetenv are deliberately absent. They were on this
        # list for one probe run, and `import scipy.sparse` tripped it: the
        # import machinery sets environment variables, so blocking them broke
        # legitimate numerics before the cell ran a line of its own. Setting a
        # variable inside this process is not a write, a process, or a packet.
        "subprocess.Popen",
        "socket.connect",
        "socket.bind",
        "socket.sendto",
        "ctypes.dlopen",
        "ctypes.dlsym",
        "ctypes.call_function",
        "shutil.copyfile",
        "shutil.move",
        "shutil.rmtree",
        "webbrowser.open",
        "urllib.Request",
        "pickle.find_class",
    }
)

# Any of these in an open() mode means the call intends to modify something.
# Read modes stay allowed: importing a module opens files, and blocking that
# would mean the cell could not `import sympy`.
_WRITE_MODE_CHARS = frozenset("wax+")

_cell_local = threading.local()
_audit_lock = threading.Lock()
_audit_installed = False


def _cell_audit(event: str, args: tuple[Any, ...]) -> None:
    """Process-wide hook that is inert except on a thread running a cell.

    `sys.addaudithook` cannot be removed once installed, so this has to be
    safe for the whole application forever. It is: the first line returns for
    every thread that is not executing a cell, which is all of them almost
    all of the time, and the only way out of here is a deliberate raise.

    Thread state rather than a set of thread ids on purpose — ids are reused
    after a thread dies, and the timeout path deliberately abandons threads.
    """
    if not getattr(_cell_local, "in_cell", False):
        return
    if event in _BLOCKED_AUDIT_EVENTS:
        raise _CellBlocked(event)
    if event == "open":
        mode = args[1] if len(args) >= 2 else ""
        if isinstance(mode, str) and not _WRITE_MODE_CHARS.isdisjoint(mode):
            raise _CellBlocked(f"open(..., {mode!r})")


def _install_audit_hook() -> None:
    """Installed on first use, so the app pays nothing until a cell runs."""
    global _audit_installed
    with _audit_lock:
        if _audit_installed:
            return
        sys.addaudithook(_cell_audit)
        _audit_installed = True


class _CellDeadline(BaseException):
    """Raised inside the worker thread when the cell runs past its deadline.

    A `BaseException` and not an `Exception` so that `try: ... except
    Exception: pass` in the model's own code cannot swallow its own kill
    switch. Nothing in the cell can name it: the sandbox refuses identifiers
    that start with an underscore.
    """


def _run_timed(code: str) -> str:
    """Ten seconds, and this time it is true.

    The previous version wrapped the pool in `with`, so on timeout
    `__exit__` called `shutdown(wait=True)` and joined the runaway thread —
    forever. `while True: pass` did not time out; it hung the agent, with the
    tool description still promising "Timeout 10s".

    Threads cannot be killed from outside, so there are two layers. The tracer
    below raises inside the cell on the next bytecode line, which handles any
    loop written in Python. If the cell is stuck inside one long C call
    instead, the tracer never gets a line event, so the future's own timeout
    fires two seconds later and we walk away from the thread without joining
    it. That leaks a thread, which is bad; hanging the assistant is worse.
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(_run_cell, code)
        try:
            return future.result(timeout=_TIMEOUT_S + _TIMEOUT_GRACE_S)
        except concurrent.futures.TimeoutError as exc:
            raise TimeoutError("python timeout") from exc
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _trace_deadline(deadline: float) -> Any:
    """A line tracer that stops the cell once the clock runs out."""

    def _trace(frame: Any, event: str, arg: Any) -> Any:
        if time.monotonic() > deadline:
            raise _CellDeadline()
        return _trace

    return _trace


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
    # The clock starts here rather than at the top of the function: importing
    # sympy and numpy is the tool's own cost, not the model's, and on a cold
    # process it can eat most of the budget on its own.
    _install_audit_hook()
    _cell_local.in_cell = True
    sys.settrace(_trace_deadline(time.monotonic() + _TIMEOUT_S))
    try:
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
    except _CellDeadline as exc:
        raise TimeoutError("python timeout") from exc
    except _CellBlocked as exc:
        raise ValueError(
            f"{exc.args[0]} is not allowed in this cell. It runs in Arelis's "
            "own process: no files, no processes, no sockets. Use the "
            "workspace tool for files and plot for pictures."
        ) from exc
    finally:
        sys.settrace(None)
        _cell_local.in_cell = False

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
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_ATTR_CALLS:
                        raise ValueError(_ATTR_REFUSAL.format(name=alias.name))
        if isinstance(node, ast.Attribute) and str(node.attr).startswith("_"):
            raise ValueError("private attributes are not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ValueError(f"name {node.id!r} is not allowed")
        if isinstance(node, ast.Attribute):
            if str(node.attr) in _FORBIDDEN_ATTRS_ANYWHERE:
                raise ValueError(_ATTR_REFUSAL.format(name=node.attr))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_CALLS:
                raise ValueError(f"call {node.func.id!r} is not allowed")
            if node.func.id in _FORBIDDEN_ATTR_CALLS:
                raise ValueError(_ATTR_REFUSAL.format(name=node.func.id))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if str(node.func.attr) in _ATTR_CALL_ONLY:
                raise ValueError(_ATTR_REFUSAL.format(name=node.func.attr))
        # A dunder spelled inside a string is invisible to the Attribute and
        # Name rules above, which is how attrgetter('__class__') and
        # sympify("__import__('os')") both got through. Blanket-refusing them
        # is safe because a numerics cell has no legitimate use for one, and
        # enumerating every function that takes an attribute name as text is a
        # denylist that will always be shorter than the attack surface.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "__" in node.value:
                raise ValueError(
                    "a string containing '__' is not allowed — that is how an "
                    "attribute name gets smuggled past the checks"
                )
        # f-strings hold their literal halves in JoinedStr, not Constant.
        if isinstance(node, ast.JoinedStr):
            for piece in node.values:
                if (
                    isinstance(piece, ast.Constant)
                    and isinstance(piece.value, str)
                    and "__" in piece.value
                ):
                    raise ValueError(
                        "a string containing '__' is not allowed — that is how "
                        "an attribute name gets smuggled past the checks"
                    )
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
