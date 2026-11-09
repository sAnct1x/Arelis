"""Child entry for a run_script sandbox run. It must not import arelis.

The parent starts ``python -I -B -u sandbox_host.py`` in the sandbox folder
and sends one JSON object on stdin: the script path, its argv, the folders
it may write, and the outside paths the user allowed on a card.

An audit hook refuses three things before the script's first line runs:

- changing a file or folder outside the writable folders (open for write,
  delete, move, mkdir, chmod, sqlite), unless that exact path was allowed;
- a socket to anything but this machine, and name lookups for other hosts;
  binding to all interfaces (empty host, 0.0.0.0, ::) is refused too;
- starting another program.

On POSIX, ``_posixsubprocess.fork_exec`` raises no audit event, so the host
also replaces it before the script runs (multiprocessing spawn/forkserver).
On Windows, ``_winapi.CreateProcess`` is audited and the parent's job object
allows only one process.

This is Python-level. A C extension that writes or connects on its own,
ctypes, ``os.open``/``os.rename`` with an outside ``dir_fd``, and
``os.mkfifo`` do not raise the audit events we catch. On Windows the
parent's job object is the kernel-level part: one process, a memory cap, a
CPU cap, and a kill when the parent lets go. See docs/code-sandbox.md.
"""

from __future__ import annotations

import importlib.util
import json
import os
import runpy
import sys
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

BLOCK_PREFIX = "ARELIS_SANDBOX_BLOCKED "
STATUS_PREFIX = "ARELIS_RUN_STATUS "

_STATE: dict[str, Any] = {"roots": [], "grants": set()}
_IN_HOOK = False

# Event name to (argument positions that are paths, what the user sees).
# sqlite3.connect is handled in _audit_inner so file: URIs are parsed.
_PATH_EVENTS: dict[str, tuple[tuple[int, ...], str]] = {
    "os.remove": ((0,), "delete"),
    "os.rmdir": ((0,), "delete"),
    "shutil.rmtree": ((0,), "delete"),
    "os.rename": ((0, 1), "move"),
    "os.link": ((0, 1), "write"),
    "os.symlink": ((1,), "write"),
    "os.mkdir": ((0,), "write"),
    "os.chmod": ((0,), "write"),
    "os.chown": ((0,), "write"),
    "os.utime": ((0,), "write"),
    "os.truncate": ((0,), "write"),
}
# dir_fd position for the events that take one. POSIX only; Windows has none.
_DIR_FD_ARG = {"os.remove": 1, "os.rmdir": 1, "os.mkdir": 2, "os.rename": 2}
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
# Loopback names for connect/sendto/DNS ("" is an empty host). Bind treats
# "", 0.0.0.0 and :: as not local (listening on every interface).
_LOCAL_NAMES = frozenset({"", "localhost", "127.0.0.1", "::1", "0:0:0:0:0:0:0:1"})
_BIND_ALL = frozenset({"", "0.0.0.0", "::"})
_NULL_DEVICES = frozenset({os.path.normcase(os.devnull), "nul"})


class SandboxBlocked(BaseException):
    """BaseException, so ``except Exception`` in the script cannot swallow it."""


