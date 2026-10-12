"""Short scientific Python, in a child process.

The pocket calculator is one expression. This tool runs a short cell:
assignments, prints, math, sympy, numpy. It is not a general interpreter.
os, subprocess, sockets, and the user's files stay out.

The cell used to run in this process, on a thread. A tracer stopped a
Python loop, and a C call that held the GIL froze the whole app, because
the thread could not be killed. The cell now runs under ``python -I -B``
with a hard kill. The 10 second limit starts after numpy and sympy have
imported. On Windows that import is a new interpreter and can take longer
than it does here, so a hung import is killed on its own budget instead of
being counted against the cell, and instead of waiting forever.

The AST checks and the audit hook live in the child. Name rules still
refuse the obvious spellings. The hook refuses the operation: a process, a
socket, ctypes, a write, or a read outside the Python libraries.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.child_proc import _close_job, _spawn, child_env
from arelis.tools.run_script import _kill_tree

_MAX_CHARS = 8_000
_TIMEOUT_S = 10.0
# The child enforces the 10s tracer. This extra second lets that tracer
# report a clean timeout before the parent kills a Python loop.
_WORK_GRACE_S = 1.0
# A cold Windows interpreter spends this on numpy and sympy before the cell
# runs a line. The work limit stays 10s. This cap only stops a child that
# never finishes importing.
_IMPORT_BUDGET_S = 30.0
# Windows job cap. The data cell keeps its own 2 GB limit.
_MEMORY_BYTES = 1024 * 1024 * 1024
_TIMEOUT_OUTPUT = "The Python cell timed out (10s). I will not guess the result."
_MEMORY_OUTPUT = "That used too much memory, so I stopped it."
# Windows job kill codes. Same set the data cell treats as out of memory.
_MEMORY_CODES = {
    0xC0000017,
    0xC000009A,
    0xC000012D,
    -1073741801,
    -1073741670,
    -1073741515,
}
_RUNNER = Path(__file__).with_name("python_cell_runner.py")


class PythonTool:
    name = "python"
    description = (
        "Run a short Python cell for numerics, kinematics, linear algebra, or "
        "a multi-step derivation. math is preloaded (sin, cos, radians, sqrt, "
        "pi). sympy is `sp`, numpy is `np` when installed. Assignments and "
        "print() work; the last expression is shown. Do not import os, "
        "subprocess, or open files. sympify/lambdify/parse_expr are refused"
        "build expressions from sp.Symbol, not from strings. Timeout 10s. "
        "Use calculator for a single "
        "arithmetic expression; use cas for one symbolic integrate/diff/solve; "
        "use this when you need a script (projectile range, quadratic time of "
        "flight, systems of equations). matplotlib is not allowed, print "
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
        return await _run_in_child(code)


async def _run_in_child(code: str) -> ToolResult:
    """Run the cell off the event loop, and do not leave that thread behind."""
    loop = asyncio.get_running_loop()
    done = asyncio.Event()
    box: dict[str, ToolResult] = {}

    def _target() -> None:
        try:
            box["result"] = _run_in_child_sync(code)
        except Exception as exc:
            box["result"] = ToolResult(ok=False, output=f"Python failed: {exc}")
        finally:
            loop.call_soon_threadsafe(done.set)

    worker = threading.Thread(target=_target, name="arelis-python-cell", daemon=True)
    worker.start()
    await done.wait()
    worker.join(timeout=2)
    return box.get("result") or ToolResult(
        ok=False, output="Python failed: the cell stopped."
    )


def _run_in_child_sync(code: str) -> ToolResult:
    work = Path(tempfile.mkdtemp(prefix="arelis-py-"))
    env = child_env(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    proc: subprocess.Popen[str] | None = None
    job: int | None = None
    threads: list[threading.Thread] = []
    killed = False
    lines: list[str] = []
    errors: list[str] = []
    try:
        proc, job = _spawn(
            sys.executable,
            work,
            env,
            runner=_RUNNER,
            memory_bytes=_MEMORY_BYTES,
            extra_args=("-u",),
        )
        if proc is None or proc.stdin is None or proc.stdout is None or proc.stderr is None:
            return ToolResult(ok=False, output="Python failed: the cell could not start.")
        ready, lines, errors, threads = _attach_readers(proc)
        try:
            proc.stdin.write(json.dumps({"code": code}))
            proc.stdin.close()
        except Exception:
            # The child already exited, so the pipe is gone. The caller is told.
            killed = True
            _kill_tree(proc)
            return ToolResult(ok=False, output="Python failed: the cell could not start.")
        # communicate() would flush a closed stdin and raise. Drop the handle.
        proc.stdin = None
        if not ready.wait(_IMPORT_BUDGET_S):
            killed = True
            _kill_tree(proc)
            _finish_io(proc, threads)
            threads = []
            return _startup_failure(errors)
        deadline = time.monotonic() + _TIMEOUT_S + _WORK_GRACE_S
        while proc.poll() is None:
            if time.monotonic() >= deadline:
                killed = True
                _kill_tree(proc)
                break
            time.sleep(0.05)
        _finish_io(proc, threads)
        threads = []
        payload = _parse_result("".join(lines))
        if payload is not None:
            return _tool_result(code, payload)
        if _memory_death(proc):
            return ToolResult(ok=False, output=_MEMORY_OUTPUT)
        if killed:
            return ToolResult(ok=False, output=_TIMEOUT_OUTPUT)
        return _startup_failure(errors)
    finally:
        if proc is not None and proc.poll() is None:
            _kill_tree(proc)
        if proc is not None and threads:
            _finish_io(proc, threads)
        _close_job(job)
        shutil.rmtree(work, ignore_errors=True)


def _attach_readers(
    proc: subprocess.Popen[str],
) -> tuple[threading.Event, list[str], list[str], list[threading.Thread]]:
    """Read both pipes on their own threads so a full stderr cannot stall the child.

    ``_drain`` uses communicate(), which would fight these readers. The
    Python cell waits on the threads instead.
    """
    ready = threading.Event()
    lines: list[str] = []
    errors: list[str] = []

    def _read_out() -> None:
        try:
            if proc.stdout is None:
                return
            for line in proc.stdout:
                lines.append(line)
                if line.startswith("ARELIS_PY_READY"):
                    ready.set()
        finally:
            ready.set()

    def _read_err() -> None:
        try:
            if proc.stderr is None:
                return
            errors.append(proc.stderr.read())
        except Exception:
            # The pipe closed because the child died. Empty stderr is the report.
            errors.append("")

    threads = [
        threading.Thread(target=_read_out, name="arelis-python-cell-out", daemon=True),
        threading.Thread(target=_read_err, name="arelis-python-cell-err", daemon=True),
    ]
    for thread in threads:
        thread.start()
    return ready, lines, errors, threads


def _finish_io(proc: subprocess.Popen[str], threads: list[threading.Thread]) -> None:
    deadline = time.monotonic() + 2.0
    while proc.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    for stream in (proc.stdout, proc.stderr):
        if stream is None:
            continue
        try:
            stream.close()
        except Exception:
            # The reader thread may have closed this pipe already.
            pass
    for thread in threads:
        thread.join(timeout=2)


def _memory_death(proc: subprocess.Popen[str]) -> bool:
    code = proc.returncode
    if code is None:
        return False
    return code in _MEMORY_CODES or (code & 0xFFFFFFFF) in _MEMORY_CODES


def _parse_result(text: str) -> dict[str, Any] | None:
    for line in text.splitlines():
        if not line.startswith("ARELIS_PY_RESULT "):
            continue
        try:
            parsed = json.loads(line[len("ARELIS_PY_RESULT ") :])
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _tool_result(code: str, payload: dict[str, Any]) -> ToolResult:
    if payload.get("ok"):
        text = str(payload.get("output") or "")
        return ToolResult(ok=True, output=text, data={"code": code, "result": text})
    kind = str(payload.get("kind") or "")
    message = str(payload.get("message") or "")
    if kind == "timeout":
        return ToolResult(ok=False, output=_TIMEOUT_OUTPUT)
    if kind == "syntax":
        return ToolResult(ok=False, output=f"Python syntax error: {message}")
    if kind == "refused":
        return ToolResult(ok=False, output=f"Python refused: {message}")
    return ToolResult(ok=False, output=f"Python failed: {message or 'the cell stopped.'}")


def _startup_failure(errors: list[str]) -> ToolResult:
    text = "\n".join(part.strip() for part in errors if part and part.strip())
    line = ""
    for item in reversed(text.splitlines()):
        if item.strip():
            line = item.strip()
            break
    if line:
        return ToolResult(ok=False, output=f"Python failed: {line[:300]}")
    return ToolResult(ok=False, output="Python failed: the cell could not start.")
