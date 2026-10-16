"""Environment and process helpers for a program the user asked to run.

The parent process keeps its own environment. A child gets the names a
script needs to start, and nothing that looks like a credential.

The data cell and the Python cell share the spawn, the Windows job, and
the wait. Each tool still builds its own environment and its own runner.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

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
# The primary thread does not run until ResumeThread. subprocess has no name for this.
_CREATE_SUSPENDED = 0x00000004
_DEFAULT_RUNNER = Path(__file__).with_name("data_cell_runner.py")
# User-mode CPU cap for the job, in seconds. Same number the data cell runner
# passes to RLIMIT_CPU. Written into the job as 100-nanosecond ticks.
# The parent's wall-clock kill is unchanged.
_CPU_SECONDS = 130
# 1 keeps the cell as the only process in the job. None leaves the active
# process limit off so a test can prove a launch still creates a marker.
_ACTIVE_PROCESS_LIMIT: int | None = 1
_JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_TH32CS_SNAPTHREAD = 0x00000004
_THREAD_SUSPEND_RESUME = 0x0002


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

    On Windows the child is created suspended. ``_contain`` assigns the job
    and resumes the primary thread. If that fails the child is killed and
    this returns ``(None, None)``. Callers already treat that as a cell that
    did not start.
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
        kwargs["creationflags"] = (
            _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP | _CREATE_SUSPENDED
        )
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, **kwargs)
    except OSError:
        return None, None
    if sys.platform != "win32":
        return proc, None
    contained = False
    job: int | None = None
    try:
        job = _contain(proc, memory_bytes)
        contained = True
    except Exception as exc:
        log.warning("refusing to run the cell: %s", exc)
    finally:
        if not contained:
            _abandon(proc)
    if not contained or job is None:
        return None, None
    return proc, job


def _contain(proc: subprocess.Popen[str], memory_bytes: int | None) -> int:
    """Assign ``proc`` to a job, then resume its only thread.

    One ``SetInformationJobObject`` call (class 9) sets the active process
    limit, the per-process user-mode CPU limit, kill-on-close, and the
    memory cap. The process handle is the one Popen already holds.
    """
    import ctypes

    handle = getattr(proc, "_handle", None)
    pid = int(proc.pid or 0)
    if handle is None or _bad_handle(int(handle)) or pid <= 0:
        raise OSError("child process handle is missing")
    kernel32 = _kernel32()
    job = kernel32.CreateJobObjectW(None, None)
    err = ctypes.get_last_error()
    if _bad_handle(job):
        raise OSError(f"CreateJobObjectW failed (winerror {err})")
    try:
        _set_job_limits(kernel32, job, memory_bytes)
        if not kernel32.AssignProcessToJobObject(job, int(handle)):
            err = ctypes.get_last_error()
            raise OSError(f"AssignProcessToJobObject failed (winerror {err})")
        _resume_primary_thread(kernel32, pid)
    except Exception:
        kernel32.CloseHandle(job)
        raise
    return int(job)


def _set_job_limits(kernel32: Any, job: int, memory_bytes: int | None) -> None:
    import ctypes

    info = _extended_limit_info()
    flags = (
        _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | _JOB_OBJECT_LIMIT_PROCESS_TIME
    )
    active = _ACTIVE_PROCESS_LIMIT
    if active is not None:
        flags |= _JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        info.BasicLimitInformation.ActiveProcessLimit = int(active)
    info.BasicLimitInformation.LimitFlags = flags
    info.BasicLimitInformation.PerProcessUserTimeLimit = int(_CPU_SECONDS) * 10_000_000
    info.ProcessMemoryLimit = _job_memory_bytes(memory_bytes)
    if not kernel32.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        err = ctypes.get_last_error()
        raise OSError(f"SetInformationJobObject failed (winerror {err})")


def _extended_limit_info() -> Any:
    import ctypes
    from ctypes import wintypes

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

    return JOBOBJECT_EXTENDED_LIMIT_INFORMATION()


def _resume_primary_thread(kernel32: Any, pid: int) -> None:
    """Resume the one thread a suspended CreateProcess leaves behind."""
    # Toolhelp can miss the new thread for a moment. More than one is fatal.
    deadline = time.monotonic() + 0.2
    found: list[int] = []
    while True:
        found = _thread_ids(kernel32, pid)
        if len(found) == 1:
            break
        if len(found) > 1 or time.monotonic() >= deadline:
            raise OSError(f"expected one suspended thread for {pid}, found {len(found)}")
        time.sleep(0.01)
    _resume_thread(kernel32, found[0])


def _thread_ids(kernel32: Any, pid: int) -> list[int]:
    import ctypes
    from ctypes import wintypes

    class THREADENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
    kernel32.Thread32First.restype = wintypes.BOOL
    kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(THREADENTRY32)]
    kernel32.Thread32Next.restype = wintypes.BOOL
    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPTHREAD, 0)
    err = ctypes.get_last_error()
    if _bad_handle(snap):
        raise OSError(f"CreateToolhelp32Snapshot failed (winerror {err})")
    try:
        entry = THREADENTRY32()
        entry.dwSize = ctypes.sizeof(THREADENTRY32)
        if entry.dwSize != 28:
            raise OSError(f"THREADENTRY32 size is {entry.dwSize}, expected 28")
        found: list[int] = []
        if not kernel32.Thread32First(snap, ctypes.byref(entry)):
            err = ctypes.get_last_error()
            raise OSError(f"Thread32First failed (winerror {err})")
        while True:
            if int(entry.th32OwnerProcessID) == pid:
                found.append(int(entry.th32ThreadID))
            entry.dwSize = ctypes.sizeof(THREADENTRY32)
            if not kernel32.Thread32Next(snap, ctypes.byref(entry)):
                break
        return found
    finally:
        kernel32.CloseHandle(snap)


def _resume_thread(kernel32: Any, thread_id: int) -> None:
    import ctypes

    thread = kernel32.OpenThread(_THREAD_SUSPEND_RESUME, False, int(thread_id))
    err = ctypes.get_last_error()
    if _bad_handle(thread):
        raise OSError(f"OpenThread failed (winerror {err})")
    previous = -1
    try:
        previous = int(kernel32.ResumeThread(thread))
        if previous == 0xFFFFFFFF:
            raise OSError(f"ResumeThread failed (winerror {ctypes.get_last_error()})")
    finally:
        kernel32.CloseHandle(thread)
    if previous != 1:
        raise OSError(f"ResumeThread returned {previous}, expected 1")


def _kernel32() -> Any:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    return kernel32


def _bad_handle(value: int | None) -> bool:
    if not value:
        return True
    import ctypes

    invalid = ctypes.c_void_p(-1).value
    return invalid is not None and int(value) == int(invalid)


def _abandon(proc: subprocess.Popen[str]) -> None:
    """Kill a child that will not be returned to the caller."""
    if sys.platform == "win32":
        handle = getattr(proc, "_handle", None)
        if handle:
            try:
                import ctypes
                from ctypes import wintypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
                kernel32.TerminateProcess.restype = wintypes.BOOL
                kernel32.TerminateProcess(int(handle), 1)
            except Exception:
                # The handle is already dead. kill() and wait() still run.
                pass
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:
        # Already dead, or this platform cannot signal it. wait() still runs.
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        # The wait timed out. The pipes are closed either way.
        pass
    for stream in (proc.stdin, proc.stdout, proc.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except Exception:
            # The pipe is already closed.
            pass


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
