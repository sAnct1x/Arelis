"""Child process for the Python cell.

Run this file by path (`python -I -B -u python_cell_runner.py`). It must not
import arelis. The parent sends the source on stdin after this process has
imported the numerics libraries and printed a ready line.

The allowlist is the original cell unless the parent sets science_io. That
flag adds corner, csv, seaborn, emcee, and astropy. matplotlib, pyplot, and
savefig stay allowed either way. Ordinary Python writes (open, np.save,
savefig) run in this turn's work folder, which is the process cwd. A write
outside that folder or a writable results folder is refused at run time, so
a path built in a variable still cannot change a file the user named.
Process launchers stay refused. An audit hook also refuses process launch,
network use, ctypes, imports of blocked modules, and reads of files outside
the work folder, workspace roots, results folders, and the interpreter or
library paths, at run time, even when those names come through a library
such as openpyxl or matplotlib. Matplotlib
is imported before the process stubs when a snippet asks for it. The parent
sets MPL_IGNORE_SYSTEM_FONTS, so that import uses the bundled fonts and does
not spawn system_profiler or fc-list.
"""

from __future__ import annotations

import _thread
import ast
import io
import json
import os
import sys
import tempfile
import threading
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
        "openpyxl",
        "mpmath",
        "matplotlib",
    }
)
# MCMC extras. Off until python_cell.science_io is set. matplotlib is already
# in the base set; the flag still adds the names below.
_SCIENCE_IMPORTS = frozenset(
    {"matplotlib", "corner", "csv", "seaborn", "emcee", "astropy"}
)
_SCIENCE_IO = False

