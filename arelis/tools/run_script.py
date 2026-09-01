"""Run a project .py under workspace roots. Not a shell, not the python cell.

The numerics cell cannot open files. This tool starts a named script the way
the user would: argv, project cwd, captured output. Jobs do not get it.
"""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.safety import redact_secrets
from arelis.workspace import WorkspaceRoots

_DEFAULT_TIMEOUT_S = 120.0
_MAX_TIMEOUT_S = 600.0
_MAX_OUTPUT = 12_000
_POLL_S = 0.2
_NEST_ENV = "ARELIS_IN_RUN_SCRIPT"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


class RunScriptTool:
    name = "run_script"
    description = (
        "Run a .py file under a workspace root. Not a shell. Not diagnostics. "
        "Not schedule run_now. path is relative or name:relative/path. "
        "args is an argv list of strings. Prefer print or a CSV so the "
        "result can be read back."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Script path relative to a workspace root",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Argv strings after the script path",
            },
            "timeout_s": {
                "type": "number",
                "description": (
                    f"Seconds to wait (default {_DEFAULT_TIMEOUT_S:g}, "
                    f"max {_MAX_TIMEOUT_S:g})"
                ),
            },
        },
        "required": ["path"],
    }

    def __init__(
        self,
        roots: list[str] | WorkspaceRoots,
        *,
        python: str | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> None:
        if isinstance(roots, WorkspaceRoots):
            self.workspace = roots
        else:
            self.workspace = WorkspaceRoots.from_paths(list(roots))
        self.python = (python or "").strip() or None
        self.is_cancelled = is_cancelled

    async def run(self, **kwargs: Any) -> ToolResult:
        return await asyncio.to_thread(self._run_sync, kwargs)

    def _run_sync(self, kwargs: dict[str, Any]) -> ToolResult:
        if os.environ.get(_NEST_ENV) == "1":
            return ToolResult(
                ok=False,
                output="Already inside a run_script process. Refusing to nest.",
            )
        path_str = str(kwargs.get("path") or "").strip()
        if not path_str:
            return ToolResult(ok=False, output="Missing path. Pass a .py file under the workspace.")
        try:
            timeout_s = float(kwargs.get("timeout_s") or _DEFAULT_TIMEOUT_S)
        except (TypeError, ValueError):
            timeout_s = _DEFAULT_TIMEOUT_S
        timeout_s = max(1.0, min(timeout_s, _MAX_TIMEOUT_S))
        argv_extra = _argv_list(kwargs.get("args"))

        try:
            resolved = self.workspace.resolve(path_str, for_write=False)
        except Exception as exc:
            return ToolResult(ok=False, output=f"run_script path error: {exc}")

        if resolved.root_name == "external":
            return ToolResult(
                ok=False,
                output="Cannot run a file outside workspace roots.",
            )
        entry = self.workspace.root_named(resolved.root_name)
        if entry is not None and entry.read_only:
            return ToolResult(
                ok=False,
                output=(
                    f"Workspace root `{resolved.root_name}` is read-only; "
                    "cannot run a program there."
                ),
            )
        path = resolved.path
        if path.suffix.lower() != ".py":
            return ToolResult(
                ok=False,
                output="run_script only starts .py files. Not a shell.",
            )
        if not path.is_file():
            label = resolved.qualified(multi=len(self.workspace) > 1)
            return ToolResult(ok=False, output=f"Not a file: {label}")

        interpreter = resolve_interpreter(resolved.root, self.python)
        cwd = resolved.root
        cmd = [interpreter, str(path), *argv_extra]
        env = os.environ.copy()
        env[_NEST_ENV] = "1"
        env.setdefault("PYTHONUNBUFFERED", "1")
        env["PYTHONIOENCODING"] = "utf-8"

        started = time.monotonic()
        try:
            proc = _spawn(cmd, cwd=cwd, env=env)
        except FileNotFoundError:
            return ToolResult(
                ok=False,
                output=f"Could not start {interpreter}. Python is missing.",
            )
        except OSError as exc:
            return ToolResult(ok=False, output=f"Could not start the script: {exc}")

        try:
            code, stdout, stderr, stopped = _wait(
                proc,
                timeout_s=timeout_s,
                is_cancelled=self.is_cancelled,
            )
        except Exception as exc:
            _kill_tree(proc)
            return ToolResult(ok=False, output=f"run_script failed: {exc}")

        duration = time.monotonic() - started
        if stopped == "cancelled":
            return ToolResult(
                ok=False,
                output="The script was stopped.",
                data=_result_data(resolved, interpreter, cwd, -1, duration),
            )
        if stopped == "timeout":
            return ToolResult(
                ok=False,
                output=(
                    f"The script timed out after {int(timeout_s)}s. "
                    "I will not invent the result."
                ),
                data=_result_data(resolved, interpreter, cwd, -1, duration),
            )

        text = _format_output(stdout, stderr, code, interpreter, cwd, path)
        text = redact_secrets(text)
        if len(text) > _MAX_OUTPUT:
            text = text[:_MAX_OUTPUT] + "\n…(truncated)"
        return ToolResult(
            ok=code == 0,
            output=text,
            data=_result_data(resolved, interpreter, cwd, code, duration),
        )


def resolve_interpreter(root: Path, configured: str | None) -> str:
    """Configured path, then project .venv, then this process."""
    if configured:
        hint = Path(configured).expanduser()
        if hint.is_file():
            return str(hint.resolve())
    win = root / ".venv" / "Scripts" / "python.exe"
    if win.is_file():
        return str(win.resolve())
    posix = root / ".venv" / "bin" / "python"
    if posix.is_file():
        return str(posix.resolve())
    return sys.executable


def _argv_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    return [str(raw)]


def _spawn(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "env": env,
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
    return subprocess.Popen(cmd, **kwargs)


def _wait(
    proc: subprocess.Popen[str],
    *,
    timeout_s: float,
    is_cancelled: Callable[[], bool] | None,
) -> tuple[int, str, str, str]:
    """Return (exit, stdout, stderr, reason) where reason is ok/timeout/cancelled."""
    deadline = time.monotonic() + timeout_s
    while True:
        if is_cancelled is not None and is_cancelled():
            _kill_tree(proc)
            _drain(proc)
            return -1, "", "", "cancelled"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _kill_tree(proc)
            _drain(proc)
            return -1, "", "", "timeout"
        try:
            stdout, stderr = proc.communicate(timeout=min(_POLL_S, remaining))
            return int(proc.returncode or 0), stdout or "", stderr or "", "ok"
        except subprocess.TimeoutExpired:
            continue


def _drain(proc: subprocess.Popen[str]) -> None:
    try:
        proc.communicate(timeout=2.0)
    except Exception:
        pass


def _kill_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=_CREATE_NO_WINDOW,
        )
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _format_output(
    stdout: str,
    stderr: str,
    code: int,
    interpreter: str,
    cwd: Path,
    path: Path,
) -> str:
    parts = [
        f"exit: {code}",
        f"script: {path.name}",
        f"cwd: {cwd}",
        f"python: {interpreter}",
    ]
    out = (stdout or "").rstrip()
    err = (stderr or "").rstrip()
    if out:
        parts.extend(["", "stdout:", out])
    if err:
        parts.extend(["", "stderr:", err])
    if not out and not err:
        parts.append("")
        parts.append("(no output — print the result, or write a file I can read)")
    return "\n".join(parts)


def _result_data(
    resolved: Any,
    interpreter: str,
    cwd: Path,
    code: int,
    duration_s: float,
) -> dict[str, Any]:
    return {
        "path": resolved.qualified(multi=False),
        "abs_path": str(resolved.path),
        "root_name": resolved.root_name,
        "python": interpreter,
        "cwd": str(cwd),
        "exit": code,
        "duration_s": round(duration_s, 3),
    }
