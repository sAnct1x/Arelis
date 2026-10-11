"""Environment and process helpers for a program the user asked to run.

The parent process keeps its own environment. A child gets the names a
script needs to start, and nothing that looks like a credential.

The data cell and the Python cell share the spawn, the Windows job, and
the wait. Each tool still builds its own environment and its own runner.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# A script can start, find its interpreter, and speak the user's language
# with these. Everything else stays in this process.
_ALLOW = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "TEMP",
    "TMP",
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "LANG",
    "LC_ALL",
    "VIRTUAL_ENV",
    "PYTHONUNBUFFERED",
    "PYTHONIOENCODING",
)

_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASS|AUTH|COOKIE|SESSION")


def _dropped(name: str) -> bool:
    key = name.upper()
    if key.startswith("ARELIS_"):
        return True
    return _SECRET_NAME.search(key) is not None


def child_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy the allowlist, then extra names that are not credentials.

    `extra` cannot smuggle `ARELIS_*` or a name like `GITHUB_TOKEN`. A
    control flag the child must see is set on the dict this returns.
    """
    env: dict[str, str] = {}
    for name in _ALLOW:
        if _dropped(name) or name not in os.environ:
            continue
        env[name] = os.environ[name]
    for name, value in (extra or {}).items():
        if _dropped(name):
            continue
        env[str(name)] = str(value)
    return env


# How often a wait rechecks a child. Short enough that a timeout is prompt,
# long enough that the parent is not busy-looping.
_POLL_S = 0.2
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
_DEFAULT_RUNNER = Path(__file__).with_name("data_cell_runner.py")


def _job_memory_bytes(override: int | None) -> int:
    """Bytes for the Windows job. The data cell's constant stays patchable.

    A caller that passes a number uses that number. Otherwise read
    ``DATA_CELL_MEMORY_BYTES`` at call time, so a test can lower the cap
    without this module copying the value at import.
    """
    if override is not None:
        return int(override)
    from arelis.tools.data_cell import DATA_CELL_MEMORY_BYTES

    return int(DATA_CELL_MEMORY_BYTES)


def _spawn(
    python: str,
    cwd: Path,
    env: dict[str, str],
    runner: Path | None = None,
    memory_bytes: int | None = None,
    extra_args: tuple[str, ...] | list[str] | None = None,
) -> tuple[subprocess.Popen[str] | None, int | None]:
    """Start ``python -I -B <runner>``. The default runner is the data cell.

    ``extra_args`` sits between ``-B`` and the script. The data cell passes
    none, so its command line stays ``-I -B``.
    """
    script = Path(runner) if runner is not None else _DEFAULT_RUNNER
    argv = [python, "-I", "-B", *[str(arg) for arg in (extra_args or ())], str(script)]
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "env": env,
        "stdin": subprocess.PIPE,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, **kwargs)
    except OSError:
        return None, None
    job = _assign_job(proc.pid, memory_bytes) if sys.platform == "win32" else None
    return proc, job


def _assign_job(pid: int, memory_bytes: int | None = None) -> int | None:
    if sys.platform != "win32" or pid <= 0:
        return None
    import ctypes
    from ctypes import wintypes

    job_object_limit_kill_on_job_close = 0x2000
    job_object_limit_process_memory = 0x100
    job_object_extended_limit_information = 9
    process_set_quota = 0x0100
    process_terminate = 0x0001

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):  # noqa: N801
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = (
        job_object_limit_kill_on_job_close | job_object_limit_process_memory
    )
    info.ProcessMemoryLimit = _job_memory_bytes(memory_bytes)
    if not kernel32.SetInformationJobObject(
        job,
        job_object_extended_limit_information,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        kernel32.CloseHandle(job)
        return None
    proc = kernel32.OpenProcess(process_set_quota | process_terminate, False, pid)
    if not proc:
        kernel32.CloseHandle(job)
        return None
    ok = kernel32.AssignProcessToJobObject(job, proc)
    kernel32.CloseHandle(proc)
    if not ok:
        kernel32.CloseHandle(job)
        return None
    return int(job)


def _close_job(handle: int | None) -> None:
    if not handle or sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.CloseHandle(handle)
    except Exception:
        # The handle was already closed with the job.
        return


def _wait(proc: subprocess.Popen[str], timeout_s: float) -> tuple[str, str, str]:
    # Imported here. run_script imports this module for child_env, so a
    # module-level import of _kill_tree would still be loading run_script.
    from arelis.tools.run_script import _kill_tree

    deadline = time.monotonic() + max(0.1, float(timeout_s))
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _kill_tree(proc)
            _drain(proc)
            return "timeout", "", ""
        try:
            stdout, stderr = proc.communicate(timeout=min(_POLL_S, remaining))
            return "ok", stdout or "", stderr or ""
        except subprocess.TimeoutExpired:
            continue


def _drain(proc: subprocess.Popen[str]) -> None:
    # Same as _wait: never flush a pipe the parent already closed.
    proc.stdin = None
    try:
        proc.communicate(timeout=2.0)
    except Exception:
        # The child is already dead, so there is nothing left to read.
        return
