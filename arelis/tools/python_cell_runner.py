"""Child process for the Python cell.

Run this file by path (`python -I -B -u python_cell_runner.py`). It must not
import arelis. The parent sends the source on stdin after this process has
imported the numerics libraries and printed a ready line.

The allowlist is the original cell unless the parent sets science_io. That
flag adds matplotlib, corner, csv, seaborn, emcee, and astropy, and it allows
numpy and astropy file IO plus savefig into the room's results folder.
The audit hook is the boundary either way. It refuses new processes, sockets,
ctypes, and directory listings outside the workspace. A create with execute
permission is refused everywhere. With the flag on, a write has to stay in
the results folder and a read may stay in the workspace. Library reads stay
allowed. The font scan, when a snippet imports matplotlib, runs before the hook.
"""

from __future__ import annotations

import ast
import faulthandler
import io
import json
import os
import signal
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
# numpy/astropy file IO and savefig. Allowed only while science_io is on.
# open() is the same switch: the hook then limits the path.
_SCIENCE_ATTRS = frozenset(
    {"save", "savetxt", "load", "loadtxt", "write", "writeto", "savefig", "open"}
)

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
        "os.fork",
        "os.forkpty",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        # 3.14 audits the launcher Popen uses. It is not the Popen event.
        "_posixsubprocess.fork_exec",
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
# os.open's audit event passes the permission mode as None. The wrapper
# stashes the real mode so the hook can refuse an executable create.
_OS_OPEN_MODE: int | None = None
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
    if _SCIENCE_IO:
        return _FORBIDDEN_CALLS
    return _FORBIDDEN_CALLS | {"open"}


def _forbidden_attr_calls() -> frozenset[str]:
    if _SCIENCE_IO:
        return _FORBIDDEN_ATTR_CALLS
    return _FORBIDDEN_ATTR_CALLS | _SCIENCE_ATTRS


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


def _font_roots() -> list[Path]:
    """OS font folders. Matplotlib's realpath walks their parents too."""
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
    return roots


def _font_read(path: Path) -> bool:
    """Matplotlib opens the OS font folder. That is not the user's files."""
    return _under_roots(path, _font_roots())


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
        if "matplotlib" in names or "corner" in names or "seaborn" in names:
            return True
    return False


def _warm_matplotlib() -> None:
    """Build the font cache before the hook. ``fc-list`` is a process."""
    _cell_diag("warm begin")
    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as pyplot

        del pyplot
    except Exception:
        # No matplotlib: the cell still runs. A later import is refused by the hook
        # if it tries to start a process.
        _cell_diag("warm failed")
        return
    _force_agg()
    _cell_diag("warm end")


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


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _is_write(mode: Any, flags: Any) -> bool:
    """True when this open writes. An executable create is refused outright.

    ``os.open`` audits ``open(path, None, flags)`` and drops the permission
    mode. ``_OS_OPEN_MODE`` is that mode, stashed by the wrapper. Any execute
    bit on a create is refused, including inside the results folder.
    """
    try:
        flag = int(flags or 0)
    except (TypeError, ValueError):
        flag = 0
    perm = _as_int(mode)
    if perm is None:
        perm = _as_int(_OS_OPEN_MODE)
    creat = bool(flag & getattr(os, "O_CREAT", 0))
    if creat and perm is not None and perm & 0o111:
        raise _CellBlocked("creating an executable is not allowed in this cell.")
    if isinstance(mode, bytes):
        mode = os.fsdecode(mode)
    text = "" if mode is None else str(mode)
    if any(ch in text for ch in "wax+"):
        return True
    bits = (
        os.O_WRONLY
        | os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_APPEND", 0)
        | getattr(os, "O_TRUNC", 0)
    )
    return bool(flag & bits)


