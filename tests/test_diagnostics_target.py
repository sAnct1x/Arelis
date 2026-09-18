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

import os
import subprocess
import sys

import pytest

from arelis.core.claims import detect_diagnostics_ask
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


async def test_omitted_target_still_runs_the_full_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run()
    assert result.ok
    assert calls, "full suite path must still start pytest"
    target = _norm(_pytest_target(calls[0]))
    assert target.endswith("tests") or target == "tests"
    assert not target.endswith(".py")


async def test_suite_all_without_target_is_the_full_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run(suite="all")
    assert result.ok
    target = _norm(_pytest_target(calls[0]))
    assert target.endswith("tests") or target == "tests"
    assert not target.endswith(".py")


async def test_bare_filename_resolves_under_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """target='test_foo.py' becomes tests/test_foo.py (probe stands in for foo)."""
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run(target=_PROBE)
    assert result.ok
    assert calls, "a contained existing target must start pytest"
    seen = _norm(_pytest_target(calls[0]))
    assert seen.endswith(f"tests/{_PROBE}") or seen.endswith(_PROBE)
    assert "tests/" in seen or seen.endswith(_PROBE)
    assert not seen.rstrip("/").endswith("tests")


async def test_tests_prefixed_path_is_not_doubled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run(target=f"tests/{_PROBE}")
    assert result.ok
    seen = _norm(_pytest_target(calls[0]))
    assert seen.endswith(f"tests/{_PROBE}")
    assert "tests/tests/" not in seen


async def test_nodeid_is_what_pytest_sees(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run(target=f"{_PROBE}::test_diag_probe")
    assert result.ok
    seen = _norm(_pytest_target(calls[0]))
    assert seen.endswith(f"tests/{_PROBE}::test_diag_probe")


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


async def test_walkout_through_tests_prefix_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run(target="tests/../arelis/tools/diagnostics.py")
    assert not result.ok
    assert result.data.get("fail_class") == "fail:target"
    assert not calls


async def test_windows_drive_path_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run(target=_WIN_ABS)
    assert not result.ok
    assert result.data.get("fail_class") == "fail:target"
    assert "[fail:target]" in result.output
    assert not calls


async def test_missing_file_is_not_a_green_suite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutant 2: missing file still ok=True."""
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run(target=_MISSING)
    assert result.ok is False
    assert result.data.get("fail_class") == "fail:missing"
    assert "[fail:missing]" in result.output
    assert "green" not in result.output.lower()
    assert "passed" not in result.data
    assert "failed" not in result.data
    assert result.data.get("green") is not True
    assert not calls


async def test_target_is_not_ignored_for_the_full_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutant 3: target ignored, argv is always tests/."""
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run(target=_PROBE)
    assert result.ok
    assert calls
    seen = _norm(_pytest_target(calls[0]))
    assert _PROBE in seen
    assert not (seen.endswith("tests") or seen == "tests")


async def test_nest_guard_still_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARELIS_IN_DIAGNOSTICS", "1")
    calls = _patch_pytest(monkeypatch)
    result = await DiagnosticsTool().run(target=_PROBE)
    assert not result.ok
    assert "nest" in result.output.lower()
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


@pytest.mark.skipif(
    os.environ.get("ARELIS_IN_DIAGNOSTICS") == "1",
    reason="already inside diagnostics; do not nest pytest",
)
async def test_a_real_tiny_target_runs_pytest() -> None:
    result = await DiagnosticsTool().run(target=_PROBE)
    assert result.ok, result.output
    assert result.data.get("passed") == 1
    assert result.data.get("failed") == 0
    assert result.data.get("green") is True
    target = _norm(str(result.data.get("target") or ""))
    assert target.endswith(f"tests/{_PROBE}")


def test_run_the_inbox_tests_is_a_diagnostics_ask() -> None:
    assert detect_diagnostics_ask("run the inbox tests")


def test_howto_is_still_not_a_diagnostics_ask() -> None:
    assert not detect_diagnostics_ask("how do I run the tests?")
