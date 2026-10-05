"""SDIST_ONLY packages are wheeled on the runner, not built inside the embeddable tree."""

from __future__ import annotations

import importlib.util
import inspect
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "win-installer"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_inst_{name}", ROOT / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tree_pip_install_does_not_pass_no_binary() -> None:
    build = _load("build")
    source = inspect.getsource(build.install_locked_dependencies)
    assert "--no-binary" not in source
    wheel_source = inspect.getsource(build.install_sdist_only_wheels)
    assert "--no-binary" in wheel_source
    assert "--require-hashes" in wheel_source


def test_is_pure_py3_wheel_accepts_only_py3_none_any() -> None:
    build = _load("build")
    assert build.is_pure_py3_wheel("jieba-0.42.1-py3-none-any.whl")
    assert not build.is_pure_py3_wheel("jieba-0.42.1-cp314-cp314-win_amd64.whl")
    assert not build.is_pure_py3_wheel("jieba-0.42.1-py2.py3-none-any.whl")


def test_lock_without_sdist_only_drops_exactly_those_projects() -> None:
    build = _load("build")
    lock = _load("lock")
    text = (ROOT / "requirements-win-amd64-cp314.txt").read_text(encoding="utf-8")
    filtered = build.lock_without_sdist_only(text)

    def pinned_names(body: str) -> set[str]:
        names: set[str] = set()
        for raw in body.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r"([A-Za-z0-9._-]+)\s*==", line)
            assert match, line
            names.add(lock.normalise(match.group(1)))
        return names

    original = pinned_names(text)
    remaining = pinned_names(filtered)
    assert remaining == original - set(lock.SDIST_ONLY)
    for name in lock.SDIST_ONLY:
        assert name not in remaining
        assert re.search(rf"^{re.escape(name)}==", text, re.M)
        assert not re.search(rf"^{re.escape(name)}==", filtered, re.M)


def test_every_sdist_only_name_is_in_the_lock_with_a_hash() -> None:
    lock = _load("lock")
    pinned = lock.read_lock()
    text = (ROOT / "requirements-win-amd64-cp314.txt").read_text(encoding="utf-8")
    for name in lock.SDIST_ONLY:
        assert name in pinned, f"{name} is allowlisted but not in the lock"
        match = re.search(
            rf"^{re.escape(name)}==[^\s]+\s+--hash=sha256:[0-9a-f]{{64}}\s*$",
            text,
            re.M,
        )
        assert match, f"{name} pin is missing a sha256 hash"
