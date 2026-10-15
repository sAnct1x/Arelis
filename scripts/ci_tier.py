"""Pick which tests a pull request has to run.

Push is not tiered. ``decide`` returns the full suite for every push,
including a branch that is not main, even if the diff is only docs.

Pull requests:

* docs: ``*.md``, ``docs/``, and non-packaged repo files (LICENSE, the
  repo-root assets tree, images that do not ship in the package).
* area: every other path sits in one mapped area. Pytest runs the tests
  that statically import that area, including any serial tests.
* full: routing, prompts, tool schemas, shared core, safety gates (SMS,
  send, confirm, email), packaged fonts and assets, workflows, locks,
  test fixtures, several areas, an empty file list, or anything that is
  not confidently mapped.

The workflow calls this from inside the existing jobs. It does not skip
those jobs, so the required check names still report a conclusion.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Checked before docs. A prompt file is markdown, and it is not a docs change.
_FULL: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "ci",
        (
            ".github/",
            "tests/conftest.py",
            "scripts/ci_tier.py",
            "scripts/ci_pytest.py",
            "tests/test_ci_gate.py",
            "tests/test_ci_tier.py",
        ),
    ),
    (
        "deps",
        (
            "pyproject.toml",
            "win-installer/lock.py",
            "mac-installer/lock.py",
            "win-installer/requirements-*.txt",
            "mac-installer/requirements-*.txt",
        ),
    ),
    (
        "core",
        (
            "arelis/core/",
            "arelis/guard/",
            "arelis/__init__.py",
            "arelis/__main__.py",
            "arelis/main.py",
            "arelis/paths.py",
            "arelis/config.py",
            "arelis/cli.py",
        ),
    ),
    ("routing", ("arelis/llm/", "arelis/eval/")),
    ("prompts", ("arelis/persona/",)),
    ("tools", ("arelis/tools/",)),
    ("packaged", ("arelis/assets/", "arelis/ui/fonts/")),
)

# name, source prefixes, import-module prefixes.
# The test list is every tests/test_*.py that imports one of those modules.
# Calendar booking imports the agenda tool. World physics imports
# spatial.scene and spatial.depth. Those modules are the area.
_AREAS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("browser", ("arelis/browser/",), ("arelis.browser",)),
    ("calendar", ("arelis/calendar/",), ("arelis.calendar", "arelis.tools.agenda")),
    ("earth", ("arelis/earth/",), ("arelis.earth",)),
    ("memory", ("arelis/memory/",), ("arelis.memory",)),
    (
        "physics",
        ("arelis/physics/",),
        ("arelis.physics", "arelis.spatial.scene", "arelis.spatial.depth"),
    ),
    ("voice", ("arelis/voice/",), ("arelis.voice",)),
)

AREA_IMPORTS: tuple[tuple[str, tuple[str, ...]], ...] = tuple(
    (name, imports) for name, _sources, imports in _AREAS
)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp"}
_TEXT_NAMES = {"LICENSE", "COPYING"}
_SAFETY_TOKENS = ("sms", "send", "confirm", "email", "mail")


@dataclass(frozen=True)
class Tier:
    kind: str
    reason: str
    area: str = ""
    tests: tuple[str, ...] = ()

    @property
    def skip_pytest(self) -> bool:
        return self.kind == "docs"


def _norm(path: str) -> str:
    text = path.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text


def _matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatch(path, pattern)
    return path == pattern


def _is_safety(path: str) -> bool:
    """SMS, send, confirm, and email gates. A miss here runs the full suite."""
    if not path.startswith("arelis/") or not path.endswith(".py"):
        return False
    name = path.rsplit("/", 1)[-1].lower()
    return any(token in name for token in _SAFETY_TOKENS)


def _is_test_infra(path: str) -> bool:
    parts = path.split("/")
    if not parts or parts[0] != "tests":
        return False
    return parts[-1] == "conftest.py" or "fixtures" in parts


def _full_reason(path: str) -> str | None:
    if _is_safety(path):
        return "safety"
    if _is_test_infra(path):
        return "ci"
    for reason, patterns in _FULL:
        if any(_matches(path, pattern) for pattern in patterns):
            return reason
    return None


def _imported_modules(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _imports_any(modules: set[str], roots: tuple[str, ...]) -> bool:
    return any(mod == root or mod.startswith(root + ".") for root in roots for mod in modules)


@lru_cache(maxsize=8)
def _area_tests(root_text: str) -> dict[str, tuple[str, ...]]:
    root = Path(root_text)
    tests_dir = root / "tests"
    files = sorted(tests_dir.glob("test_*.py")) if tests_dir.is_dir() else []
    parsed = [(path, _imported_modules(path)) for path in files]
    listed: dict[str, tuple[str, ...]] = {}
    for name, _sources, imports in _AREAS:
        hits = [
            path.relative_to(root).as_posix()
            for path, modules in parsed
            if _imports_any(modules, imports)
        ]
        listed[name] = tuple(hits)
    return listed


def area_tests(area: str, root: Path | None = None) -> tuple[str, ...]:
    """Test files whose static imports reach ``area``. Serial tests stay in."""
    return _area_tests(str((root or REPO).resolve())).get(area, ())


def _areas_for(path: str, listed: dict[str, tuple[str, ...]]) -> list[str]:
    sources = [
        name
        for name, prefixes, _imports in _AREAS
        if any(_matches(path, prefix) for prefix in prefixes)
    ]
    if sources:
        return sources
    return [name for name, tests in listed.items() if path in tests]


def _is_doc(path: str) -> bool:
    """Markdown, docs/, and files that do not ship in the package.

    Anything under ``arelis/`` ships or is source. It is never a docs change.
    """
    if path.startswith(("arelis/", "tests/")):
        return False
    name = path.rsplit("/", 1)[-1]
    if name in _TEXT_NAMES:
        return True
    lower = path.lower()
    if lower.endswith((".md", ".markdown", ".rst")):
        return True
    if lower == "docs" or lower.startswith("docs/"):
        return True
    if lower.startswith("assets/"):
        return True
    return Path(lower).suffix in _IMAGE_SUFFIXES


def decide(
    paths: list[str],
    *,
    event: str = "pull_request",
    ref: str = "",
    root: Path | None = None,
) -> Tier:
    """Classify ``paths``. Non-pull_request events are always the full suite."""
    if event != "pull_request":
        reason = "main" if ref == "refs/heads/main" else "push"
        return Tier("full", reason)
    return _from_paths(paths, root or REPO)


def _from_paths(paths: list[str], root: Path) -> Tier:
    cleaned = [_norm(path) for path in paths if _norm(path)]
    if not cleaned:
        return Tier("full", "unknown")

    listed = _area_tests(str(root.resolve()))
    full_reasons: list[str] = []
    areas: list[str] = []
    saw_doc = False
    for path in cleaned:
        reason = _full_reason(path)
        if reason is not None:
            full_reasons.append(reason)
            continue
        matched = _areas_for(path, listed)
        if len(matched) > 1:
            return Tier("full", "mixed")
        if len(matched) == 1:
            areas.append(matched[0])
            continue
        if _is_doc(path):
            saw_doc = True
            continue
        return Tier("full", "unknown")

    if full_reasons:
        unique = list(dict.fromkeys(full_reasons))
        reason = unique[0] if len(unique) == 1 else "mixed"
        return Tier("full", reason)

    unique_areas = list(dict.fromkeys(areas))
    if len(unique_areas) > 1:
        return Tier("full", "mixed")
    if len(unique_areas) == 1:
        area = unique_areas[0]
        tests = listed[area]
        if not tests:
            return Tier("full", "unknown")
        return Tier("area", "area", area=area, tests=tests)
    if saw_doc:
        return Tier("docs", "docs")
    return Tier("full", "unknown")


def write_github_output(tier: Tier, output: Path, paths_out: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as handle:
        handle.write(f"tier={tier.kind}\n")
        handle.write(f"reason={tier.reason}\n")
        handle.write(f"area={tier.area}\n")
        handle.write(f"skip_pytest={'true' if tier.skip_pytest else 'false'}\n")
    text = "\n".join(tier.tests)
    if text:
        text += "\n"
    paths_out.parent.mkdir(parents=True, exist_ok=True)
    paths_out.write_text(text, encoding="utf-8")


def _read_paths(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pick the CI test tier.")
    parser.add_argument("--event", default="pull_request")
    parser.add_argument("--ref", default="")
    parser.add_argument("--paths-file", type=Path)
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--paths-out", type=Path)
    parser.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args(argv)

    paths = _read_paths(args.paths_file) if args.paths_file else []
    tier = decide(paths, event=args.event, ref=args.ref, root=args.root)
    print(
        f"tier={tier.kind} reason={tier.reason} area={tier.area} "
        f"tests={len(tier.tests)} skip_pytest={str(tier.skip_pytest).lower()}"
    )
    if args.github_output or args.paths_out:
        if args.github_output is None or args.paths_out is None:
            print("pass both --github-output and --paths-out", file=sys.stderr)
            return 2
        write_github_output(tier, args.github_output, args.paths_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
