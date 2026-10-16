"""Child process for the Python cell.

Run this file by path (`python -I -B -u python_cell_runner.py`). It must not
import arelis. The parent sends the source on stdin after this process has
imported the numerics libraries and printed a ready line.

The AST checks are the same allowlist the cell has always had. They are not
the boundary. The audit hook is. It refuses new processes, sockets, ctypes,
and any write outside the room's results folder. Reads may stay inside the
workspace, same as the data cell's room rule. Library and OS font reads stay
allowed. Matplotlib may use a private cache folder the cell cannot name.
Name rules cannot see ``vars(numpy)["lo" + "ad"]``. The open still shows up here.
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
        "emcee",
        "astropy",
        "matplotlib",
        "corner",
        "csv",
        "mpmath",
    }
)

# matplotlib itself runs in the cell (Agg, workspace files only). These
# names still mean "draw it with the plot tool" rather than a library.
_CHART_IMPORTS = frozenset({"pyplot", "pylab", "seaborn", "plotly"})

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
        # node, so a denylist cannot see it. The hook refuses the open.
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
        "savez",
        "savez_compressed",
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
_FORBIDDEN_ATTRS_ANYWHERE = _FORBIDDEN_ATTR_CALLS - _ATTR_CALL_ONLY

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

# Same operations the in-process hook refused. os.putenv stays off the list:
# importing scipy sets environment variables, and that is not a file or a socket.
_BLOCKED_AUDIT_EVENTS = frozenset(
    {
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.chmod",
        "os.link",
        "os.symlink",
        "os.truncate",
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

_IN_HOOK = False
_READY_SENT = False
_READ_ROOTS: list[Path] | None = None
_WORK_READ: list[Path] = []
_WORK_WRITE: list[Path] = []
# Matplotlib's font cache and library temp files. Not a workspace root.
_CACHE_ROOT: Path | None = None
_AGG_LOCKED = False
# These stay refused everywhere except the private cache. A workspace file
# is written with open(), which the path check below already limits.
_CACHE_ONLY_EVENTS = {"os.remove": 1, "os.rmdir": 1, "os.mkdir": 1, "os.rename": 2}


class _CellBlocked(BaseException):
    """Raised by the audit hook. BaseException so the cell cannot swallow it."""


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


def _import_refusal(name: str) -> NoReturn:
    if name in _CHART_IMPORTS:
        raise _ChartImportError(name)
    raise _CellRefusedError(
        f"import {name!r} is not allowed. "
        "math/sympy/numpy/emcee are preloaded; os/subprocess are not."
    )


def _abs(path: Path) -> Path:
    return Path(os.path.abspath(path))


def is_unsafe_path(raw: str) -> bool:
    """True for UNC and NT device prefixes. String check only, no resolve."""
    text = (raw or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    if not text:
        return False
    if text[:5].lower() == "file:":
        rest = text[5:].replace("/", "\\")
        if rest.startswith("\\\\\\\\"):
            return True
        if rest.startswith("\\\\") and not rest.startswith("\\\\\\"):
            return True
    norm = text.replace("/", "\\")
    return norm.startswith("\\\\") or norm.startswith("\\??\\")


def lexically_inside(path: Path, root: Path) -> bool:
    """True when the path stays under root without following links.

    Same rule as data_cell_runner.lexically_inside.
    """
    if is_unsafe_path(str(path)):
        return False
    root_abs = _abs(root)
    candidate = path if path.is_absolute() else Path.cwd() / path
    if is_unsafe_path(str(candidate)):
        return False
    try:
        Path(os.path.normcase(os.path.abspath(candidate))).relative_to(
            Path(os.path.normcase(str(root_abs)))
        )
    except ValueError:
        return False
    return True


def is_reparse(path: Path) -> bool:
    """Symlink, or a Windows junction on 3.12+ (is_symlink misses junctions)."""
    try:
        if path.is_symlink():
            return True
    except OSError:
        return False
    checker = getattr(path, "is_junction", None)
    if not callable(checker):
        return False
    try:
        return bool(checker())
    except OSError:
        return False


def reparse_leaves(path: Path, root: Path) -> bool:
    """True when a symlink or junction on the way resolves outside root."""
    root_abs = _abs(root)
    candidate = path if path.is_absolute() else Path.cwd() / path
    try:
        rel = os.path.relpath(os.path.abspath(candidate), str(root_abs))
    except ValueError:
        return True
    if rel.startswith(".."):
        return True
    current = root_abs
    for part in Path(rel).parts:
        current = current / part
        if not is_reparse(current):
            continue
        try:
            target = Path(os.path.realpath(current))
        except OSError:
            return True
        if not lexically_inside(target, root_abs):
            return True
        current = target
    return False


def _add_root(roots: list[Path], seen: set[str], raw: Path) -> None:
    try:
        key = os.path.normcase(os.path.abspath(raw))
    except OSError:
        return
    if not key or key in seen:
        return
    seen.add(key)
    roots.append(Path(key))


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


def _compute_roots(exe: Path | None = None) -> list[Path]:
    """Directories a read may touch. Snapshotted so the cell cannot widen it.

    Stdlib and site-packages, plus the interpreter directory. The embeddable
    installer keeps packages in Lib\\site-packages next to python.exe, which
    ``-I`` can leave off sys.prefix. The runner's own directory is included
    for the same reason data_cell_runner._library_read allows it: an editable
    install runs this file from the source tree, not from site-packages.
    """
    roots: list[Path] = []
    seen: set[str] = set()
    if exe is None:
        for raw in (sys.prefix, sys.base_prefix, getattr(sys, "base_exec_prefix", "")):
            if raw:
                _add_root(roots, seen, Path(raw))
        for entry in list(sys.path):
            if not entry or not os.path.isabs(str(entry)):
                continue
            path = Path(entry)
            if path.suffix.lower() == ".zip":
                path = path.parent
            _add_root(roots, seen, path)
        exe_path = Path(sys.executable).resolve()
        _add_root(roots, seen, Path(__file__).resolve().parent)
    else:
        exe_path = Path(exe).resolve()
    _add_root(roots, seen, exe_path.parent)
    for site in _candidate_sites(exe_path):
        if site.is_dir():
            _add_root(roots, seen, site)
    return roots


def _read_roots() -> list[Path]:
    global _READ_ROOTS
    if _READ_ROOTS is None:
        _READ_ROOTS = _compute_roots()
    return _READ_ROOTS


def _library_read(path: Path, exe: Path | None = None) -> bool:
    """True when path is a stdlib or site-packages file, not a user's file."""
    if is_unsafe_path(str(path)):
        return False
    roots = _compute_roots(exe) if exe is not None else _read_roots()
    for root in roots:
        if lexically_inside(path, root) and not reparse_leaves(path, root):
            return True
    return False


