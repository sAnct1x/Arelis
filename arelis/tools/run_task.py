"""Run a program the project already named. Not a shell.

list is free. run pauses every time, including on voice, and does not
ride along with the rest of the ask. The argv is built here. There is
no command string for the model to compose.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.confirm_preview import run_task_confirm
from arelis.tools.project_tasks import load_tasks, resolve_argv, task_named, unsafe_arg
from arelis.tools.run_script import (
    _NEST_ENV,
    _format_output,
    _spawn,
    _wait,
    resolve_interpreter,
)
from arelis.tools.safety import redact_secrets
from arelis.workspace import WorkspaceRoots

_DEFAULT_TIMEOUT_S = 120.0
_MAX_TIMEOUT_S = 600.0
_MAX_OUTPUT = 12_000


class RunTaskTool:
    name = "run_task"
    description = (
        "Run a program the project already named. Not a shell. "
        "action=list shows the names (pytest when the project has tests, "
        "package.json scripts, and arelis-tasks.json). "
        "action=run needs name= one of those names. args is an argv list "
        "of strings, appended after the declared command. "
        "Do not pass a command string. Do not call cmd, PowerShell, or bash. "
        "A .py file they named is run_script, not this."
    )
    risk = "side_effect"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "run"],
                "description": "list the declared names, or run one of them",
            },
            "name": {
                "type": "string",
                "description": "Task name from list. Required for action=run",
            },
            "path": {
                "type": "string",
                "description": "Optional project path. Defaults to the active root",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Extra argv strings. Not a shell line",
            },
            "timeout_s": {
                "type": "number",
                "description": (
                    f"Seconds to wait (default {_DEFAULT_TIMEOUT_S:g}, "
                    f"max {_MAX_TIMEOUT_S:g})"
                ),
            },
        },
        "required": ["action"],
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

    def confirm_detail(self, args: dict[str, Any]) -> str:
        action = str(args.get("action") or "run").strip().lower()
        if action == "list":
            return "List declared project tasks"
        name = str(args.get("name") or "").strip() or "(name)"
        try:
            root = self._root(str(args.get("path") or ""))
        except Exception as exc:
            return f"Run {name}\n{exc}"
        task = task_named(root.path, name)
        if task is None:
            known = ", ".join(item.name for item in load_tasks(root.path)) or "(none)"
            return f"Run {name}\nUnknown task. Declared: {known}"
        extra = _extra(args.get("args"))
        interpreter = resolve_interpreter(root.path, self.python)
        argv, err = resolve_argv(
            task, extra, root=root.path, interpreter=interpreter
        )
        shown = argv if argv is not None else [*task.argv, *extra]
        text = run_task_confirm(
            name=task.name,
            cwd=str(root.path),
            argv=shown,
            detail=task.detail,
        )
        if err:
            return text + f"\n\nWill not start: {err}"
        return text

    async def run(self, **kwargs: Any) -> ToolResult:
        import asyncio

        return await asyncio.to_thread(self._run_sync, kwargs)

    def _run_sync(self, kwargs: dict[str, Any]) -> ToolResult:
        if os.environ.get(_NEST_ENV) == "1":
            return ToolResult(
                ok=False,
                output="Already inside a run. Refusing to nest.",
            )
        action = str(kwargs.get("action") or "").strip().lower()
        if action == "list":
            return self._list(str(kwargs.get("path") or ""))
        if action != "run":
            return ToolResult(ok=False, output="Unknown action. Use list or run.")
        name = str(kwargs.get("name") or "").strip()
        if not name:
            return ToolResult(ok=False, output="run needs a name from list.")
        try:
            timeout_s = float(kwargs.get("timeout_s") or _DEFAULT_TIMEOUT_S)
        except (TypeError, ValueError):
            timeout_s = _DEFAULT_TIMEOUT_S
        timeout_s = max(1.0, min(timeout_s, _MAX_TIMEOUT_S))
        extra = _extra(kwargs.get("args"))
        for arg in extra:
            reason = unsafe_arg(arg)
            if reason:
                return ToolResult(ok=False, output=f"Refusing args: {reason}.")

        try:
            root = self._root(str(kwargs.get("path") or ""))
        except Exception as exc:
            return ToolResult(ok=False, output=f"run_task path error: {exc}")
        if root.root_name == "external":
            return ToolResult(ok=False, output="Cannot run outside workspace roots.")
        entry = self.workspace.root_named(root.root_name)
        if entry is not None and entry.read_only:
            return ToolResult(
                ok=False,
                output=f"Workspace root `{root.root_name}` is read-only.",
            )
        task = task_named(root.path, name)
        if task is None:
            known = ", ".join(item.name for item in load_tasks(root.path)) or "(none)"
            hint = (
                " If you need to run a .py file, use run_script instead."
                if name and any(c in name for c in "./\\")
                else ""
            )
            return ToolResult(
                ok=False,
                output=f"Unknown task `{name}`. Declared: {known}.{hint}",
            )
        interpreter = resolve_interpreter(root.path, self.python)
        argv, err = resolve_argv(task, extra, root=root.path, interpreter=interpreter)
        if argv is None:
            return ToolResult(ok=False, output=err)

        env = os.environ.copy()
        env[_NEST_ENV] = "1"
        env.setdefault("PYTHONUNBUFFERED", "1")
        env["PYTHONIOENCODING"] = "utf-8"
        started = time.monotonic()
        try:
            proc = _spawn(argv, cwd=root.path, env=env)
        except FileNotFoundError:
            return ToolResult(ok=False, output=f"Could not start {argv[0]}.")
        except OSError as exc:
            return ToolResult(ok=False, output=f"Could not start the task: {exc}")
        try:
            code, stdout, stderr, stopped = _wait(
                proc, timeout_s=timeout_s, is_cancelled=self.is_cancelled
            )
        except Exception as exc:
            from arelis.tools.run_script import _kill_tree

            _kill_tree(proc)
            return ToolResult(ok=False, output=f"run_task failed: {exc}")
        duration = time.monotonic() - started
        data = {
            "action": "run",
            "name": task.name,
            "argv": argv,
            "cwd": str(root.path),
            "root_name": root.root_name,
            "exit": code,
            "duration_s": round(duration, 3),
        }
        if stopped == "cancelled":
            return ToolResult(ok=False, output="The task was stopped.", data=data)
        if stopped == "timeout":
            return ToolResult(
                ok=False,
                output=f"The task timed out after {int(timeout_s)}s.",
                data=data,
            )
        text = _format_output(
            stdout, stderr, code, argv[0], root.path, Path(task.name)
        )
        text = redact_secrets(text)
        if len(text) > _MAX_OUTPUT:
            text = text[:_MAX_OUTPUT] + "\n…(truncated)"
        return ToolResult(ok=code == 0, output=text, data=data)

    def _list(self, path_str: str) -> ToolResult:
        try:
            root = self._root(path_str)
        except Exception as exc:
            return ToolResult(ok=False, output=f"run_task path error: {exc}")
        tasks = load_tasks(root.path)
        if not tasks:
            return ToolResult(
                ok=True,
                output=(
                    "No declared tasks. Add tests/ for pytest, scripts in "
                    "package.json, or arelis-tasks.json."
                ),
                data={"action": "list", "tasks": []},
            )
        lines = [f"{task.name}  ({task.kind})  {task.detail}" for task in tasks]
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={
                "action": "list",
                "tasks": [task.name for task in tasks],
                "cwd": str(root.path),
            },
        )

    def _root(self, path_str: str):
        raw = (path_str or "").strip() or "."
        return self.workspace.resolve_read(raw)


def _extra(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw] if raw else []
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw]
    return [str(raw)]
