"""The sdist-only exception in the installer lock stays tiny and in step.

lock.py resolves with --only-binary=:all:. A short allowlist of pure-Python projects
that publish no wheel (jieba, for misaki[zh]) is the one exception, and build.py has
to name exactly the same projects when it wheels them on the runner.
"""

from __future__ import annotations

import ast
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


def test_everything_else_still_installs_binary_only() -> None:
    """The locked install argv carries the flags. A comment with the same words does not."""
    tree = ast.parse((ROOT / "build.py").read_text(encoding="utf-8"))
    argv = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or len(node.args) < 2:
            continue
        label = node.args[1]
        if isinstance(label, ast.Constant) and label.value == "Installing the locked dependency set":
            argv = node.args[0]
            break
    assert isinstance(argv, ast.List), "locked install lost its argv list"
    flags = [
        elt.value
        for elt in argv.elts
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
    ]
    assert "--require-hashes" in flags
    start = flags.index("--require-hashes")
    assert flags[start : start + 3] == ["--require-hashes", "--only-binary", ":all:"]


def test_read_lock_accepts_multi_hash_dependabot_lines_and_rejects_unhashed(
    monkeypatch, tmp_path
) -> None:
    """Dependabot security PRs write wheel + sdist sha256 flags on one line; lock.py --check must accept them while rejecting unpinned or unhashed lines."""
    import pytest

    sample = (
        "soupsieve==4.1.3 "
        "--hash=sha256:7a390d1a57d1ab7bb228531e9b8a750a5ebf87db774e0ef6faeeac057d22a5bf "
        "--hash=sha256:ccd6470b256394ac44b08b86fd94b30a17d335a5335c8a3d15565f7b03d3c8cf\n"
    )
    for folder in ("win-installer", "mac-installer"):
        spec = importlib.util.spec_from_file_location(
            f"_lock_{folder}", ROOT.parent / folder / "lock.py"
        )
        assert spec and spec.loader
        lock = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lock)

        fake_lock = tmp_path / f"{folder}-req.txt"
        fake_lock.write_text(sample, encoding="utf-8")
        monkeypatch.setattr(lock, "LOCK_PATH", fake_lock)
        assert lock.read_lock() == {"soupsieve": "4.1.3"}

        fake_lock.write_text("soupsieve==4.1.3\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            lock.read_lock()

