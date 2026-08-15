"""Pin the exact dependency set the Windows installer ships, with hashes.

Why a lockfile rather than letting the build install `arelis[installer]`
=======================================================================

Because otherwise no two installers are the same program. The dependency floors in
pyproject.toml are floors on purpose -- somebody installing Arelis with pip should get
current libraries -- but an installer handed to a person who has never installed
Python is a different promise. It has to be the build that was tested, not the build
that happened to resolve on the morning it was cut.

That is not hypothetical drift. Resolving this set the day this file was written
picked ten packages at versions newer than the ones the test suite had actually run
against: numpy 2.5.2 against a tested 2.5.1, av 18.1.0 against 18.0.0, pypdf 6.16.1
against 6.15.0. Every one of those is an upstream project's ordinary Tuesday. None of
them was chosen, reviewed or run. pyproject.toml already makes this argument about
ruff, where a floor meant a new lint rule turned an untouched tree red on somebody
else's pull request; shipping an interpreter and 76 libraries to strangers is the same
mistake with a worse blast radius.

So the installer installs from `requirements-win-amd64-cp314.txt`, every line pinned
with `==` and carrying a sha256, and the build passes `--require-hashes`. Which buys a
second thing beyond reproducibility: pip refuses to install an archive whose hash does
not match, so a compromised mirror or a corrupted download fails the build instead of
being signed into an installer and handed out.

Why the hashes cost nothing
===========================

The obvious way to get them is to download every wheel and hash it, which is about a
gigabyte for this set. Not necessary. pip's `--report` already carries the sha256 of
each chosen archive, taken from the index metadata, and `--dry-run` means it never
fetches the archives themselves. Regenerating this lock is a few seconds and a few
hundred kilobytes.

Why `--check` does not re-resolve
================================

A check that compared the lock against a fresh resolution would go red whenever any
of 76 upstream projects published anything, on a pull request that touched none of
it. That is the failure mode pyproject.toml pins ruff to avoid. So `--check` is
offline and asks the only question that can be answered without the network and that
anyone can actually act on: is every dependency this project declares for the
installer present in the lock, and is every line pinned and hashed. It catches the
real mistake, which is adding a dependency and shipping an installer without it.
Taking new upstream versions stays a deliberate act: run this file, then run the
tests against what it produced.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
LOCK_PATH = HERE / "requirements-win-amd64-cp314.txt"

# The interpreter the installer ships, and so the only platform this lock describes.
# 3.12 is not a candidate: its last Windows binary was 3.12.10 in April 2025 and every
# release since is source only, so bundling it would mean bundling an interpreter that
# can never receive another security fix in a form we can ship. 3.13 leaves the bugfix
# phase within months. 3.14 receives official Windows builds into late 2027, and is
# already what this project is developed and tested on.
PYTHON_VERSION = "3.14"
PLATFORM = "win_amd64"

# Resolved instead of a list repeated here. See the `installer` extra in pyproject.
EXTRA = "installer"

# Arelis itself is installed from the wheel the build just made, which has no hash on
# any index and no business in a file of third-party pins.
SELF = "arelis"


def run(command: list[str], what: str) -> None:
    """Run pip, and on failure show what it said.

    subprocess with check=True and capture_output raises an exception whose message is
    the command line, and throws away the only part anyone needs: the resolver
    explaining which package it could not find a wheel for.
    """
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(f"\n{what} failed.\n\n")
        sys.stderr.write((result.stdout or "").strip() + "\n")
        sys.stderr.write((result.stderr or "").strip() + "\n")
        raise SystemExit(result.returncode)


def normalise(name: str) -> str:
    """PyPI's name equivalence, which is why `sherpa_onnx` and `sherpa-onnx` are one
    package and why a lookup that only lowercases silently misses PySide6_Essentials.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def build_wheel(destination: Path) -> Path:
    """Build the arelis wheel, because the resolution has to start from real metadata.

    Resolving the source directory would mean asking pip to install a source tree
    under `--only-binary=:all:`, which it correctly refuses. Building first also means
    the extras being resolved are the ones the built distribution actually declares,
    rather than what the current pyproject would declare if the build backend agreed.
    """
    run(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(destination),
         str(REPO_ROOT)],
        "Building the arelis wheel",
    )
    wheels = sorted(destination.glob("arelis-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"expected exactly one arelis wheel in {destination}, found {wheels}")
    return wheels[0]


def resolve(wheel: Path, scratch: Path) -> list[dict]:
    """Ask pip what it would install on Windows for cp314, and to fail if it cannot.

    `--only-binary=:all:` is the point rather than an optimisation: the installer build
    has no compiler, so a dependency that exists only as a source distribution for this
    platform must fail here, loudly, and not halfway through a build.
    """
    report = scratch / "report.json"
    run(
        [
            sys.executable, "-m", "pip", "install",
            "--dry-run",
            "--ignore-installed",
            "--only-binary=:all:",
            "--platform", PLATFORM,
            "--python-version", PYTHON_VERSION,
            # Required by pip whenever --platform is given. --dry-run means nothing is
            # written to it, but it still has to name somewhere.
            "--target", str(scratch / "unused"),
            "--report", str(report),
            f"{wheel}[{EXTRA}]",
        ],
        f"Resolving the {EXTRA} extra for {PLATFORM} on Python {PYTHON_VERSION}",
    )
    # utf-8 explicitly. The default on Windows is cp1252, and a single non-Latin
    # character in any of 76 packages' metadata is enough to end the run.
    return json.loads(report.read_text(encoding="utf-8"))["install"]


def lock_lines(entries: list[dict]) -> list[str]:
    lines: list[str] = []
    missing: list[str] = []
    for entry in sorted(entries, key=lambda e: normalise(e["metadata"]["name"])):
        name = entry["metadata"]["name"]
        if normalise(name) == SELF:
            continue
        version = entry["metadata"]["version"]
        digest = entry.get("download_info", {}).get("archive_info", {}).get("hashes", {}).get(
            "sha256"
        )
        if not digest:
            missing.append(name)
            continue
        lines.append(f"{name}=={version} --hash=sha256:{digest}")
    if missing:
        # Refuse rather than write a lock that cannot be installed with
        # --require-hashes, which is the only way the hashes are load-bearing.
        raise SystemExit(
            "no sha256 in the index metadata for: " + ", ".join(sorted(missing)) + "\n"
            "A lock missing any hash cannot be installed with --require-hashes."
        )
    return lines


def declared_dependencies() -> set[str]:
    """The distributions the installer extra pulls in directly, from pyproject.

    Only the names written down by this project, not the transitive closure -- the
    closure is what resolution is for. This is the set `--check` insists on finding,
    because forgetting to regenerate after adding a dependency is the mistake that
    ships a broken installer.
    """
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = data["project"]["optional-dependencies"]

    names: set[str] = set()
    pending = list(extras[EXTRA])
    seen_extras = {EXTRA}
    while pending:
        requirement = pending.pop()
        # `arelis[voice]` refers back into this project's own extras; follow it rather
        # than recording arelis as a dependency of itself.
        self_reference = re.fullmatch(rf"{SELF}\[([\w,-]+)\]", requirement.strip())
        if self_reference:
            for extra in self_reference.group(1).split(","):
                if extra not in seen_extras:
                    seen_extras.add(extra)
                    pending.extend(extras[extra])
            continue
        name = re.split(r"[<>=!~\[;\s]", requirement.strip(), maxsplit=1)[0]
        if name:
            names.add(normalise(name))
    for name in data["project"]["dependencies"]:
        names.add(normalise(re.split(r"[<>=!~\[;\s]", name.strip(), maxsplit=1)[0]))
    return names


def read_lock() -> dict[str, str]:
    if not LOCK_PATH.exists():
        raise SystemExit(f"no lock at {LOCK_PATH}. Run: python {Path(__file__).name}")
    found: dict[str, str] = {}
    for number, raw in enumerate(LOCK_PATH.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9._-]+)==([^\s]+)\s+--hash=sha256:([0-9a-f]{64})", line)
        if not match:
            raise SystemExit(
                f"{LOCK_PATH.name}:{number}: not a pinned, hashed requirement: {line}"
            )
        found[normalise(match.group(1))] = match.group(2)
    return found


def check() -> int:
    locked = read_lock()
    declared = declared_dependencies()
    absent = sorted(declared - set(locked))
    if absent:
        print("These are declared for the installer but absent from the lock:")
        for name in absent:
            print("  " + name)
        print("")
        print(f"Regenerate it:  python {Path(__file__).relative_to(REPO_ROOT)}")
        print("Then run the tests against what it produced before shipping it.")
        return 1
    print(f"{LOCK_PATH.name}: {len(locked)} packages, all pinned and hashed.")
    print(f"All {len(declared)} directly declared dependencies are present.")
    return 0


def generate() -> int:
    with tempfile.TemporaryDirectory(prefix="arelis-lock-") as raw:
        scratch = Path(raw)
        print("Building the wheel, so extras resolve from real metadata...")
        wheel = build_wheel(scratch)
        print(f"Resolving {wheel.name}[{EXTRA}] for {PLATFORM}, Python {PYTHON_VERSION}...")
        entries = resolve(wheel, scratch)
        lines = lock_lines(entries)

    header = [
        "# Generated by win-installer/lock.py. Do not edit by hand.",
        "#",
        f"# The exact dependency set the Windows installer ships, for {PLATFORM} on",
        f"# CPython {PYTHON_VERSION}. Regenerate with:",
        "#",
        "#     python win-installer/lock.py",
        "#",
        "# Then run the test suite against what it produced. Taking new upstream",
        "# versions is meant to be a deliberate act with a commit attached, not",
        "# something that happens because a build ran on a different day.",
        "#",
        "# Installed with --require-hashes, so a mirror serving a different archive",
        "# than the one resolved here fails the build rather than reaching anybody.",
        "",
    ]
    LOCK_PATH.write_text("\n".join(header + lines) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {LOCK_PATH.relative_to(REPO_ROOT)}: {len(lines)} packages.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lock.py",
        description="Pin the dependency set the Windows installer ships.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Offline. Verify every line is pinned and hashed and that nothing declared "
            "for the installer is missing from the lock. Does not re-resolve, so it "
            "cannot go red because an unrelated project published a release."
        ),
    )
    args = parser.parse_args(argv)
    return check() if args.check else generate()


if __name__ == "__main__":
    sys.exit(main())
