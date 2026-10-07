"""Fail when a third-party GitHub Action is not pinned to a commit SHA."""

from __future__ import annotations

import re
import sys
from pathlib import Path

# One rule: local ./ actions are fine; everything else must be owner/repo(/path)@40 hex.
_PINNED = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w.-]+)*@[0-9a-fA-F]{40}$")
_USES = re.compile(r"^\s*-?\s*uses:\s*(.+)$")


def _ref(raw: str) -> str:
    value = raw.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    return value


def _ok(ref: str) -> bool:
    return ref.startswith("./") or bool(_PINNED.match(ref))


def _yaml_files(root: Path) -> list[Path]:
    files: list[Path] = []
    workflows = root / ".github" / "workflows"
    if workflows.is_dir():
        files.extend(sorted(workflows.glob("*.yml")))
    actions = root / ".github" / "actions"
    if actions.is_dir():
        files.extend(sorted(actions.rglob("*.yml")))
        files.extend(sorted(actions.rglob("*.yaml")))
    return files


def violations(root: Path) -> list[str]:
    found: list[str] = []
    for path in _yaml_files(root):
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = _USES.match(line)
            if not match:
                continue
            ref = _ref(match.group(1))
            if ref and not _ok(ref):
                found.append(f"{rel}:{lineno}")
    return found


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parent.parent
    bad = violations(root)
    for item in bad:
        print(item)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
