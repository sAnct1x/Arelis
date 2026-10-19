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
