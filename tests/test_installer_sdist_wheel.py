"""SDIST_ONLY packages are wheeled on the runner, not built inside the embeddable tree."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent / "win-installer"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"_inst_{name}", ROOT / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_build(build, monkeypatch, tmp_path, wheel_name="jieba-0.42.1-py3-none-any.whl"):
    """Point build.py at a scratch dir and record every pip command it would run.

    A fake `pip wheel` drops a wheel with the given name into --wheel-dir, so the steps
    after it run for real. Nothing is downloaded or installed.
    """
    calls: list[list[str]] = []

    def fake_run(command, what, cwd=None):
        cmd = [str(part) for part in command]
        calls.append(cmd)
        if "--wheel-dir" in cmd and "wheel" in cmd:
            out = Path(cmd[cmd.index("--wheel-dir") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / wheel_name).write_bytes(b"")
        return ""

    monkeypatch.setattr(build, "run", fake_run)
    monkeypatch.setattr(build, "BUILD", tmp_path)
    monkeypatch.setattr(build, "python_exe", lambda: tmp_path / "tree" / "python.exe")
    return calls


def _arg_after(cmd: list[str], flag: str) -> str:
    return cmd[cmd.index(flag) + 1]


def test_runner_wheel_step_is_hash_checked_from_the_locks_sdist_pin(monkeypatch, tmp_path) -> None:
    build = _load("build")
    calls = _fake_build(build, monkeypatch, tmp_path)
    build.install_sdist_only_wheels()
    wheel_cmd = next(c for c in calls if c[1:4] == ["-m", "pip", "wheel"])
    for flag in ("--require-hashes", "--no-deps", "--no-binary"):
        assert flag in wheel_cmd, f"pip wheel lost {flag}"
    assert _arg_after(wheel_cmd, "--no-binary") == "jieba"
    # The one-line requirements file it reads carries the lock's sdist hash.
    req_text = Path(_arg_after(wheel_cmd, "-r")).read_text(encoding="utf-8")
    lock_text = (ROOT / "requirements-win-amd64-cp314.txt").read_text(encoding="utf-8")
    pin = re.search(r"^jieba==\S+ --hash=sha256:[0-9a-f]{64}$", lock_text, re.M)
    assert pin and pin.group(0) in req_text


def test_tree_install_is_offline_and_runs_after_the_wheel_step(monkeypatch, tmp_path) -> None:
    build = _load("build")
    calls = _fake_build(build, monkeypatch, tmp_path)
    build.install_sdist_only_wheels()
    wheel_at = next(i for i, c in enumerate(calls) if "wheel" in c and "--wheel-dir" in c)
    tree_at = next(i for i, c in enumerate(calls) if "--no-index" in c)
    assert wheel_at < tree_at
    tree_cmd = calls[tree_at]
    assert tree_cmd[0].endswith("python.exe")
    for flag in ("--no-deps", "--no-index", "--find-links"):
        assert flag in tree_cmd
    assert "--no-binary" not in tree_cmd
    assert tree_cmd[-1].startswith("jieba==")


def test_a_wheel_that_is_not_pure_python_fails_the_build(monkeypatch, tmp_path) -> None:
    build = _load("build")
    calls = _fake_build(
        build, monkeypatch, tmp_path, wheel_name="jieba-0.42.1-cp314-cp314-win_amd64.whl"
    )
    with pytest.raises(SystemExit) as raised:
        build.install_sdist_only_wheels()
    assert "py3-none-any" in str(raised.value)
    # It stopped before anything was installed into the tree.
    assert not any("--no-index" in c for c in calls)


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