def _paths_module() -> Any:
    """The data cell's path checks, loaded by file so arelis is not imported."""
    here = Path(__file__).resolve().with_name("data_cell_runner.py")
    spec = importlib.util.spec_from_file_location("_arelis_sandbox_paths", here)
    if spec is None or spec.loader is None:
        raise ImportError("data_cell_runner.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_PATHS = _paths_module()


def _report(record: dict[str, Any]) -> None:
    # os.write is not audited and does not go through a sys.stderr the
    # script may have replaced.
    try:
        os.write(2, (BLOCK_PREFIX + json.dumps(record) + "\n").encode("utf-8"))
    except OSError:
        pass


def _key(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


def _fd_folder(fd: Any) -> str | None:
    """Folder behind a POSIX dir_fd. rmtree uses one for every entry."""
    if not isinstance(fd, int):
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


def _as_text(raw: Any) -> str | None:
    if isinstance(raw, int) or raw is None:
        return None
    if isinstance(raw, bytes):
        raw = os.fsdecode(raw)
    text = os.fspath(raw) if isinstance(raw, os.PathLike) else str(raw)
    return text or None


def _writable(text: str) -> bool:
    if os.path.normcase(text) in _NULL_DEVICES:
        return True
    path = Path(text)
    for root in _STATE["roots"]:
        if not _PATHS.escapes_tree(path, root):
            return True
    return _key(text) in _STATE["grants"]


def _check_write(op: str, raw: Any, folder: str | None = None) -> None:
    text = _as_text(raw)
    if text is None or text == ":memory:":
        return
    if folder is not None and not os.path.isabs(text):
        text = os.path.join(folder, text)
    if _writable(text):
        return
    target = os.path.realpath(os.path.join(os.getcwd(), text))
    _report({"kind": "write", "op": op, "path": target})
    raise SandboxBlocked(
        f"Blocked: {op} {target} is outside the sandbox. Nothing was changed there."
    )


def _sqlite_path_to_check(text: str) -> str | None:
    """Filesystem path to guard for sqlite3.connect, or None if allowed.

    Plain paths are checked. ``:memory:`` and ``file:`` URIs with mode=ro or
    mode=memory are allowed. Other ``file:`` URIs are stripped to a path and
    checked like any write.
    """
    if text == ":memory:":
        return None
    if not text.startswith("file:"):
        return text
    parsed = urlparse(text)
    mode = (parse_qs(parsed.query).get("mode") or [None])[0]
    if mode in ("ro", "memory"):
        return None
    # file://localhost/abs and file:///abs both land in path; file:rel keeps
    # a relative path. Unknown hosts are treated as a path to refuse.
    if parsed.netloc and parsed.netloc.lower() not in ("", "localhost"):
        return text
    path = unquote(parsed.path or "")
    return path or None


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
    port = address[1] if isinstance(address, tuple) and len(address) > 1 else None
    if bind:
        raw = host
        if isinstance(raw, bytes):
            raw = raw.decode("ascii", "replace")
        text = "" if raw is None else str(raw).strip().lower()
        if text in _BIND_ALL:
            _report({"kind": "network", "host": text or "0.0.0.0"})
            raise SandboxBlocked("Blocked: the sandbox has no network.")
    # Port 9 is the closed proxy the parent sets, so urllib and requests
    # land here. Report that as no network, not as a refused connection.
    if _local_host(host) and port != 9:
        return
    _report({"kind": "network", "host": str(host)})
    raise SandboxBlocked("Blocked: the sandbox has no network.")


def _audit(event: str, args: tuple[Any, ...]) -> None:
    global _IN_HOOK
    if _IN_HOOK:
        return
    _IN_HOOK = True
    try:
        _audit_inner(event, args)
    finally:
        _IN_HOOK = False


def _audit_inner(event: str, args: tuple[Any, ...]) -> None:
    if event == "open":
        if len(args) >= 3 and _PATHS._is_write(args[1], args[2]):
            _check_write("write", args[0])
        return
    if event == "sqlite3.connect":
        text = _as_text(args[0]) if args else None
        if text is None:
            return
        target = _sqlite_path_to_check(text)
        if target is not None:
            _check_write("write", target)
        return
    spec = _PATH_EVENTS.get(event)
    if spec is not None:
        positions, op = spec
        fd_at = _DIR_FD_ARG.get(event)
        folder = _fd_folder(args[fd_at]) if fd_at is not None and len(args) > fd_at else None
        for index in positions:
            if index < len(args):
                _check_write(op, args[index], folder)
        return
    if event in _NET_ADDRESS_EVENTS and len(args) >= 2:
        _check_address(args[1], bind=(event == "socket.bind"))
        return
    if event in _NET_NAME_EVENTS and args:
        if not _local_host(args[0]):
            _report({"kind": "network", "host": str(args[0])})
            raise SandboxBlocked("Blocked: the sandbox has no network.")
        return
    if event in _PROCESS_EVENTS:
        _report({"kind": "process"})
        raise SandboxBlocked("Blocked: the sandbox cannot start other programs.")


def _block_fork_exec(*_args: Any, **_kwargs: Any) -> Any:
    """Stand-in for ``_posixsubprocess.fork_exec`` (no audit event on spawn)."""
    _report({"kind": "process"})
    raise SandboxBlocked("Blocked: the sandbox cannot start other programs.")


def _patch_posix_process_start() -> None:
    """Block multiprocessing spawn/forkserver. Windows uses CreateProcess + job."""
    if sys.platform == "win32":
        return
    try:
        import _posixsubprocess
    except ImportError:
        return
    _posixsubprocess.fork_exec = _block_fork_exec  # type: ignore[assignment]


def _posix_cpu_cap(seconds: int) -> None:
    if sys.platform == "win32" or seconds <= 0:
        return
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
    except (ImportError, OSError, ValueError):
        return


def _emit_status(exc: BaseException) -> None:
    payload = {"status": "bad_args", "error_type": type(exc).__name__}
    try:
        os.write(2, (STATUS_PREFIX + json.dumps(payload) + "\n").encode("utf-8"))
    except OSError:
        pass


def _script_traceback(exc: BaseException) -> None:
    """The script's frames. The host and runpy frames are not the error."""
    tb = exc.__traceback__
    while tb is not None:
        name = tb.tb_frame.f_code.co_filename
        if name != __file__ and not name.startswith("<frozen") and "runpy" not in name:
            break
        tb = tb.tb_next
    traceback.print_exception(type(exc), exc, tb)


def main() -> None:
    config = json.loads(sys.stdin.read() or "{}")
    script = str(config["script"])
    _PATHS._enable_venv_site()
    _STATE["roots"] = [Path(item) for item in config.get("roots") or []]
    _STATE["grants"] = {_key(str(item)) for item in config.get("grants") or []}
    _posix_cpu_cap(int(config.get("cpu_s") or 0))
    sys.argv = [script, *[str(item) for item in config.get("argv") or []]]
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    sys.addaudithook(_audit)
    _patch_posix_process_start()
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as exc:
        if exc.code in (None, 0):
            raise
        _emit_status(exc)
        raise SystemExit(exc.code if isinstance(exc.code, int) else 1) from None
    except SandboxBlocked as exc:
        sys.stderr.write(f"{exc}\n")
        _emit_status(exc)
        raise SystemExit(1) from None
    except BaseException as exc:
        _script_traceback(exc)
        _emit_status(exc)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
