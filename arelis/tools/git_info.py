"""Read-only git status / diff / log under workspace roots.

No shell tool: only a fixed allow-list of git subcommands. Never commit,
push, reset, or otherwise mutate the repo.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from arelis.tools.base import ToolResult
from arelis.workspace import WorkspaceRoots

# Match workspace list / analyze caps so a huge dirty tree cannot flood context.
_MAX_STATUS_LINES = 500
_MAX_OUTPUT_CHARS = 20_000
_MAX_LOG_N = 50
_DEFAULT_LOG_N = 10
_GIT_TIMEOUT_S = 15

_ALLOWED_ACTIONS = frozenset({"status", "diff", "log"})


class GitInfoTool:
    name = "git_info"
    description = (
        "Read-only git info for the active project (or a path under workspace). "
        "Actions: status, diff, log. Use instead of inventing branch or dirty "
        "state. Never commits, pushes, or resets."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "diff", "log"],
                "description": "Git read action (default status)",
            },
            "path": {
                "type": "string",
                "description": (
                    "Optional path under a workspace root to scope the call "
                    "(name:relative/path when multi-root). Defaults to the "
                    "active project root."
                ),
            },
            "n": {
                "type": "integer",
                "description": f"Log entry count (default {_DEFAULT_LOG_N}, max {_MAX_LOG_N})",
            },
            "max_chars": {
                "type": "integer",
                "description": f"Output truncation limit (default {_MAX_OUTPUT_CHARS})",
            },
        },
        "required": [],
    }

    def __init__(self, roots: list[str] | WorkspaceRoots) -> None:
        if isinstance(roots, WorkspaceRoots):
            self.workspace = roots
        else:
            self.workspace = WorkspaceRoots.from_paths(list(roots))
        self.roots = [r.path for r in self.workspace.roots]

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "status").strip().lower()
        if action not in _ALLOWED_ACTIONS:
            return ToolResult(
                ok=False,
                output=(
                    f"Unknown or forbidden action: {action}. "
                    "Allowed: status, diff, log (read-only)."
                ),
            )
        path_str = kwargs.get("path")
        try:
            max_chars = int(kwargs.get("max_chars") or _MAX_OUTPUT_CHARS)
        except (TypeError, ValueError):
            max_chars = _MAX_OUTPUT_CHARS
        max_chars = max(256, min(max_chars, _MAX_OUTPUT_CHARS))
        try:
            n = int(kwargs.get("n") or _DEFAULT_LOG_N)
        except (TypeError, ValueError):
            n = _DEFAULT_LOG_N
        n = max(1, min(n, _MAX_LOG_N))

        return await asyncio.to_thread(
            self._run_sync,
            action,
            None if path_str is None else str(path_str),
            n,
            max_chars,
        )

    def _run_sync(
        self,
        action: str,
        path_str: str | None,
        n: int,
        max_chars: int,
    ) -> ToolResult:
        if shutil.which("git") is None:
            return ToolResult(ok=False, output="git is not installed or not on PATH.")
        try:
            cwd = self._cwd_for(path_str)
        except Exception as exc:
            return ToolResult(ok=False, output=f"git_info path error: {exc}")

        toplevel = self._git_toplevel(cwd)
        if toplevel is None:
            return ToolResult(
                ok=False,
                output=(
                    f"Not a git repository (or any parent): {cwd}. "
                    "Workspace root must be inside a git repo."
                ),
            )
        # cwd is resolved via WorkspaceRoots; re-check so a race/symlink escape
        # cannot run git outside configured roots. Toplevel may sit above a
        # workspace subdirectory of a larger monorepo — that is allowed.
        if not self._within_workspace(cwd):
            return ToolResult(ok=False, output="Path escapes workspace roots.")

        if action == "status":
            return self._status(cwd, toplevel, max_chars)
        if action == "diff":
            return self._diff(cwd, toplevel, max_chars)
        return self._log(cwd, toplevel, n, max_chars)

    def _cwd_for(self, path_str: str | None) -> Path:
        if path_str is None or not str(path_str).strip():
            return self.workspace.active_root().path.resolve()
        resolved = self.workspace.resolve(str(path_str).strip())
        path = resolved.path
        if path.is_file():
            return path.parent.resolve()
        return path.resolve()

    def _within_workspace(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            return False
        for root in self.workspace.roots:
            try:
                resolved.relative_to(root.path.resolve())
                return True
            except ValueError:
                continue
        return False

    def _git_toplevel(self, cwd: Path) -> Path | None:
        completed = self._git(cwd, "rev-parse", "--show-toplevel")
        if completed.returncode != 0:
            return None
        text = (completed.stdout or "").strip()
        if not text:
            return None
        return Path(text).resolve()

    def _status(self, cwd: Path, toplevel: Path, max_chars: int) -> ToolResult:
        completed = self._git(cwd, "status", "--porcelain=v1", "-b")
        if completed.returncode != 0:
            return self._git_fail(completed, "status")
        lines = (completed.stdout or "").splitlines()
        shown = lines[:_MAX_STATUS_LINES]
        body = "\n".join(shown) if shown else "(clean)"
        if len(lines) > len(shown):
            body += f"\n[{len(lines) - len(shown)} more lines not shown]"
        return self._ok(body, action="status", cwd=cwd, toplevel=toplevel, max_chars=max_chars)

    def _diff(self, cwd: Path, toplevel: Path, max_chars: int) -> ToolResult:
        # Working tree + index vs HEAD so staged and unstaged both appear.
        completed = self._git(cwd, "diff", "HEAD")
        if completed.returncode != 0:
            return self._git_fail(completed, "diff")
        body = completed.stdout or ""
        if not body.strip():
            body = "(no diff vs HEAD)"
        return self._ok(body, action="diff", cwd=cwd, toplevel=toplevel, max_chars=max_chars)

    def _log(
        self, cwd: Path, toplevel: Path, n: int, max_chars: int
    ) -> ToolResult:
        completed = self._git(
            cwd,
            "log",
            f"-n{n}",
            "--decorate",
            "--oneline",
            "--no-color",
        )
        if completed.returncode != 0:
            return self._git_fail(completed, "log")
        body = (completed.stdout or "").rstrip() or "(no commits)"
        return self._ok(body, action="log", cwd=cwd, toplevel=toplevel, max_chars=max_chars)

    def _ok(
        self,
        body: str,
        *,
        action: str,
        cwd: Path,
        toplevel: Path,
        max_chars: int,
    ) -> ToolResult:
        header = f"repo: {toplevel}\ncwd: {cwd}\naction: {action}\n\n"
        text = header + body
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n\n[truncated to {max_chars} chars]"
        return ToolResult(
            ok=True,
            output=text,
            data={
                "action": action,
                "repo": str(toplevel),
                "cwd": str(cwd),
            },
        )

    def _git_fail(self, completed: subprocess.CompletedProcess[str], label: str) -> ToolResult:
        detail = (completed.stderr or completed.stdout or "").strip()
        return ToolResult(
            ok=False,
            output=detail or f"git {label} failed (exit {completed.returncode})",
        )

    def _git(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        return subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_S,
            check=False,
            env=env,
        )
