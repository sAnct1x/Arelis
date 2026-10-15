"""Windows os.kill(pid, 0) scan, and pid_is_alive without that call."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from arelis.presence.lock import pid_is_alive

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_windows_footguns.py"


def _run_check(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_pid_is_alive_self_and_fake_pid() -> None:
    assert pid_is_alive(os.getpid()) is True
    assert pid_is_alive(0) is False
    assert pid_is_alive(-3) is False
    # A pid that is not an allocated process on this host.
    assert pid_is_alive(2_147_483_647) is False


def test_check_script_exits_zero_on_arelis_package() -> None:
    result = _run_check()
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def _checker():
    spec = importlib.util.spec_from_file_location("check_windows_footguns", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_scan_visits_scripts(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _checker()
    seen: list[Path] = []
    real = module.iter_hits

    def spy(root: Path):
        seen.append(Path(root).resolve())
        return real(root)

    monkeypatch.setattr(module, "iter_hits", spy)
    code = module.main([])
    assert (ROOT / "scripts").resolve() in seen
    assert (ROOT / "arelis").resolve() in seen
    assert code == 0