def _install_open_guard() -> None:
    """Remember os.open's permission mode. The audit event does not carry it."""
    global _OS_OPEN_MODE
    real = os.open

    def guarded(
        path: Any,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        global _OS_OPEN_MODE
        previous = _OS_OPEN_MODE
        _OS_OPEN_MODE = mode if _as_int(mode) is not None else None
        try:
            if dir_fd is None:
                return real(path, flags, mode)
            return real(path, flags, mode, dir_fd=dir_fd)
        finally:
            _OS_OPEN_MODE = previous

    for module in list(sys.modules.values()):
        mapping = getattr(module, "__dict__", None)
        if not isinstance(mapping, dict):
            continue
        for name, value in list(mapping.items()):
            if value is real:
                try:
                    mapping[name] = guarded
                except Exception:
                    # A frozen or extension module dict cannot be patched.
                    # os.open is assigned again below, which is the lookup
                    # matplotlib.os and the other aliases actually use.
                    pass
    os.open = guarded


_LIST_EVENTS = frozenset({"os.listdir", "os.scandir", "os.walk", "os.fwalk"})
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
    """Refuse process launch before the hook. fork_exec never audits as Popen.

    The font scan has already run, so its fc-list still used the real
    launcher. After this, every alias of these functions raises.
    """
    found: dict[int, Any] = {}

    def take(fn: Any) -> None:
        if callable(fn):
            found[id(fn)] = _refuse_process

    for name in _OS_LAUNCH_NAMES:
        take(getattr(os, name, None))
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


def _listing_allowed(raw: Any) -> bool:
    """A directory list may stay in the workspace, the libraries, or the cache."""
    if raw is None:
        return False
    path = _as_path(raw)
    if path is None:
        return False
    return bool(
        _library_read(path)
        or _font_read(path)
        or _under_roots(path, _WORK_READ)
        or _cache_path(path)
    )


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
    if event in _CACHE_ONLY_EVENTS:
        if _paths_in_cache(event, args):
            return
        raise _CellBlocked(_refusal(event))
    if event in _BLOCKED_AUDIT_EVENTS:
        raise _CellBlocked(_refusal(event))
    if event in _LIST_EVENTS:
        raw = args[0] if args else None
        if _listing_allowed(raw):
            return
        raise _CellBlocked(
            "listing a directory outside this room is not allowed in this cell."
        )
    if event != "open" or not args:
        return
    mode = args[1] if len(args) > 1 else ""
    flags = args[2] if len(args) > 2 else 0
    path = _as_path(args[0])
    if path is None:
        return
    if _is_write(mode, flags):
        if _SCIENCE_IO and (_under_roots(path, _WORK_WRITE) or _cache_path(path)):
            return
        if _SCIENCE_IO:
            raise _CellBlocked(
                "opening a file to write it is not allowed in this cell. "
                "The path has to stay inside this room's results folder."
            )
        raise _CellBlocked(_refusal("opening a file to write it"))
    if _library_read(path):
        return
    if _SCIENCE_IO and (
        _font_read(path) or _under_roots(path, _WORK_READ) or _cache_path(path)
    ):
        return
    raise _CellBlocked(_refusal("reading a file outside the Python libraries"))


def _install_hook() -> None:
    # Roots are fixed before the cell runs. Later edits to sys.path do not
    # add a folder the hook will read. The font scan has already finished,
    # so every later Popen is refused.
    _read_roots()
    _stub_process_launchers()
    _install_open_guard()
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
    }
    if _SCIENCE_IO:
        safe_builtins["open"] = open
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


def _cell_diag(msg: str) -> None:
    """Temporary. The macOS worker death left no signal in the job log."""
    path = os.environ.get("PYTEST_CELL_DIAG", "")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(msg.rstrip() + "\n")
    except OSError:
        return


def _id_text() -> str:
    pid = os.getpid()
    pgrp = os.getpgrp() if hasattr(os, "getpgrp") else -1
    sid = os.getsid(0) if hasattr(os, "getsid") else -1
    ppid = os.getppid() if hasattr(os, "getppid") else -1
    return f"pid={pid} pgrp={pgrp} sid={sid} ppid={ppid}"


def _install_child_diag() -> None:
    path = os.environ.get("PYTEST_CELL_DIAG", "")
    if not path:
        return
    try:
        handle = open(path, "a", encoding="utf-8")
        faulthandler.enable(file=handle, all_threads=True)
    except OSError:
        return
    _cell_diag("child start " + _id_text())

    def _on_signal(signum: int, _frame: Any) -> None:
        _cell_diag(f"child signal {signum} " + _id_text())
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for name in ("SIGHUP", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, _on_signal)
        except (OSError, ValueError):
            continue


def main() -> None:
    global _SCIENCE_IO
    _install_child_diag()
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
