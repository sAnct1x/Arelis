"""The sdist-only exception in the installer lock stays tiny and in step.

lock.py resolves with --only-binary=:all:. A short allowlist of pure-Python projects
that publish no wheel (jieba, for misaki[zh]) is the one exception, and build.py has
to name exactly the same projects when it installs, or the hashed sdist is refused.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "win-installer"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_inst_{name}", ROOT / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_allowlist_is_exactly_jieba_and_build_agrees() -> None:
    lock = _load("lock")
    assert lock.SDIST_ONLY == frozenset({"jieba"})
    source = (ROOT / "build.py").read_text(encoding="utf-8")
    match = re.search(r"^SDIST_ONLY = \((.*?)\)", source, re.M)
    assert match, "build.py lost SDIST_ONLY"
    names = {part.strip().strip("\"'") for part in match.group(1).split(",") if part.strip()}
    assert names == set(lock.SDIST_ONLY)


def test_the_lock_pins_every_allowlisted_project_with_a_hash() -> None:
    lock = _load("lock")
    pinned = lock.read_lock()
    for name in lock.SDIST_ONLY:
        assert name in pinned, f"{name} is allowlisted but not in the lock"


def test_everything_else_still_installs_binary_only() -> None:
    source = (ROOT / "build.py").read_text(encoding="utf-8")
    assert '"--only-binary", ":all:"' in source
    assert "--require-hashes" in source
