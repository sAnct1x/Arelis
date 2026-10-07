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


def _checker():
    spec = importlib.util.spec_from_file_location("check_windows_footguns", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "body",
    [
        "def poke(pid):\n    os.kill(\n        pid,\n        0,\n    )\n",
        "from os import kill\n\ndef poke(pid):\n    kill(pid, 0)\n",
        "def poke(pid):\n    sig = 0\n    os.kill(pid, sig)\n",
        "def poke(pid):\n    os.kill(pid, 0x0)\n",
        "def poke(pid):\n    os.kill(pid, sig=0)\n",
        "import signal\n\ndef poke(pid):\n    os.kill(pid, signal.CTRL_C_EVENT)\n",
        "from signal import CTRL_C_EVENT\n\ndef poke(pid):\n    os.kill(pid, CTRL_C_EVENT)\n",
        "import os as host\n\ndef poke(pid):\n    host.kill(pid, 0)\n",
    ],
    ids=[
        "split-call",
        "imported-kill",
        "named-zero",
        "hex-zero",
        "keyword",
        "ctrl-c-attr",
        "ctrl-c-import",
        "os-alias",
    ],
)
def test_scan_flags_zero_and_ctrl_c(tmp_path: Path, body: str) -> None:
    (tmp_path / "probe.py").write_text(body, encoding="utf-8")
    result = _run_check(str(tmp_path))
    assert result.returncode != 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "body",
    [
        "def poke(pid):\n    os.kill(pid, 9)\n",
        "import signal\n\ndef poke(pid):\n    os.kill(pid, signal.SIGTERM)\n",
        "from os import kill\n\ndef poke(pid):\n    kill(pid, 15)\n",
        "def poke(pid):\n    sig = 0\n    sig = 9\n    os.kill(pid, sig)\n",
        "os.killpg(proc.pid, 0)\n",
        "# os.kill(pid, 0) stays a comment\n",
        'note = "os.kill(pid, 0)"\n',
    ],
    ids=[
        "signal-nine",
        "sigterm",
        "imported-nonzero",
        "rebound-name",
        "killpg",
        "comment",
        "string",
    ],
)
def test_scan_leaves_ordinary_kills_alone(tmp_path: Path, body: str) -> None:
    (tmp_path / "ok.py").write_text(body, encoding="utf-8")
    result = _run_check(str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


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


@pytest.mark.skipif(os.name == "nt", reason="libc kill is the POSIX branch")
def test_pid_is_alive_libc_branch_without_proc(monkeypatch: pytest.MonkeyPatch) -> None:
    real_is_file = Path.is_file
    real_is_dir = Path.is_dir

    def is_file(self: Path, *args, **kwargs):
        if str(self).replace("\\", "/").startswith("/proc"):
            return False
        return real_is_file(self, *args, **kwargs)

    def is_dir(self: Path, *args, **kwargs):
        if str(self).replace("\\", "/").startswith("/proc"):
            raise AssertionError(f"procfs used for {self}")
        return real_is_dir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", is_file)
    monkeypatch.setattr(Path, "is_dir", is_dir)
    assert pid_is_alive(os.getpid()) is True
    assert pid_is_alive(2_147_483_647) is False