# seaborn and the other chart names still redirect to plot. matplotlib does not.
_BASE_CHARTS = frozenset({"pylab", "seaborn", "plotly"})
# science_io widens imports. These names stay chart refusals either way.
_SCIENCE_CHARTS_KEPT = frozenset({"pylab", "plotly"})

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
    "openpyxl, and mpmath"
)
_SCIENCE_LIST = (
    "math, cmath, statistics, fractions, decimal, itertools, functools, "
    "collections, operator, copy, json, re, datetime, sympy, numpy, scipy, "
    "openpyxl, emcee, astropy, matplotlib, corner, csv, seaborn, and mpmath"
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


_WRITE_ROOTS: list[Path] = []
_READ_ROOTS: list[Path] = []
_IN_WRITE_HOOK = False
_NULL_DEVICES = frozenset({os.path.normcase(os.devnull), "nul"})
# Event name to (path argument positions, what the refusal calls the write).
_WRITE_EVENTS: dict[str, tuple[tuple[int, ...], str]] = {
    "os.remove": ((0,), "delete"),
    "os.rmdir": ((0,), "delete"),
    "shutil.rmtree": ((0,), "delete"),
    "os.rename": ((0, 1), "move"),
    "os.replace": ((0, 1), "move"),
    "os.link": ((0, 1), "write"),
    "os.symlink": ((1,), "write"),
    "os.mkdir": ((0,), "write"),
    "os.makedirs": ((0,), "write"),
    "os.chmod": ((0,), "write"),
    "os.chown": ((0,), "write"),
    "os.utime": ((0,), "write"),
    "os.truncate": ((0,), "write"),
}
_DIR_FD_ARG = {"os.remove": 1, "os.rmdir": 1, "os.mkdir": 2, "os.rename": 2, "os.replace": 2}

_WRITE_REFUSAL = (
    "This cell cannot change a file outside its work folder or a results "
    "folder. Call run_script with the same code so the file card can ask "
    "first. Nothing was changed there."
)
_READ_REFUSAL = (
    "This cell cannot read a file outside its work folder, a workspace "
    "folder, or a results folder. Call run_script with the same code so "
    "the file card can ask first, or use external_read for a file the "
    "user named."
)


def _is_write_open(mode: Any, flags: Any) -> bool:
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


def _as_text(raw: Any) -> str | None:
    if isinstance(raw, int) or raw is None:
        return None
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    text = os.fspath(raw) if isinstance(raw, os.PathLike) else str(raw)
    return text or None


def _fd_folder(fd: Any) -> str | None:
    if not isinstance(fd, int) or fd < 0:
        return None
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        pass
    try:
        import fcntl

        raw = fcntl.fcntl(fd, fcntl.F_GETPATH, b"\0" * 1024)  # type: ignore[attr-defined]
        return os.fsdecode(raw.split(b"\0", 1)[0])
    except (AttributeError, OSError, ImportError):
        return None


def _inside_root(text: str, root: Path) -> bool:
    try:
        target = Path(os.path.realpath(os.path.join(os.getcwd(), text)))
        base = Path(os.path.realpath(str(root)))
        Path(os.path.normcase(str(target))).relative_to(
            Path(os.path.normcase(str(base)))
        )
    except (OSError, ValueError):
        return False
    return True


def _writable_path(text: str) -> bool:
    if os.path.normcase(text) in _NULL_DEVICES:
        return True
    for root in _WRITE_ROOTS:
        if _inside_root(text, root):
            return True
    return False


def _readable_path(text: str) -> bool:
    if os.path.normcase(text) in _NULL_DEVICES:
        return True
    for root in _READ_ROOTS:
        if _inside_root(text, root):
            return True
    return False


def _check_write(op: str, raw: Any, folder: str | None = None) -> None:
    text = _as_text(raw)
    if text is None:
        return
    if folder is not None and not os.path.isabs(text):
        text = os.path.join(folder, text)
    if _writable_path(text):
        return
    raise _CellBlocked(_WRITE_REFUSAL)


def _check_read(raw: Any) -> None:
    text = _as_text(raw)
    if text is None:
        return
    if _readable_path(text):
        return
    raise _CellBlocked(_READ_REFUSAL)


_PROCESS_EVENTS = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.spawn",
        "os.posix_spawn",
        "os.startfile",
        "os.fork",
        "os.forkpty",
        "_winapi.CreateProcess",
    }
)
_NET_ADDRESS_EVENTS = frozenset({"socket.connect", "socket.sendto", "socket.bind"})
_NET_NAME_EVENTS = frozenset(
    {
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "socket.gethostbyname_ex",
        "socket.gethostbyaddr",
    }
)
# Loopback stays allowed; some libraries open a local socket. Bind treats
# "", 0.0.0.0 and :: as not local (listening on every interface).
_LOCAL_NAMES = frozenset({"", "localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"})
_BIND_ALL = frozenset({"", "0.0.0.0", "::"})
_PROCESS_REFUSAL = "starting a process is not allowed in this cell."
_NETWORK_REFUSAL = "the network is not allowed in this cell."
_CTYPES_REFUSAL = "ctypes is not allowed in this cell."


# Threads started by the cell, not the runner thread that executes it.
_CELL_MAIN_THREAD = 0
_CELL_THREADS: set[int] = set()
_CELL_THREAD_LOCK = threading.Lock()
_CELL_THREAD_HOOKED = False


def _register_cell_thread(ident: int) -> None:
    with _CELL_THREAD_LOCK:
        _CELL_THREADS.add(ident)


def _on_cell_started_thread() -> bool:
    ident = threading.get_ident()
    with _CELL_THREAD_LOCK:
        return ident != _CELL_MAIN_THREAD and ident in _CELL_THREADS


def _parent_starts_cell_thread() -> bool:
    if _audit_cell_on_stack():
        return True
    ident = threading.get_ident()
    with _CELL_THREAD_LOCK:
        return ident in _CELL_THREADS or ident == _CELL_MAIN_THREAD


