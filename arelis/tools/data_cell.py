"""Run a short analysis of files in the current room, in a separate Python.

The child is a fresh interpreter in isolated mode (`-I`), so PYTHONPATH and
the user site are ignored. Nothing is exec'd in this process. Charts and
tables land only in the room's results folder. No room, or a room with no
folder, is refused. There is no fallback to outputs/.

The time limit is DATA_CELL_TIMEOUT_S (120). The model cannot change it.
On Windows the child sits in a job with kill-on-close and a 2 GB process
memory limit. Network blocking in the child is defense in depth, not a
guarantee: ctypes can still get out.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.data_cell_runner import (
    MEMORY_REFUSAL,
    READ_REFUSAL,
    TOO_BIG,
    WRITE_REFUSAL,
    escapes_tree,
    is_unsafe_path,
)
from arelis.tools.run_script import _kill_tree, resolve_interpreter

DATA_CELL_TIMEOUT_S = 120.0
DATA_CELL_MEMORY_BYTES = 2 * 1024 * 1024 * 1024
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_TOTAL_READ_BYTES = 64 * 1024 * 1024
MAX_PNG_BYTES = 8 * 1024 * 1024
MAX_WRITE_BYTES = 16 * 1024 * 1024
_MAX_SUMMARY = 12_000
_TOO_LONG = "That took too long, so I stopped it."
_POLL_S = 0.2
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
_RUNNER = Path(__file__).with_name("data_cell_runner.py")
_MEMORY_CODES = {
    0xC0000017,  # STATUS_NO_MEMORY
    0xC000009A,  # STATUS_INSUFFICIENT_RESOURCES
    0xC000012D,  # STATUS_COMMITMENT_LIMIT
    -1073741801,  # STATUS_NO_MEMORY as a signed exit
    -1073741670,
    -1073741515,
}


class DataCellTool:
    name = "data_cell"
    description = (
        "Room csv FITS. "
        "Reads tables (CSV, TSV, JSON, Excel) and FITS headers or images. "
        "Pass code plus the file names in this room. Charts and tables are "
        "saved in this room's results folder."
    )
    risk = "write"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Python that prints the answer. It can call read_table, "
                    "read_fits, save_png, and save_csv."
                ),
            },
        },
        "required": ["code"],
    }

    def __init__(self, workspace: Any, rooms: Any = None) -> None:
        self.workspace = workspace
        self.rooms = rooms

    async def run(self, **kwargs: Any) -> ToolResult:
        return await asyncio.to_thread(self._run, kwargs)

    def _room_dir(self) -> Path | None:
        room = None if self.rooms is None else getattr(self.rooms, "active", None)
        if room is None or self.workspace is None:
            return None
        root_name = str(getattr(room, "root", "") or "").strip()
        if not root_name:
            return None
        entry = self.workspace.root_named(root_name)
        if entry is None or not entry.path.is_dir():
            return None
        return Path(entry.path)

    def _run(self, kwargs: dict[str, Any]) -> ToolResult:
        room = self._room_dir()
        if room is None:
            return ToolResult(ok=False, output=READ_REFUSAL)
        code = str(kwargs.get("code") or "").strip()
        if not code:
            return ToolResult(ok=False, output="Tell me what to work out from the files.")
        names, error = _file_names(kwargs.get("files"))
        if error:
            return ToolResult(ok=False, output=error)
        names = _names_mentioned(room, code, names)
        mapped, error = _check_inputs(room, names)
        if error:
            return ToolResult(ok=False, output=error)
        results = room / "results"
        try:
            results.mkdir(parents=True, exist_ok=True)
        except OSError:
            return ToolResult(ok=False, output=WRITE_REFUSAL)
        before = {path.resolve() for path in results.rglob("*") if path.is_file()}
        python = resolve_interpreter(room, None)
        payload = json.dumps(
            {
                "room": str(room),
                "results": str(results),
                "files": {key: str(path) for key, path in mapped.items()},
                "code": code,
                "max_input": MAX_INPUT_BYTES,
                "max_total_read": MAX_TOTAL_READ_BYTES,
                "max_png": MAX_PNG_BYTES,
                "max_write": MAX_WRITE_BYTES,
            }
        )
        env = _child_env(python, results)
        proc, job = _spawn(python, room, env)
        if proc is None:
            return ToolResult(ok=False, output="I couldn't finish that.")
        child_pid = int(proc.pid or 0)
        reason = "ok"
        stdout = ""
        stderr = ""
        try:
            try:
                proc.stdin.write(payload)
                proc.stdin.close()
            except Exception:
                # The child already exited, so the pipe is gone.
                reason = "fail"
            # communicate() flushes stdin on its first call. The pipe is
            # already closed, and on POSIX that flush raises ValueError.
            # Dropping the handle makes the wait path the same everywhere.
            proc.stdin = None
            if reason == "ok":
                reason, stdout, stderr = _wait(proc, DATA_CELL_TIMEOUT_S)
        finally:
            if proc.poll() is None:
                _kill_tree(proc)
                _drain(proc)
            _close_job(job)
        if reason == "timeout":
            _drop_new_pngs(results, before)
            return ToolResult(ok=False, output=_TOO_LONG, data={"child_pid": child_pid})
        parsed = _parse_stdout(stdout)
        if _looks_like_memory(parsed, stderr, proc.returncode):
            _drop_new_pngs(results, before)
            return ToolResult(ok=False, output=MEMORY_REFUSAL, data={"child_pid": child_pid})
        if not parsed:
            _drop_new_pngs(results, before)
            return ToolResult(
                ok=False,
                output="I couldn't finish that.",
                data={"child_pid": child_pid},
            )
        summary = str(parsed.get("summary") or "").strip() or "I couldn't finish that."
        if len(summary) > _MAX_SUMMARY:
            summary = summary[:_MAX_SUMMARY].rstrip() + "\n(truncated)"
        if not parsed.get("ok"):
            _drop_new_pngs(results, before)
            return ToolResult(ok=False, output=summary, data={"child_pid": child_pid})
        charts = _charts(parsed.get("charts"), results)
        data: dict[str, Any] = {"child_pid": child_pid}
        if charts:
            first = charts[0]
            data.update(
                {
                    "path": first["name"],
                    "abs_path": first["abs_path"],
                    "format": "png",
                    "title": Path(first["name"]).stem,
                    "charts": charts,
                }
            )
        return ToolResult(ok=True, output=summary, data=data)


_CODE_FILE = re.compile(r"(?i)\b([\w.-]+\.(?:csv|tsv|tab|json|xlsx|xls|fits|fit))\b")


def _names_mentioned(room: Path, code: str, names: list[str]) -> list[str]:
    """Authorize a room file the code names even when files= was left off."""
    found = list(names)
    have = {item.lower() for item in found}
    for match in _CODE_FILE.finditer(code or ""):
        leaf = match.group(1)
        if leaf.lower() in have:
            continue
        candidate = room / leaf
        if escapes_tree(candidate, room):
            continue
        if candidate.is_file():
            found.append(leaf)
            have.add(leaf.lower())
    return found


def _file_names(raw: Any) -> tuple[list[str], str]:
    if raw is None:
        return [], ""
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return [], ""
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()], ""
        return [text], ""
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()], ""
    return [], READ_REFUSAL


def _check_inputs(room: Path, names: list[str]) -> tuple[dict[str, Path], str]:
    mapped: dict[str, Path] = {}
    total = 0
    for name in names:
        if is_unsafe_path(name):
            return {}, READ_REFUSAL
        candidate = Path(name)
        if not candidate.is_absolute():
            candidate = room / candidate
        if escapes_tree(candidate, room):
            return {}, READ_REFUSAL
        if not candidate.is_file():
            return {}, "I can't find that file in this room."
        try:
            size = candidate.stat().st_size
        except OSError:
            return {}, READ_REFUSAL
        if size > MAX_INPUT_BYTES or total + size > MAX_TOTAL_READ_BYTES:
            return {}, TOO_BIG
        total += size
        mapped[name] = candidate
        mapped.setdefault(candidate.name, candidate)
    return mapped, ""


def _child_env(python: str, results: Path) -> dict[str, str]:
    del results
    env = {
        "PATH": str(Path(python).resolve().parent),
        "MPLBACKEND": "Agg",
        "PYTHONNOUSERSITE": "1",
        "http_proxy": "http://127.0.0.1:9",
        "https_proxy": "http://127.0.0.1:9",
        "all_proxy": "http://127.0.0.1:9",
        "HTTP_PROXY": "http://127.0.0.1:9",
        "HTTPS_PROXY": "http://127.0.0.1:9",
        "ALL_PROXY": "http://127.0.0.1:9",
    }
    if sys.platform == "win32":
        for key in ("SYSTEMROOT", "TEMP"):
            value = os.environ.get(key, "")
            if value:
                env[key] = value
        if "TEMP" not in env and os.environ.get("TMP"):
            env["TEMP"] = os.environ["TMP"]
    return env


def _spawn(
    python: str, room: Path, env: dict[str, str]
) -> tuple[subprocess.Popen[str] | None, int | None]:
    kwargs: dict[str, Any] = {
        "cwd": str(room),
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
        proc = subprocess.Popen([python, "-I", "-B", str(_RUNNER)], **kwargs)
    except OSError:
        return None, None
    job = _assign_job(proc.pid) if sys.platform == "win32" else None
    return proc, job


def _assign_job(pid: int) -> int | None:
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
    info.ProcessMemoryLimit = int(DATA_CELL_MEMORY_BYTES)
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


def _parse_stdout(stdout: str) -> dict[str, Any] | None:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _looks_like_memory(parsed: dict[str, Any] | None, stderr: str, code: int | None) -> bool:
    if parsed and str(parsed.get("error") or "") == "memory":
        return True
    text = stderr or ""
    if "MemoryError" in text or "Memory allocation still failed" in text:
        return True
    if code is None:
        return False
    unsigned = code & 0xFFFFFFFF
    return code in _MEMORY_CODES or unsigned in _MEMORY_CODES


def _charts(raw: Any, results: Path) -> list[dict[str, str]]:
    charts: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return charts
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("abs_path") or "").strip()
        if not text or is_unsafe_path(text):
            continue
        path = Path(text)
        if escapes_tree(path, results) or not path.is_file():
            continue
        if path.suffix.lower() != ".png":
            continue
        charts.append({"name": path.name, "abs_path": str(path.resolve())})
    return charts


def _drop_new_pngs(results: Path, before: set[Path]) -> None:
    if not results.is_dir():
        return
    for path in results.rglob("*.png"):
        try:
            if path.is_file() and path.resolve() not in before:
                path.unlink()
        except OSError:
            continue
