"""Windows os.kill(pid, 0) scan, and pid_is_alive without that call."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

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


def test_check_script_fails_on_tmp_fixture(tmp_path: Path) -> None:
    (tmp_path / "probe.py").write_text(
        "def poke(pid):\n    os.kill(pid, 0)\n",
        encoding="utf-8",
    )
    result = _run_check(str(tmp_path))
    assert result.returncode != 0
    assert "os.kill" in result.stderr


def test_check_script_ignores_other_kills(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text(
        "os.killpg(proc.pid, signal.SIGKILL)\nproc.kill()\n",
        encoding="utf-8",
    )
    result = _run_check(str(tmp_path))
    assert result.returncode == 0
    assert result.stderr == ""


def test_check_script_exits_zero_on_arelis_package() -> None:
    result = _run_check()
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_ci_lock_job_runs_the_windows_footgun_scan() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    lock_block = text.split("\n  lock:", 1)[1].split("\n  installed:", 1)[0]
    assert "python win-installer/lock.py --check" in lock_block
    assert "python scripts/check_windows_footguns.py" in lock_block