def _install_cell_thread_tracking() -> None:
    """Record threads the cell starts, including descendants.

    A Thread target has no <python> frame when the target is a library
    function such as import_module. The hook still has to treat that
    thread as the cell. threading snapshots start_joinable_thread at
    import time, so Thread.start must be hooked there too.
    """
    global _CELL_MAIN_THREAD, _CELL_THREAD_HOOKED
    _CELL_MAIN_THREAD = threading.get_ident()
    with _CELL_THREAD_LOCK:
        _CELL_THREADS.clear()
        _CELL_THREADS.add(_CELL_MAIN_THREAD)
    if _CELL_THREAD_HOOKED:
        return
    _CELL_THREAD_HOOKED = True
    orig_new = _thread.start_new_thread
    orig_joinable = getattr(_thread, "start_joinable_thread", None)

    def _wrap_target(function: Any, from_cell: bool) -> Any:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if from_cell:
                _register_cell_thread(threading.get_ident())
            return function(*args, **kwargs)

        return wrapped

    def start_new_thread(function: Any, args: Any, kwargs: Any = None) -> int:
        from_cell = _parent_starts_cell_thread()
        if kwargs is None:
            kwargs = {}
        return orig_new(_wrap_target(function, from_cell), args, kwargs)

    _thread.start_new_thread = start_new_thread  # type: ignore[method-assign]
    if orig_joinable is not None:

        def start_joinable_thread(
            function: Any, handle: Any = None, daemon: bool = True
        ) -> Any:
            from_cell = _parent_starts_cell_thread()
            return orig_joinable(_wrap_target(function, from_cell), handle, daemon)

        _thread.start_joinable_thread = start_joinable_thread  # type: ignore[method-assign]
        # threading snapshots this at import time, so Thread.start
        # would otherwise keep the unwrapped builtin.
        if getattr(threading, "_start_joinable_thread", None) is orig_joinable:
            threading._start_joinable_thread = start_joinable_thread


def _norm_frame_name(filename: str) -> str:
    return filename.replace("\\", "/")


def _is_infra_frame(filename: str) -> bool:
    return (
        filename == __file__
        or filename.startswith("<frozen")
        or filename.startswith("<built-in")
        or "importlib" in filename
    )


def _is_loading_module_frame(filename: str, module_name: str) -> bool:
    """True when this frame is the module being imported, not its importer."""
    text = _norm_frame_name(filename)
    rel = module_name.replace(".", "/")
    if not rel or not text:
        return False
    for ext in (".py", ".pyc", ".pyo", ".so", ".pyd", ".dylib"):
        if text.endswith(ext):
            stem = text[: -len(ext)]
            break
    else:
        stem = text
    leaf = stem.rsplit("/", 1)[-1]
    if "." in leaf:
        directory, leaf = stem.rsplit("/", 1) if "/" in stem else ("", stem)
        leaf = leaf.split(".", 1)[0]
        stem = f"{directory}/{leaf}" if directory else leaf
    return (
        stem.endswith("/" + rel)
        or stem.endswith("/" + rel + "/__init__")
        or stem == rel
        or stem == rel + "/__init__"
    )


def _is_ctypes_frame(filename: str) -> bool:
    text = _norm_frame_name(filename)
    leaf = text.rsplit("/", 1)[-1]
    if (
        "/ctypes/" in text
        or text.endswith("/ctypes.py")
        or text.endswith("/ctypes.pyc")
    ):
        return True
    if leaf.startswith("ctypes.") or leaf.startswith("_ctypes"):
        return True
    return text.startswith("<frozen ctypes") or text.startswith("<frozen _ctypes")


# Stdlib names on the allowlist are not "libraries importing a
# dependency". functools or json can appear on an import_module stack
# without meaning the cell did not start the import.
_STDLIB_IMPORTS = frozenset(
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
        "csv",
    }
)


