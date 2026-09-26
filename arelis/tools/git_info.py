"""Git status / diff / log, plus stage and commit, under workspace roots.

No shell tool: only a fixed allow-list of git subcommands, each invoked as an
argv list so nothing in a commit message can become a second command.

Reads are free. The only two writes are stage and commit, and they are the
only two because they are additive and recoverable — the objects stay in the
repo, and a bad commit can be amended, reverted or reset by hand afterwards.
Push, reset, clean, checkout, rebase and anything that rewrites history are
refused: none of them can be walked back from inside a chat turn, and a
repository is the one thing in this app with no undo.
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

_READ_ACTIONS = frozenset({"status", "diff", "log", "branch", "stash", "blame", "show"})
# Stash mutations stay off the allow-list; list-only is the whole verb.
_STASH_WRITE_ACTIONS = frozenset({"stash_apply", "stash_pop", "stash_drop", "stash_push"})
# Additive and recoverable. Everything else about a repo is not, so the
# allow-list stays exactly this long.
_WRITE_ACTIONS = frozenset({"stage", "commit"})
_ALLOWED_ACTIONS = _READ_ACTIONS | _WRITE_ACTIONS

_MAX_MESSAGE_CHARS = 2_000


class GitInfoTool:
    name = "git_info"
    description = (
        "Git for the active project (or a path under workspace). "
        "Actions: status, diff, log, branch, stash (list only), blame, show, "
        "stage, commit. Use instead of inventing branch or dirty state. "
        "commit needs message and only commits what is staged; stage takes an "
        "optional path; blame needs path; show takes optional rev (default HEAD). "
        "Never pushes, resets, cleans, checks out, rewrites history, or mutates "
        "stash — say so rather than claiming you did."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "status",
                    "diff",
                    "log",
                    "branch",
                    "stash",
                    "blame",
                    "show",
                    "stage",
                    "commit",
                ],
                "description": (
                    "status, diff, log, branch, stash (list only), blame, show, "
                    "stage, or commit (default status). "
                    "push/reset/clean/checkout/stash apply|pop|drop are not available"
                ),
            },
            "message": {
                "type": "string",
                "description": "Commit message for action=commit. Required.",
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
            "rev": {
                "type": "string",
                "description": "Revision for action=show (default HEAD).",
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
        if action in _STASH_WRITE_ACTIONS:
            return ToolResult(
                ok=False,
                output=(
                    f"Unknown or forbidden action: {action}. "
                    "stash is list-only (git stash list). "
                    "apply, pop, drop and push are deliberately unavailable — "
                    "tell the user to run it themselves rather than claiming "
                    "you did."
                ),
            )
        if action not in _ALLOWED_ACTIONS:
            return ToolResult(
                ok=False,
                output=(
                    f"Unknown or forbidden action: {action}. "
                    "Allowed: status, diff, log, branch, stash, blame, show, "
                    "stage, commit. "
                    "Pushing, resetting, cleaning, checking out and rewriting "
                    "history are deliberately unavailable — tell the user to "
                    "run it themselves rather than claiming you did."
                ),
            )
        if action == "blame" and not str(kwargs.get("path") or "").strip():
            return ToolResult(
                ok=False,
                output="blame needs path — the file to annotate.",
            )
        message = str(kwargs.get("message") or "").strip()
        if action == "commit" and not message:
            return ToolResult(
                ok=False,
                output="commit needs a message describing what changed.",
            )
        if len(message) > _MAX_MESSAGE_CHARS:
            return ToolResult(
                ok=False,
                output=f"That commit message is over {_MAX_MESSAGE_CHARS} chars.",
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
        rev = str(kwargs.get("rev") or "HEAD").strip() or "HEAD"

        return await asyncio.to_thread(
            self._run_sync,
            action,
            None if path_str is None else str(path_str),
            n,
            max_chars,
            message,
            rev,
        )

    def _run_sync(
        self,
        action: str,
        path_str: str | None,
        n: int,
        max_chars: int,
        message: str = "",
        rev: str = "HEAD",
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
        if action == "stage":
            return self._stage(cwd, toplevel, path_str, max_chars)
        if action == "commit":
            return self._commit(cwd, toplevel, message, max_chars)
        if action == "log":
            return self._log(cwd, toplevel, n, max_chars)
        if action == "branch":
            return self._branch(cwd, toplevel, max_chars)
        if action == "stash":
            return self._stash(cwd, toplevel, max_chars)
        if action == "blame":
            return self._blame(cwd, toplevel, path_str, max_chars)
        return self._show(cwd, toplevel, rev, max_chars)

    def _stage(self, cwd: Path, toplevel: Path, path_str: str | None, max_chars: int) -> ToolResult:
        """git add. Scoped to a named path, or everything under cwd.

        Deliberately not `git add -A` from the toplevel: cwd is already
        contained by the workspace check above, so staging relative to it
        cannot sweep in a sibling directory the user never mentioned.
        """
        target = "."
        if path_str and str(path_str).strip():
            resolved = self.workspace.resolve(str(path_str).strip())
            target = str(resolved.path)
        completed = self._git(cwd, "add", "--", target)
        if completed.returncode != 0:
            return self._git_fail(completed, "add")
        after = self._git(cwd, "status", "--porcelain=v1")
        staged = [
            line for line in (after.stdout or "").splitlines() if line[:1] not in {" ", "?", ""}
        ]
        body = "\n".join(staged) if staged else "(nothing staged)"
        return self._ok(body, action="stage", cwd=cwd, toplevel=toplevel, max_chars=max_chars)

    def _commit(self, cwd: Path, toplevel: Path, message: str, max_chars: int) -> ToolResult:
        """git commit of whatever is already staged.

        The message is passed as its own argv entry, so quotes, semicolons and
        newlines in it are a commit subject and never a second command. No
        --all: committing files the user did not stage is how an unrelated
        work-in-progress ends up in someone's history.
        """
        completed = self._git(cwd, "commit", "-m", message)
        if completed.returncode != 0:
            detail = (completed.stdout or completed.stderr or "").strip()
            if "nothing to commit" in detail.lower():
                return ToolResult(
                    ok=False,
                    output=(
                        "Nothing is staged, so there is nothing to commit. "
                        "Stage something first with action=stage."
                    ),
                )
            return self._git_fail(completed, "commit")
        return self._ok(
            (completed.stdout or "").strip() or "committed",
            action="commit",
            cwd=cwd,
            toplevel=toplevel,
            max_chars=max_chars,
        )

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

    def _branch(self, cwd: Path, toplevel: Path, max_chars: int) -> ToolResult:
        completed = self._git(cwd, "branch", "--no-color")
        if completed.returncode != 0:
            return self._git_fail(completed, "branch")
        body = (completed.stdout or "").rstrip() or "(no branches)"
        return self._ok(body, action="branch", cwd=cwd, toplevel=toplevel, max_chars=max_chars)

    def _stash(self, cwd: Path, toplevel: Path, max_chars: int) -> ToolResult:
        completed = self._git(cwd, "stash", "list")
        if completed.returncode != 0:
            return self._git_fail(completed, "stash list")
        body = (completed.stdout or "").rstrip() or "(no stashes)"
        return self._ok(body, action="stash", cwd=cwd, toplevel=toplevel, max_chars=max_chars)

    def _blame(self, cwd: Path, toplevel: Path, path_str: str | None, max_chars: int) -> ToolResult:
        assert path_str and str(path_str).strip()
        try:
            resolved = self.workspace.resolve(str(path_str).strip())
        except Exception as exc:
            return ToolResult(ok=False, output=f"git_info path error: {exc}")
        target = resolved.path
        if not target.is_file():
            return ToolResult(
                ok=False,
                output=f"blame needs a file path; not found: {path_str}",
            )
        if not self._within_workspace(target):
            return ToolResult(ok=False, output="Path escapes workspace roots.")
        completed = self._git(cwd, "blame", "--", str(target.resolve()))
        if completed.returncode != 0:
            return self._git_fail(completed, "blame")
        body = (completed.stdout or "").rstrip() or "(empty blame)"
        return self._ok(body, action="blame", cwd=cwd, toplevel=toplevel, max_chars=max_chars)

    def _show(self, cwd: Path, toplevel: Path, rev: str, max_chars: int) -> ToolResult:
        completed = self._git(cwd, "show", "--no-color", rev)
        if completed.returncode != 0:
            return self._git_fail(completed, "show")
        body = (completed.stdout or "").rstrip() or "(empty show)"
        return self._ok(body, action="show", cwd=cwd, toplevel=toplevel, max_chars=max_chars)

    def _log(self, cwd: Path, toplevel: Path, n: int, max_chars: int) -> ToolResult:
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
