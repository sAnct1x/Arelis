"""Child process for the Python cell.

Run this file by path (`python -I -B -u python_cell_runner.py`). It must not
import arelis. The parent sends the source on stdin after this process has
imported the numerics libraries and printed a ready line.

The allowlist is the original cell unless the parent sets science_io. That
flag adds matplotlib, corner, csv, seaborn, emcee, and astropy. Ordinary
Python writes (open, np.save, savefig) run in this turn's work folder, which
is the process cwd. Process launchers stay refused. Matplotlib is imported
before those stubs when a snippet asks for it. The parent sets
MPL_IGNORE_SYSTEM_FONTS, so that import uses the bundled fonts and does not
spawn system_profiler or fc-list.
"""

from __future__ import annotations

import ast
import io
import json
import os
import sys
import tempfile
import time
import traceback
import warnings
from pathlib import Path
from typing import Any, NoReturn

_TIMEOUT_S = 10.0
_MAX_OUTPUT = 8_000
_READY = "ARELIS_PY_READY\n"
_RESULT = "ARELIS_PY_RESULT "

# The cell on main. science_io adds the names below. It does not add these.
_BASE_IMPORTS = frozenset(
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
# MCMC and a figure need these. Off until python_cell.science_io is set.
_SCIENCE_IMPORTS = frozenset(
    {"matplotlib", "corner", "csv", "seaborn", "emcee", "astropy"}
)
_SCIENCE_IO = False

# With science_io off, matplotlib and seaborn are chart imports, as on main.
_BASE_CHARTS = frozenset({"matplotlib", "pyplot", "pylab", "seaborn", "plotly"})
# These two become real imports when the flag is on. pyplot stays a chart.
_SCIENCE_CHARTS_KEPT = frozenset({"pyplot", "pylab", "plotly"})

_FORBIDDEN_CALLS = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        # vars() stays callable. vars(numpy)["lo"+"ad"] is not an Attribute
        # node, so a denylist cannot see it.
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

_FORBIDDEN_ATTR_CALLS = frozenset(
    {
        "sympify",
        "parse_expr",
        "parse_latex",
        "lambdify",
        "S",
        "eval",
        "exec",
        "evalf_",
        "preview",
        "run",
        "system",
        "popen",
        "spawn",
        "check_output",
        "check_call",
        "attrgetter",
        "methodcaller",
        "genfromtxt",
        "fromfile",
        "tofile",
        "memmap",
        "savemat",
        "mmwrite",
        "imsave",
        "imwrite",
        "to_csv",
        "to_excel",
        "to_pickle",
        "dump",
        "mkdir",
        "makedirs",
        "remove",
        "unlink",
        "rename",
        "rmtree",
    }
)

_ATTR_CALL_ONLY = frozenset({"S"})

_ATTR_REFUSAL = (
    "{name!r} is not allowed here, it evaluates text or touches the disk. "
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

_READY_SENT = False
# Matplotlib's font cache and library temp files. Not the work folder.
_CACHE_ROOT: Path | None = None
_AGG_LOCKED = False


class _CellBlocked(BaseException):
    """Raised by a process stub. BaseException so the cell cannot swallow it."""


class _CellRefusedError(ValueError):
    """A sandbox rule. A ValueError from the snippet is not one of these."""


class _CellDeadline(BaseException):
    """Raised by the line tracer. BaseException for the same reason."""


class _ChartImportError(ValueError):
    """Chart library import. The parent copies these fields onto the tool result.

    The message still tells the model what to do. The loop does not read it.
    """

    refusal = "chart_import"
    next_tool = "plot"

    def __init__(self, name: str) -> None:
        self.import_name = name
        super().__init__(
            f"import {name!r} is not allowed in this cell. "
            "Call plot with the data: pass xs and ys as comma-separated numbers "
            "and out='name.png'. path= is a CSV table, not the PNG."
        )


_BASE_LIST = (
    "math, cmath, statistics, fractions, decimal, itertools, functools, "
    "collections, operator, copy, json, re, datetime, sympy, numpy, scipy, "
    "and mpmath"
)
_SCIENCE_LIST = (
    "math, cmath, statistics, fractions, decimal, itertools, functools, "
    "collections, operator, copy, json, re, datetime, sympy, numpy, scipy, "
    "emcee, astropy, matplotlib, corner, csv, seaborn, and mpmath"
)


def _allowed_imports() -> frozenset[str]:
    if _SCIENCE_IO:
        return _BASE_IMPORTS | _SCIENCE_IMPORTS
    return _BASE_IMPORTS


def _chart_imports() -> frozenset[str]:
    if _SCIENCE_IO:
        return _SCIENCE_CHARTS_KEPT
    return _BASE_CHARTS


def _forbidden_calls() -> frozenset[str]:
    return _FORBIDDEN_CALLS


def _forbidden_attr_calls() -> frozenset[str]:
    return _FORBIDDEN_ATTR_CALLS


def _forbidden_attrs_anywhere() -> frozenset[str]:
    return _forbidden_attr_calls() - _ATTR_CALL_ONLY


def _import_refusal(name: str) -> NoReturn:
    if name in _chart_imports():
        raise _ChartImportError(name)
    listed = _SCIENCE_LIST if _SCIENCE_IO else _BASE_LIST
    raise _CellRefusedError(
        f"import {name!r} is not allowed. "
        f"{listed} are allowed. os and subprocess are not."
    )


def _candidate_sites(exe: Path) -> list[Path]:
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    return [
        # Embeddable installer: python.exe beside Lib\\site-packages.
        exe.parent / "Lib" / "site-packages",
        # Virtualenv on Windows: Scripts\\python.exe, site one level up.
        exe.parent.parent / "Lib" / "site-packages",
        # Virtualenv on POSIX.
        exe.parent.parent / "lib" / version / "site-packages",
    ]


def _force_agg() -> None:
    """Keep matplotlib on Agg. A later use() call cannot switch it."""
    global _AGG_LOCKED
    os.environ["MPLBACKEND"] = "Agg"
    if _AGG_LOCKED or "matplotlib" not in sys.modules:
        return
    import matplotlib

    matplotlib.use("Agg", force=True)
    real = matplotlib.use

    def _locked(*_args: Any, **_kwargs: Any) -> Any:
        return real("Agg", force=True)

    matplotlib.use = _locked
    _AGG_LOCKED = True


def _announce() -> None:
    """Tell the parent the libraries are in. Once."""
    global _READY_SENT
    if _READY_SENT:
        return
    _READY_SENT = True
    sys.stdout.write(_READY)
    sys.stdout.flush()


def _prepare_cache() -> None:
    """Private folder for the font cache and library temp files.

    The path is a fresh temp directory, not the working directory, so a
    relative ``savefig("fig.png")`` does not land here.
    """
    global _CACHE_ROOT
    cache = Path(tempfile.mkdtemp(prefix="arelis-mpl-"))
    root = Path(os.path.abspath(cache))
    _CACHE_ROOT = root
    text = str(root)
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["MPLCONFIGDIR"] = text
    os.environ["HOME"] = text
    os.environ["USERPROFILE"] = text
    os.environ["APPDATA"] = text
    os.environ["LOCALAPPDATA"] = text
    os.environ["XDG_CACHE_HOME"] = text
    os.environ["XDG_CONFIG_HOME"] = text
    os.environ["TMPDIR"] = text
    os.environ["TMP"] = text
    os.environ["TEMP"] = text
    # mkdtemp cached the system temp dir. astropy's mmap probe calls
    # mkstemp() with no directory, and that write has to stay in this cache.
    tempfile.tempdir = text


def _needs_matplotlib(code: str) -> bool:
    """True when the snippet imports matplotlib, corner, or seaborn.

    A cell that does not plot should not pay for the matplotlib import.
    That import builds the font cache, so it has to finish before launchers
    are stubbed.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name.split(".", 1)[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root:
                names = [root]
        if "matplotlib" in names or "corner" in names or "seaborn" in names:
            return True
    return False


def _warm_matplotlib() -> None:
    """Import pyplot before launchers are stubbed, on the bundled fonts.

    The parent sets ``MPL_IGNORE_SYSTEM_FONTS``. Without it, macOS lists
    fonts by spawning ``system_profiler``, and a fresh cache per cell
    repeats that scan until a test outlives pytest's 90s limit.
    """
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as pyplot

        del pyplot
    except Exception:
        # No matplotlib: the cell still runs.
        return
    _force_agg()


def _wipe_cache() -> None:
    """Delete the private cache."""
    root = _CACHE_ROOT
    if root is None or not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            try:
                os.remove(os.path.join(dirpath, name))
            except OSError:
                pass
        for name in dirnames:
            try:
                os.rmdir(os.path.join(dirpath, name))
            except OSError:
                pass
    try:
        os.rmdir(root)
    except OSError:
        pass


def _enable_sites() -> None:
    """Put this interpreter's site-packages back. ``-I`` may have dropped it.

    A virtualenv hides packages when pyvenv.cfg is ignored. The Windows
    installer is an embeddable tree: python.exe and Lib\\site-packages are
    siblings, and a ``._pth`` file is what normally puts that folder on the
    path. Adding it here covers both layouts. ``addsitedir`` also runs the
    ``.pth`` files numpy needs to find its libraries.
    """
    import site

    exe = Path(sys.executable).resolve()
    for folder in _candidate_sites(exe):
        if folder.is_dir():
            site.addsitedir(str(folder))


_OS_LAUNCH_NAMES = (
    "fork",
    "forkpty",
    "posix_spawn",
    "posix_spawnp",
    "execl",
    "execle",
    "execlp",
    "execlpe",
    "execv",
    "execve",
    "execvp",
    "execvpe",
    "spawnl",
    "spawnle",
    "spawnlp",
    "spawnlpe",
    "spawnv",
    "spawnve",
    "spawnvp",
    "spawnvpe",
    "startfile",
)


def _refuse_process(*_args: Any, **_kwargs: Any) -> NoReturn:
    raise _CellBlocked("starting a process is not allowed in this cell.")


def _replace_functions(targets: dict[int, Any]) -> None:
    """Point every module alias at the replacement. vars(module) sees it."""
    if not targets:
        return
    for module in list(sys.modules.values()):
        mapping = getattr(module, "__dict__", None)
        if not isinstance(mapping, dict):
            continue
        for name, value in list(mapping.items()):
            repl = targets.get(id(value))
            if repl is None:
                continue
            try:
                mapping[name] = repl
            except Exception:
                # A frozen or extension module dict cannot be patched.
                # The os and _posixsubprocess entries are the ones the
                # cell reaches through sys.modules.
                pass


def _stub_process_launchers() -> None:
    """Refuse process launch. fork_exec never looks like Popen.

    The optional matplotlib import has already finished, so it is not the
    one spawn this cell allows. After this, every alias of these functions
    raises.
    """
    found: dict[int, Any] = {}

    def take(fn: Any) -> None:
        if callable(fn):
            found[id(fn)] = _refuse_process

    for name in _OS_LAUNCH_NAMES:
        take(getattr(os, name, None))
    import subprocess

    take(getattr(subprocess, "Popen", None))
    for mod_name in ("posix", "nt", "_posixsubprocess", "_winapi"):
        module = sys.modules.get(mod_name)
        if module is None:
            continue
        if mod_name == "_posixsubprocess":
            take(getattr(module, "fork_exec", None))
        elif mod_name == "_winapi":
            for attr in dir(module):
                if attr.startswith("CreateProcess"):
                    take(getattr(module, attr, None))
        else:
            for name in _OS_LAUNCH_NAMES:
                take(getattr(module, name, None))
    _replace_functions(found)


def _set_cwd(raw: Any) -> None:
    """Run the cell in the per-turn work folder the parent created."""
    text = str(raw or "").strip()
    if not text:
        return
    try:
        folder = Path(os.path.abspath(text))
    except OSError:
        return
    if folder.is_dir():
        os.chdir(folder)


_CHART_SUFFIXES = {".png", ".svg"}


def _work_dir() -> Path | None:
    try:
        folder = Path(os.getcwd())
    except OSError:
        return None
    return folder if folder.is_dir() else None


def _save_open_figures() -> None:
    """Write leftover matplotlib figures into the work folder as PNG.

    savefig already landed a file, so those figures stay as the cell left
    them. A plot that was never saved still has to show up as the turn figure.
    """
    if "matplotlib" not in sys.modules:
        return
    folder = _work_dir()
    if folder is None:
        return
    try:
        existing = [
            path
            for path in folder.iterdir()
            if path.is_file() and path.suffix.lower() in _CHART_SUFFIXES
        ]
    except OSError:
        return
    if existing:
        return
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return
    try:
        numbers = list(plt.get_fignums())
    except Exception:
        return
    for index, number in enumerate(numbers, start=1):
        name = "figure.png" if index == 1 else f"figure-{index}.png"
        try:
            plt.figure(number).savefig(folder / name)
        except Exception:
            continue


def _collect_charts() -> list[dict[str, str]]:
    folder = _work_dir()
    if folder is None:
        return []
    found: list[dict[str, str]] = []
    try:
        paths = list(folder.iterdir())
    except OSError:
        return []
    for path in paths:
        try:
            if not path.is_file() or path.suffix.lower() not in _CHART_SUFFIXES:
                continue
            found.append({"name": path.name, "abs_path": str(path.resolve())})
        except OSError:
            continue
    found.sort(key=lambda item: (0 if item["name"].lower().endswith(".png") else 1, item["name"]))
    return found


def _chart_payload() -> dict[str, Any]:
    """Same abs_path keys plot puts on a successful chart."""
    charts = _collect_charts()
    if not charts:
        return {}
    first = charts[0]
    suffix = Path(first["name"]).suffix.lower()
    return {
        "path": first["name"],
        "abs_path": first["abs_path"],
        "format": suffix.lstrip("."),
        "title": Path(first["name"]).stem,
        "charts": charts,
    }


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
                if name not in _allowed_imports():
                    _import_refusal(name)
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _forbidden_attr_calls():
                        raise _CellRefusedError(_ATTR_REFUSAL.format(name=alias.name))
        if isinstance(node, ast.Attribute) and str(node.attr).startswith("_"):
            raise _CellRefusedError("private attributes are not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise _CellRefusedError(f"name {node.id!r} is not allowed")
        if isinstance(node, ast.Attribute):
            if str(node.attr) in _forbidden_attrs_anywhere():
                raise _CellRefusedError(_ATTR_REFUSAL.format(name=node.attr))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _forbidden_calls():
                raise _CellRefusedError(f"call {node.func.id!r} is not allowed")
            if node.func.id in _forbidden_attr_calls():
                raise _CellRefusedError(_ATTR_REFUSAL.format(name=node.func.id))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if str(node.func.attr) in _ATTR_CALL_ONLY:
                raise _CellRefusedError(_ATTR_REFUSAL.format(name=node.func.attr))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "__" in node.value:
                raise _CellRefusedError(
                    "a string containing '__' is not allowed, that is how an "
                    "attribute name gets smuggled past the checks"
                )
        if isinstance(node, ast.JoinedStr):
            for piece in node.values:
                if (
                    isinstance(piece, ast.Constant)
                    and isinstance(piece.value, str)
                    and "__" in piece.value
                ):
                    raise _CellRefusedError(
                        "a string containing '__' is not allowed, that is how "
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
            raise _CellRefusedError("async/yield is not allowed")


def _safe_import(
    name: str,
    globals: Any = None,
    locals: Any = None,
    fromlist: tuple[str, ...] = (),
    level: int = 0,
) -> Any:
    if level:
        raise _CellRefusedError("relative imports are not allowed")
    root = str(name or "").split(".", 1)[0]
    if root not in _allowed_imports():
        _import_refusal(root)
    module = __import__(name, globals, locals, fromlist, 0)
    if root == "matplotlib" or "matplotlib" in sys.modules:
        _force_agg()
    return module


def _namespace() -> dict[str, Any]:
    import cmath
    import collections
    import copy
    import datetime
    import decimal
    import fractions
    import functools
    import itertools
    import json as json_mod
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
        "vars": vars,
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
        "open": open,
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
        "json": json_mod,
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
    if _SCIENCE_IO:
        import csv as csv_mod

        ns["csv"] = csv_mod
        try:
            import emcee

            ns["emcee"] = emcee
        except ImportError:
            pass
    try:
        import mpmath

        ns["mpmath"] = mpmath
    except ImportError:
        pass
    return ns


def _trace_deadline(deadline: float) -> Any:
    def _trace(frame: Any, event: str, arg: Any) -> Any:
        if time.monotonic() > deadline:
            raise _CellDeadline()
        return _trace

    return _trace


def _execute(code: str, namespace: dict[str, Any]) -> str:
    tree = ast.parse(code, mode="exec")
    _assert_safe(tree)
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
    # The clock starts after the libraries are imported. That cost is the
    # parent's import budget, not these 10 seconds.
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
    finally:
        sys.settrace(None)

    out = buf.getvalue()
    if last_value is not None:
        shown = str(last_value)
        if out and not out.endswith("\n"):
            out += "\n"
        out += shown
    text = (out or "").strip() or (
        "(no output, print the result, or leave a final expression)"
    )
    if len(text) > _MAX_OUTPUT:
        text = text[:_MAX_OUTPUT] + "\n…(truncated)"
    return text


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(_RESULT + json.dumps(payload) + "\n")
    sys.stdout.flush()


def _failure_text(exc: BaseException) -> str:
    """The snippet's traceback. Runner frames are not the error."""
    tb = exc.__traceback__
    while tb is not None:
        filename = tb.tb_frame.f_code.co_filename
        if filename == __file__ or filename.startswith("<frozen"):
            tb = tb.tb_next
            continue
        break
    return "".join(traceback.format_exception(type(exc), exc, tb)).rstrip()


def _fail(kind: str, exc: BaseException, **extra: Any) -> None:
    """Error payload. The type is the class name, not the message text."""
    payload: dict[str, Any] = {
        "ok": False,
        "status": "bad_args",
        "kind": kind,
        "error_type": type(exc).__name__,
    }
    payload.update(extra)
    if "message" not in payload and kind != "timeout":
        if kind in {"failed", "syntax"}:
            payload["message"] = _failure_text(exc)
            payload["exc_message"] = str(exc)
        else:
            payload["message"] = str(exc)
    _emit(payload)


def main() -> None:
    global _SCIENCE_IO
    _prepare_cache()
    try:
        _enable_sites()
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except Exception:
            # Older interpreters have no reconfigure. Buffering still follows -u.
            pass
        warnings.filterwarnings("ignore")
        # The parent writes stdin before it waits for READY. Read it first so
        # a cell that never plots does not build the font cache, and so the
        # science flag is known before the namespace is built.
        raw = sys.stdin.read()
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            _announce()
            _fail("failed", exc, message="the cell could not read its input")
            return
        if not isinstance(payload, dict):
            _announce()
            _emit(
                {
                    "ok": False,
                    "status": "bad_args",
                    "kind": "failed",
                    "message": "the cell could not read its input",
                }
            )
            return
        _SCIENCE_IO = bool(payload.get("science_io"))
        code = str(payload.get("code") or "")
        namespace = _namespace()
        if _SCIENCE_IO and _needs_matplotlib(code):
            _warm_matplotlib()
        _set_cwd(payload.get("work"))
        _stub_process_launchers()
        _announce()
        try:
            text = _execute(code, namespace)
        except _CellDeadline as exc:
            _fail("timeout", exc)
        except _ChartImportError as exc:
            _fail(
                "refused",
                exc,
                message=str(exc),
                refusal=exc.refusal,
                next_tool=exc.next_tool,
            )
        except _CellBlocked as exc:
            _fail("refused", exc)
        except _CellRefusedError as exc:
            _fail("refused", exc)
        except SyntaxError as exc:
            _fail("syntax", exc)
        except Exception as exc:
            _fail("failed", exc)
        else:
            _save_open_figures()
            result = {"ok": True, "output": text}
            result.update(_chart_payload())
            _emit(result)
    finally:
        _wipe_cache()


if __name__ == "__main__":
    main()