def _frame_is_allowed_library(filename: str) -> bool:
    if not filename or filename.startswith("<"):
        return False
    allowed = _allowed_imports() - _STDLIB_IMPORTS
    for part in _norm_frame_name(filename).split("/"):
        stem = part
        if stem.endswith(".py"):
            stem = stem[:-3]
        elif "." in stem:
            stem = stem.split(".", 1)[0]
        if stem in allowed:
            return True
    return False


def _audit_from_cell(
    *, loading_module: str | None = None, skip_ctypes: bool = False
) -> bool:
    """True when the audited call was initiated by the user cell.

    Allowed libraries import os, sys, socket, subprocess, and ctypes for
    their own use. The hook must not refuse those. A call compiled as
    <python> is the cell. The module being loaded is not the importer:
    import_module('socket') would otherwise look like socket.py itself
    made the import. A thread the cell started is also the cell, even
    when the target is a library function and <python> is not on that
    thread's stack.
    """
    frame = sys._getframe()
    while frame is not None:
        name = frame.f_code.co_filename
        if (
            _is_infra_frame(name)
            or (
                loading_module is not None
                and _is_loading_module_frame(name, loading_module)
            )
            or (skip_ctypes and _is_ctypes_frame(name))
        ):
            frame = frame.f_back
            continue
        if name == "<python>":
            return True
        if _frame_is_allowed_library(name):
            return False
        frame = frame.f_back
    return _on_cell_started_thread()


def _audit_cell_on_stack() -> bool:
    """True when the user cell is anywhere on the stack.

    load_workbook opens the file from zipfile, so the first frame is a
    library. The cell is still on the stack. Import-time reads before
    the cell starts are not.
    """
    frame = sys._getframe()
    while frame is not None:
        if frame.f_code.co_filename == "<python>":
            return True
        frame = frame.f_back
    return False


def _local_host(host: Any) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    text = str(host).strip().lower()
    return text in _LOCAL_NAMES or text.startswith("127.")


def _check_address(address: Any, *, bind: bool = False) -> None:
    if isinstance(address, (str, bytes)):
        return  # AF_UNIX path: a local socket file, not the network.
    host = address[0] if isinstance(address, tuple) and address else None
    if bind:
        raw = host
        if isinstance(raw, bytes):
            raw = raw.decode("ascii", "replace")
        text = "" if raw is None else str(raw).strip().lower()
        if text in _BIND_ALL:
            raise _CellBlocked(_NETWORK_REFUSAL)
    if _local_host(host):
        return
    raise _CellBlocked(_NETWORK_REFUSAL)


def _write_audit(event: str, args: tuple[Any, ...]) -> None:
    global _IN_WRITE_HOOK
    if _IN_WRITE_HOOK:
        return
    _IN_WRITE_HOOK = True
    try:
        _write_audit_inner(event, args)
    finally:
        _IN_WRITE_HOOK = False


def _write_audit_inner(event: str, args: tuple[Any, ...]) -> None:
    if event == "open":
        mode = args[1] if len(args) > 1 else ""
        flags = args[2] if len(args) > 2 else 0
        if args and _is_write_open(mode, flags):
            _check_write("write", args[0])
            return
        if args and _audit_cell_on_stack():
            _check_read(args[0])
        return
    if event in _PROCESS_EVENTS:
        raise _CellBlocked(_PROCESS_REFUSAL)
    if event == "sys.addaudithook":
        raise _CellBlocked("changing the audit hook is not allowed in this cell.")
    if event.startswith("ctypes.") and _audit_from_cell(skip_ctypes=True):
        raise _CellBlocked(_CTYPES_REFUSAL)
    if event == "import":
        name = str(args[0] or "") if args else ""
        root = name.split(".", 1)[0]
        if root and _audit_from_cell(loading_module=name) and root not in _allowed_imports():
            _import_refusal(root)
        return
    if event in _NET_ADDRESS_EVENTS and len(args) >= 2:
        _check_address(args[1], bind=(event == "socket.bind"))
        return
    if event in _NET_NAME_EVENTS and args and not _local_host(args[0]):
        raise _CellBlocked(_NETWORK_REFUSAL)
    spec = _WRITE_EVENTS.get(event)
    if spec is None:
        return
    positions, op = spec
    fd_at = _DIR_FD_ARG.get(event)
    folder = _fd_folder(args[fd_at]) if fd_at is not None and len(args) > fd_at else None
    for index in positions:
        if index < len(args):
            _check_write(op, args[index], folder)