def _set_work_roots(raw: Any) -> None:
    """Workspace folders for this cell. Resolved once, before the snippet runs.

    Reads use the workspace root, the data cell's room. Writes use only
    ``<root>/results``, the data cell's results folder.
    """
    global _WORK_READ, _WORK_WRITE
    read: list[Path] = []
    write: list[Path] = []
    seen_read: set[str] = set()
    seen_write: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            path = ""
            can_write = True
            if isinstance(item, str):
                path = item
            elif isinstance(item, dict):
                path = str(item.get("path") or "")
                can_write = bool(item.get("write", True))
            if not path.strip():
                continue
            _add_root(read, seen_read, Path(path))
            if can_write:
                _add_root(write, seen_write, Path(path) / "results")
    _WORK_READ = read
    _WORK_WRITE = write


def _under_roots(path: Path, roots: list[Path]) -> bool:
    """True when the resolved path stays inside one root.

    ``..`` is collapsed by abspath before the check. A symlink or junction
    that leaves the root is refused.
    """
    if is_unsafe_path(str(path)):
        return False
    for root in roots:
        if lexically_inside(path, root) and not reparse_leaves(path, root):
            return True
    return False


def _font_read(path: Path) -> bool:
    """Matplotlib opens the OS font folder. That is not the user's files."""
    roots: list[Path] = []
    windir = os.environ.get("SYSTEMROOT", "")
    if windir:
        roots.append(Path(windir) / "Fonts")
    for extra in (
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        "/Library/Fonts",
        "/System/Library/Fonts",
    ):
        roots.append(Path(extra))
    return _under_roots(path, roots)


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


def _cache_path(path: Path) -> bool:
    if _CACHE_ROOT is None:
        return False
    return _under_roots(path, [_CACHE_ROOT])


def _needs_matplotlib(code: str) -> bool:
    """True when the snippet imports matplotlib or corner.

    A NameError cell should not pay for a font scan. The scan is a process,
    so it has to finish before the hook is installed.
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
        if "matplotlib" in names or "corner" in names:
            return True
    return False


def _fontconfig_list(args: tuple[Any, ...]) -> bool:
    """Matplotlib's font scan. Not a general subprocess allow."""
    if not args:
        return False
    raw = args[0]
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    return Path(str(raw)).name.lower() in {"fc-list", "fc-list.exe"}


def _warm_matplotlib() -> None:
    """Build the font cache before the hook. ``fc-list`` is a process."""
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as pyplot

        del pyplot
    except Exception:
        # No matplotlib: the cell still runs. A later import is refused by the hook
        # if it tries to start a process.
        return
    _force_agg()


def _wipe_cache() -> None:
    """Delete the private cache. The hook is already installed, so no rmtree."""
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


