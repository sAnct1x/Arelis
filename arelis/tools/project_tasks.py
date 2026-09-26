"""Named programs a project already declared. No command string.

The model picks a name. This module turns that name into an argv list.
npm scripts still run through npm, which shells the body the project
already stored — the card shows that body. arelis-tasks.json is an argv
array, started with shell off.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from arelis.workspace import _WINDOWS_DRIVE

_NAME = re.compile(r"^[A-Za-z0-9:_-]{1,64}$")
# Bare executables we will resolve on PATH. Anything else has to be a
# project .py, rewritten onto the interpreter.
_BARE = frozenset(
    {
        "python",
        "py",
        "pytest",
        "ruff",
        "node",
        "npm",
        "npx",
        "cargo",
        "go",
        "dotnet",
    }
)
_PY = frozenset({"python", "py"})


@dataclass(frozen=True)
class ProjectTask:
    name: str
    kind: str
    argv: list[str]
    detail: str


def load_tasks(root: Path) -> list[ProjectTask]:
    """Declared tasks for one project root. Later sources replace the same name."""
    by_name: dict[str, ProjectTask] = {}
    auto = _pytest_task(root)
    if auto is not None:
        by_name[auto.name] = auto
    for task in _npm_tasks(root):
        by_name[task.name] = task
    for task in _file_tasks(root):
        by_name[task.name] = task
    return [by_name[name] for name in sorted(by_name)]


def task_named(root: Path, name: str) -> ProjectTask | None:
    key = (name or "").strip()
    for task in load_tasks(root):
        if task.name == key:
            return task
    return None


def unsafe_arg(arg: str) -> str | None:
    """Why this argv element cannot be passed through, or None when it is fine."""
    if "\n" in arg or "\r" in arg or "\x00" in arg:
        return "an argument contains a newline"
    if _WINDOWS_DRIVE.match(arg) or arg.startswith("\\\\") or arg.startswith("/"):
        return "an argument is an absolute path"
    parts = re.split(r"[\\/]", arg)
    if ".." in parts:
        return "an argument climbs out of the project"
    return None


def resolve_argv(
    task: ProjectTask,
    extra: list[str],
    *,
    root: Path,
    interpreter: str,
) -> tuple[list[str] | None, str]:
    """(argv, error). Rewrites python and a project .py. Does not spawn."""
    for arg in extra:
        reason = unsafe_arg(arg)
        if reason:
            return None, reason
    built: list[str] = []
    for index, raw in enumerate(task.argv):
        reason = unsafe_arg(raw)
        if reason:
            return None, f"{task.name}: {reason}"
        if index == 0 and raw in _PY:
            built.append(interpreter)
            continue
        if index == 0 and raw.endswith(".py"):
            script = (root / raw).resolve()
            try:
                script.relative_to(root.resolve())
            except ValueError:
                return None, f"{task.name}: script leaves the project"
            if not script.is_file():
                return None, f"{task.name}: missing {raw}"
            built.append(interpreter)
            built.append(str(script))
            continue
        if index == 0 and raw in _BARE:
            found = shutil.which(raw)
            if not found:
                return None, f"{raw} is not on PATH"
            built.append(found)
            continue
        if index == 0:
            return None, (
                f"{task.name}: refusing to start `{raw}`. "
                "Use python, a project .py, or a bare tool name from the allow-list."
            )
        built.append(raw)
    if task.kind == "npm" and extra:
        built.append("--")
    built.extend(extra)
    return built, ""


def _pytest_task(root: Path) -> ProjectTask | None:
    looks = (root / "tests").is_dir() or (root / "pytest.ini").is_file()
    if not looks:
        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            try:
                text = pyproject.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            looks = "[tool.pytest" in text
    if not looks:
        return None
    return ProjectTask(
        name="pytest",
        kind="pytest",
        argv=["python", "-m", "pytest"],
        detail="python -m pytest",
    )


def _npm_tasks(root: Path) -> list[ProjectTask]:
    path = root / "package.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return []
    tasks: list[ProjectTask] = []
    for key, body in scripts.items():
        name = str(key).strip()
        if not _NAME.match(name) or not isinstance(body, str):
            continue
        tasks.append(
            ProjectTask(
                name=name,
                kind="npm",
                argv=["npm", "run", name],
                detail=body.strip(),
            )
        )
    return tasks


def _file_tasks(root: Path) -> list[ProjectTask]:
    path = root / "arelis-tasks.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    table = data.get("tasks") if isinstance(data, dict) and "tasks" in data else data
    if not isinstance(table, dict):
        return []
    tasks: list[ProjectTask] = []
    for key, argv in table.items():
        name = str(key).strip()
        if not _NAME.match(name) or not isinstance(argv, list) or not argv:
            continue
        words = [str(item) for item in argv]
        if any(unsafe_arg(word) for word in words):
            continue
        head = words[0]
        if head not in _BARE and not head.endswith(".py"):
            continue
        tasks.append(
            ProjectTask(
                name=name,
                kind="file",
                argv=words,
                detail=json.dumps(words, ensure_ascii=False),
            )
        )
    return tasks