def _system_read_roots() -> list[Path]:
    """Interpreter, stdlib, site-packages, temp, cache, and system data dirs."""
    found: list[Path] = []

    def add(raw: Any) -> None:
        text = str(raw or "").strip()
        if not text:
            return
        try:
            found.append(Path(os.path.abspath(text)))
        except OSError:
            return

    for raw in (
        sys.prefix,
        sys.exec_prefix,
        getattr(sys, "base_prefix", None),
        getattr(sys, "base_exec_prefix", None),
    ):
        add(raw)
    try:
        import sysconfig

        for key in ("stdlib", "platstdlib", "purelib", "platlib"):
            add(sysconfig.get_path(key))
    except Exception:
        # sysconfig is missing or broken; prefix and sys.path still cover us.
        pass
    for entry in sys.path:
        if entry:
            add(entry)
    add(tempfile.gettempdir())
    if _CACHE_ROOT is not None:
        add(_CACHE_ROOT)
    if sys.platform == "win32":
        for key in ("SystemRoot", "WINDIR"):
            add(os.environ.get(key))
    else:
        for raw in (
            "/usr/lib",
            "/usr/lib64",
            "/lib",
            "/lib64",
            "/usr/local/lib",
            "/usr/share",
            "/System",
            "/Library/Frameworks",
            "/etc",
            "/dev",
        ):
            add(raw)
    return found


def _install_write_guard(payload: dict[str, Any]) -> None:
    """Refuse outside writes and reads, process launch, network, ctypes, and imports.

    The hook cannot be removed. A later addaudithook call is refused. Imports
    that allowed libraries make for their own use still run; the same import
    from the cell does not. A read of a user file is refused when the cell
    is on the stack, so load_workbook of an outside path cannot return it.
    Library files, the work folder, workspace roots, and results stay readable.
    """
    roots: list[Path] = []
    work = str(payload.get("work") or "").strip()
    if work:
        try:
            roots.append(Path(os.path.abspath(work)))
        except OSError:
            pass
    if not roots:
        try:
            roots.append(Path(os.getcwd()))
        except OSError:
            pass
    if _CACHE_ROOT is not None:
        roots.append(_CACHE_ROOT)
    read_roots: list[Path] = list(roots)
    for entry in payload.get("roots") or []:
        if not isinstance(entry, dict):
            continue
        raw = str(entry.get("path") or "").strip()
        if not raw:
            continue
        try:
            base = Path(os.path.abspath(raw))
        except OSError:
            continue
        read_roots.append(base)
        if entry.get("write"):
            roots.append(base / "results")
            read_roots.append(base / "results")
    read_roots.extend(_system_read_roots())
    _WRITE_ROOTS.clear()
    _WRITE_ROOTS.extend(roots)
    _READ_ROOTS.clear()
    _READ_ROOTS.extend(read_roots)
    _install_cell_thread_tracking()
    sys.addaudithook(_write_audit)


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
        # No pyplot: there is no leftover figure to save.
        return
    try:
        numbers = list(plt.get_fignums())
    except Exception:
        # A broken matplotlib still must not fail the cell.
        return
    for index, number in enumerate(numbers, start=1):
        name = "figure.png" if index == 1 else f"figure-{index}.png"
        try:
            plt.figure(number).savefig(folder / name)
        except Exception:
            # One bad figure is skipped; the others still show.
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
        if _needs_matplotlib(code):
            _warm_matplotlib()
        _set_cwd(payload.get("work"))
        _install_write_guard(payload)
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
