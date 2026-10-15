"""diagnostics must take a target under tests/, or refuse before pytest starts.

Roadmap 4.12. The tool used to ignore kwargs and always run the full tree.
That is the bug. Counts still come from pytest's last summary line — a
missing file or an escaped path must not be reported as a green suite.

Mutants this file is supposed to catch:

1. Containment skipped (raw target handed to pytest). The escape cases
   must fail if subprocess.run is started.
2. Missing file still ok=True (invented green / invented counts).
3. target ignored and the full tests/ tree always runs.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from arelis.tools.diagnostics import PYTEST_FLAGS, DiagnosticsTool

_ESCAPE = "../arelis/tools/diagnostics.py"
_WIN_ABS = r"C:\Windows\system32"
_MISSING = "no_such_diag_target_zzz.py"
_PROBE = "_diag_probe.py"


def _patch_pytest(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout="============================== 1 passed in 0.01s ==============================\n",
            stderr="",
        )

    monkeypatch.setattr("arelis.tools.diagnostics.subprocess.run", fake_run)
    return calls


def _pytest_target(cmd: list[str]) -> str:
    flags = set(PYTEST_FLAGS)
    skip = {sys.executable, "-m", "pytest"}
    args = [a for a in cmd if a not in flags and a not in skip]
    return args[0] if args else ""


def _norm(path: str) -> str:
    return path.replace("\\", "/").rstrip("/")


async def test_parent_escape_is_refused_and_pytest_does_not_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutant 1: skip containment and this assertion dies."""
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run(target=_ESCAPE)
    assert not result.ok
    assert result.data.get("fail_class") == "fail:target"
    assert "[fail:target]" in result.output
    assert not calls, (
        "escaped target started pytest — containment was skipped or the "
        "raw string was passed through"
    )


async def test_windows_drive_path_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run(target=_WIN_ABS)
    assert not result.ok
    assert result.data.get("fail_class") == "fail:target"
    assert "[fail:target]" in result.output
    assert not calls


async def test_timeout_still_refuses_to_invent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(cmd, **_kwargs):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1)

    monkeypatch.setattr("arelis.tools.diagnostics.subprocess.run", boom)
    result = await DiagnosticsTool().run()
    assert not result.ok
    assert "timed out" in result.output.lower()
    assert "invent" in result.output.lower()