def _is_write(mode: Any, flags: Any) -> bool:
    if isinstance(mode, bytes):
        mode = os.fsdecode(mode)
    text = "" if mode is None else str(mode)
    if any(ch in text for ch in "wax+"):
        return True
    try:
        flag = int(flags or 0)
    except (TypeError, ValueError):
        flag = 0
    bits = (
        os.O_WRONLY
        | os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_APPEND", 0)
        | getattr(os, "O_TRUNC", 0)
    )
    return bool(flag & bits)


def _as_path(raw: Any) -> Path | None:
    if isinstance(raw, int):
        return None
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    if raw is None:
        return None
    text = str(raw)
    if not text or text in {"<fdopen>", "<stdin>", "<stdout>", "<stderr>", "<python>"}:
        return None
    if is_unsafe_path(text):
        raise _CellBlocked(_refusal("reading a file outside the Python libraries"))
    return Path(text)


def _refusal(what: str) -> str:
    return (
        f"{what} is not allowed in this cell. No files, no processes, no sockets. "
        "Use the workspace tool for files and plot for pictures."
    )


def _audit(event: str, args: tuple[Any, ...]) -> None:
    global _IN_HOOK
    if _IN_HOOK:
        return
    _IN_HOOK = True
    try:
        _audit_inner(event, args)
    finally:
        _IN_HOOK = False


def _paths_in_cache(event: str, args: tuple[Any, ...]) -> bool:
    """True when every path on a cache-only event stays in the private cache."""
    count = _CACHE_ONLY_EVENTS[event]
    if len(args) < count:
        return False
    for raw in args[:count]:
        path = _as_path(raw)
        if path is None or not _cache_path(path):
            return False
    return True


def _audit_inner(event: str, args: tuple[Any, ...]) -> None:
    if event == "subprocess.Popen" and _fontconfig_list(args):
        return
    if event in _CACHE_ONLY_EVENTS:
        if _paths_in_cache(event, args):
            return
        raise _CellBlocked(_refusal(event))
    if event in _BLOCKED_AUDIT_EVENTS:
        raise _CellBlocked(_refusal(event))
    if event != "open" or not args:
        return
    mode = args[1] if len(args) > 1 else ""
    flags = args[2] if len(args) > 2 else 0
    path = _as_path(args[0])
    if path is None:
        return
    if _is_write(mode, flags):
        if _under_roots(path, _WORK_WRITE) or _cache_path(path):
            return
        raise _CellBlocked(
            "opening a file to write it is not allowed in this cell. "
            "The path has to stay inside this room's results folder."
        )
    if (
        _library_read(path)
        or _font_read(path)
        or _under_roots(path, _WORK_READ)
        or _cache_path(path)
    ):
        return
    raise _CellBlocked(_refusal("reading a file outside the Python libraries"))


def _install_hook() -> None:
    # Roots are fixed before the cell runs. Later edits to sys.path do not
    # add a folder the hook will read.
    _read_roots()
    sys.addaudithook(_audit)


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
                    _import_refusal(name)
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_ATTR_CALLS:
                        raise _CellRefusedError(_ATTR_REFUSAL.format(name=alias.name))
        if isinstance(node, ast.Attribute) and str(node.attr).startswith("_"):
            raise _CellRefusedError("private attributes are not allowed")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise _CellRefusedError(f"name {node.id!r} is not allowed")
        if isinstance(node, ast.Attribute):
            if str(node.attr) in _FORBIDDEN_ATTRS_ANYWHERE:
                raise _CellRefusedError(_ATTR_REFUSAL.format(name=node.attr))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _FORBIDDEN_CALLS:
                raise _CellRefusedError(f"call {node.func.id!r} is not allowed")
            if node.func.id in _FORBIDDEN_ATTR_CALLS:
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
    if root not in _ALLOWED_IMPORTS:
        _import_refusal(root)
    module = __import__(name, globals, locals, fromlist, 0)
    if root == "matplotlib" or "matplotlib" in sys.modules:
        _force_agg()
    return module


def _namespace() -> dict[str, Any]:
    import cmath
    import collections
    import copy
    import csv as csv_mod
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
        "open": open,
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
        "csv": csv_mod,
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
    _prepare_cache()
    try:
        _enable_sites()
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except Exception:
            # Older interpreters have no reconfigure. Buffering still follows -u.
            pass
        warnings.filterwarnings("ignore")
        namespace = _namespace()
        # The parent writes stdin before it waits for READY. Read it first so
        # a cell that never plots does not build the font cache.
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
        code = str(payload.get("code") or "")
        if _needs_matplotlib(code):
            _warm_matplotlib()
        _install_hook()
        _announce()
        _set_work_roots(payload.get("roots"))
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
            _emit({"ok": True, "output": text})
    finally:
        _wipe_cache()


if __name__ == "__main__":
    main()
