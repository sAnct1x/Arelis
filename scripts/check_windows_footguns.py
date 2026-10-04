"""Fail if arelis/ uses os.kill(..., 0).

On Windows that call is not a no-op liveness check. Signal 0 is not
supported there and the target can die. The lock path already has a
Windows-safe query; this scan exists so nobody puts the probe back.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Tiny and explicit. One pattern, one meaning.
PATTERNS: tuple[re.Pattern[str], ...] = (re.compile(r"os\.kill\s*\(\s*[^,\n]+\s*,\s*0\s*\)"),)


def default_root() -> Path:
    return Path(__file__).resolve().parent.parent / "arelis"


def iter_hits(root: Path) -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    if not root.is_dir():
        return hits
    for path in sorted(root.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            hits.append((path, 0, f"<unreadable: {exc}>"))
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for pattern in PATTERNS:
                if pattern.search(line):
                    hits.append((path, lineno, line.strip()))
                    break
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=None,
        help="Directory to scan (default: the arelis/ package next to scripts/)",
    )
    args = parser.parse_args(argv)
    root = args.root if args.root is not None else default_root()
    hits = iter_hits(root)
    if not hits:
        return 0
    for path, lineno, line in hits:
        print(f"{path}:{lineno}: {line}", file=sys.stderr)
    print(
        f"os.kill(..., 0) is a Windows footgun; {len(hits)} hit(s) in {root}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
