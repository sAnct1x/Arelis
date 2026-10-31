"""Flag files that drifted outside an allowed path list.

A pull request that was supposed to stay in scripts/ and docs/ still
touches runtime code if somebody's editor saved a stray file. This
script diffs ``base...HEAD`` with ``--name-status --no-renames`` so a
rename lists the old path and the new one. ``git diff --name-only``
follows the rename and only prints the destination, which lets
``arelis/core.py`` become ``scripts/core.py`` and slip through
``--allow 'scripts/*'``. Exit 1 if anything extra showed up, 2 on a
usage error or a base ref git cannot diff.

The allow list is globs: a file of them (one per line), or repeated
``--allow``. Blank lines and ``#`` comments in the file are ignored.
This is a check, not a rewrite. It does not touch the tree.
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path


def normalize(path: str) -> str:
    text = path.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def matches(path: str, pattern: str) -> bool:
    """True when ``path`` is covered by one allow glob.

    A trailing slash is a prefix. A glob uses fnmatch. A plain path
    matches itself and anything under that directory.
    """
    path = normalize(path)
    pattern = normalize(pattern)
    if not path or not pattern:
        return False
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if any(char in pattern for char in "*?["):
        return fnmatch.fnmatch(path, pattern)
    return path == pattern or path.startswith(pattern + "/")


def load_allow_globs(path: Path) -> list[str]:
    globs: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        globs.append(text)
    return globs


def extra_paths(changed: list[str], allowed: list[str]) -> list[str]:
    """Changed paths that no allow glob covers, in the order they arrived."""
    extras: list[str] = []
    for raw in changed:
        path = normalize(raw)
        if not path:
            continue
        if not any(matches(path, glob) for glob in allowed):
            extras.append(path)
    return extras


def paths_from_name_status(text: str) -> list[str]:
    """Collect every path a ``git diff --name-status`` line names.

    A rename or copy names the old path and the new one. ``--no-renames``
    turns that into a delete plus an add, which this also keeps. Either
    form has to flag a runtime file that moved into an allowed glob.
    """
    paths: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        if "\t" not in raw:
            continue
        status, rest = raw.split("\t", 1)
        code = status.strip()[:1]
        pieces = [normalize(part) for part in rest.split("\t")]
        pieces = [part for part in pieces if part]
        if code in {"R", "C"} and len(pieces) >= 2:
            picked = pieces[:2]
        else:
            picked = pieces
        for path in picked:
            if path not in seen:
                seen.add(path)
                paths.append(path)
    return paths


def changed_files(base: str, cwd: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", f"{base}...HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "git diff failed").strip()
        print(err, file=sys.stderr)
        raise SystemExit(2)
    return paths_from_name_status(result.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print files changed since a base ref that sit outside an allow list.",
    )
    parser.add_argument("base", help="Git ref to diff against (base...HEAD).")
    parser.add_argument(
        "--allow",
        action="append",
        default=[],
        help="Allowed path glob. Repeatable.",
    )
    parser.add_argument(
        "--allow-file",
        type=Path,
        help="File of globs, one per line. # comments and blanks are skipped.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (the git working tree). Defaults to the current folder.",
    )
    args = parser.parse_args(argv)

    allowed = list(args.allow)
    if args.allow_file is not None:
        allowed.extend(load_allow_globs(args.allow_file))
    if not allowed:
        print("pass --allow or --allow-file", file=sys.stderr)
        return 2

    root = args.root if args.root is not None else Path.cwd()
    extras = extra_paths(changed_files(args.base, root), allowed)
    for path in extras:
        print(path)
    return 1 if extras else 0


if __name__ == "__main__":
    raise SystemExit(main())
