"""Pick which tests a pull request has to run.

Push is not tiered. ``decide`` returns the full suite for every push,
including push to main, even if the diff is only docs.

Pull requests:

* docs: markdown, docs/, assets, fonts, images, LICENSE. Pytest does not run.
* area: every non-doc path sits in one mapped area. Pytest runs that area.
* full: routing, prompts, tool schemas, shared core, workflows, locks,
  several areas, or anything that is not confidently mapped.

The workflow calls this from inside the existing jobs. It does not skip
those jobs, so the required check names still report a conclusion.
"""

from __future__ import annotations

import argparse
import fnmatch
import sys
from dataclasses import dataclass
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
)

# name, paths that belong to the area, pytest targets for that area.
# A helper can mark the area without itself being a test.
_AREAS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "browser",
        ("arelis/browser/", "tests/test_browser_*.py"),
        ("tests/test_browser_*.py",),
    ),
    (
        "calendar",
        ("arelis/calendar/", "tests/test_calendar*.py"),
        ("tests/test_calendar*.py", "tests/test_agenda*.py"),
    ),
    (
        "earth",
        ("arelis/earth/", "tests/earth_helpers.py", "tests/test_earth*.py"),
        ("tests/test_earth*.py",),
    ),
    (
        "memory",
        ("arelis/memory/", "tests/test_memory*.py"),
        ("tests/test_memory*.py",),
    ),
    (
        "physics",
        ("arelis/physics/", "tests/test_physics*.py", "tests/test_collision.py"),
        ("tests/test_physics*.py", "tests/test_collision.py"),
    ),
    (
        "sms",
        ("arelis/sms.py", "arelis/sms_*.py", "tests/test_sms*.py"),
        ("tests/test_sms*.py",),
    ),
    (
        "voice",
        (
            "arelis/voice/",
            "tests/voice_helpers.py",
            "tests/test_voice_*.py",
            "tests/test_wake.py",
            "tests/test_speech_text.py",
            "tests/test_stt_repair.py",
        ),
        (
            "tests/test_voice_*.py",
            "tests/test_wake.py",
            "tests/test_speech_text.py",
            "tests/test_stt_repair.py",
        ),
    ),
)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp"}
_TEXT_NAMES = {"LICENSE", "COPYING"}


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


def _full_reason(path: str) -> str | None:
    for reason, patterns in _FULL:
        if any(_matches(path, pattern) for pattern in patterns):
            return reason
    return None


def _area_name(path: str) -> str | None:
    found: list[str] = []
    for name, patterns, _tests in _AREAS:
        if any(_matches(path, pattern) for pattern in patterns):
            found.append(name)
    if len(found) == 1:
        return found[0]
    return None


def _is_doc(path: str) -> bool:
    if path.startswith("tests/"):
        return False
    if path in _TEXT_NAMES or Path(path).name in _TEXT_NAMES:
        return True
    lower = path.lower()
    if lower.endswith((".md", ".markdown", ".rst")):
        return True
    if lower == "docs" or lower.startswith("docs/"):
        return True
    if lower.startswith("assets/") or lower.startswith("arelis/assets/"):
        return True
    if lower.startswith("arelis/ui/fonts/"):
        return True
    return Path(lower).suffix in _IMAGE_SUFFIXES


def _expand(patterns: tuple[str, ...], root: Path) -> tuple[str, ...]:
    found: list[str] = []
    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            matches = sorted(root.glob(pattern))
        else:
            candidate = root / pattern
            matches = [candidate] if candidate.is_file() else []
        for match in matches:
            if match.is_file():
                found.append(match.relative_to(root).as_posix())
    return tuple(sorted(set(found)))


def _tests_for(area: str, root: Path) -> tuple[str, ...]:
    for name, _patterns, tests in _AREAS:
        if name == area:
            return _expand(tests, root)
    return ()


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

    full_reasons: list[str] = []
    areas: list[str] = []
    saw_doc = False
    for path in cleaned:
        reason = _full_reason(path)
        if reason is not None:
            full_reasons.append(reason)
            continue
        area = _area_name(path)
        if area is not None:
            areas.append(area)
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
        tests = _tests_for(area, root)
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
