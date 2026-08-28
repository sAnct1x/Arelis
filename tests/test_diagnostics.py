"""Diagnostics — full pytest suite, honest summary, tight trigger."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from arelis.config import PROJECT_ROOT
from arelis.core.claims import detect_diagnostics_ask, detect_exactness_need
from arelis.core.evidence import EvidenceLedger
from arelis.core.skills import select_skill_ids
from arelis.core.tool_subset import ALWAYS_ON_TOOLS, filter_tool_names
from arelis.tools import build_tool_registry
from arelis.tools.diagnostics import (
    PYTEST_FLAGS,
    DiagnosticsTool,
    format_report,
    parse_pytest,
)
from arelis.workspace import WorkspaceRoots

_RED = """\
FAILED tests/test_sms.py::test_send - AssertionError
E   assert sent is False
plugin said 12 passed in setup
===== 1 failed, 10 passed, 2 skipped in 1.23s =====
"""

_GREEN = """\
..........
===== 10 passed, 2 skipped in 0.40s =====
"""

_COLLECTION = """\
ERROR tests/test_broken.py
E   SyntaxError: invalid syntax
===== 1 error in 0.08s =====
"""

_NO_TESTS = """\
collected 0 items
===== no tests ran in 0.02s =====
"""

_INTERRUPTED = """\
.....
!!!!! KeyboardInterrupt !!!!!
===== 5 passed in 0.50s =====
"""

_NOISY_TRACE = """\
FAILED tests/test_foo.py::test_bar - assert 0
E   the helper said 4 passed before it died
===== 1 failed in 0.11s =====
"""


def test_parse_red_suite() -> None:
    parsed = parse_pytest(_RED, "", 1, 1.23)
    assert parsed["failed"] == 1
    assert parsed["passed"] == 10
    assert parsed["skipped"] == 2
    assert parsed["failed_names"] == ["tests/test_sms.py::test_send"]
    assert parsed["green"] is False
    assert parsed["exit_meaning"] == "failed"


def test_parse_ignores_passed_inside_a_trace() -> None:
    """A traceback that says '4 passed' must not become the total."""
    parsed = parse_pytest(_NOISY_TRACE, "", 1, 0.11)
    assert parsed["passed"] == 0
    assert parsed["failed"] == 1
    assert parsed["green"] is False


def test_parse_green_suite() -> None:
    parsed = parse_pytest(_GREEN, "", 0, 0.4)
    assert parsed["passed"] == 10
    assert parsed["failed"] == 0
    assert parsed["green"] is True
    report = format_report(parsed, root=Path("."))
    assert "the suite is green" in report.lower()
    assert "2 skipped" in report


def test_parse_collection_error() -> None:
    parsed = parse_pytest(_COLLECTION, "", 1, 0.08)
    assert parsed["errors"] == 1
    assert parsed["failed_names"] == ["tests/test_broken.py"]
    assert parsed["green"] is False


def test_parse_no_tests_is_not_green() -> None:
    parsed = parse_pytest(_NO_TESTS, "", 5, 0.02)
    assert parsed["no_tests"] is True
    assert parsed["green"] is False
    assert parsed["exit_meaning"] == "no tests collected"
    report = format_report(parsed, root=Path("."))
    assert "not a green suite" in report.lower()


def test_parse_interrupt() -> None:
    parsed = parse_pytest(_INTERRUPTED, "", 2, 0.5)
    assert parsed["interrupted"] is True
    assert parsed["green"] is False
    assert parsed["passed"] == 5
    report = format_report(parsed, root=Path("."))
    assert "interrupted" in report.lower()


def test_empty_output_unknown_exit_is_not_green() -> None:
    parsed = parse_pytest("", "boom", 3, 0.01)
    assert parsed["green"] is False
    assert parsed["exit_meaning"] == "internal error"
    report = format_report(parsed, root=Path("."))
    assert "internal error" in report.lower()


@pytest.mark.asyncio
async def test_tool_locks_argv_and_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = list(cmd)  # type: ignore[arg-type]
        seen["cwd"] = kwargs.get("cwd")
        seen["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0, stdout=_GREEN, stderr="")  # type: ignore[arg-type]

    monkeypatch.setattr("arelis.tools.diagnostics.subprocess.run", fake_run)
    result = await DiagnosticsTool().run()
    assert result.ok
    cmd = seen["cmd"]
    assert isinstance(cmd, list)
    assert cmd[0] == sys.executable
    assert cmd[1:3] == ["-m", "pytest"]
    assert Path(str(cmd[3])).resolve() == (PROJECT_ROOT / "tests").resolve()
    assert tuple(cmd[4:]) == PYTEST_FLAGS
    assert seen["cwd"] == str(PROJECT_ROOT)
    env = seen["env"]
    assert isinstance(env, dict)
    assert env.get("ARELIS_IN_DIAGNOSTICS") == "1"
    assert result.data["green"] is True


@pytest.mark.asyncio
async def test_tool_summarises_a_red_run(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args[0], 1, stdout=_RED, stderr="")

    monkeypatch.setattr("arelis.tools.diagnostics.subprocess.run", fake_run)
    result = await DiagnosticsTool().run()
    assert result.ok
    assert result.data["failed"] == 1
    assert "tests/test_sms.py::test_send" in result.output
    assert "1 failed" in result.output
    assert "the suite is green" not in result.output.lower()


@pytest.mark.asyncio
async def test_missing_pytest_is_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args[0],
            1,
            stdout="",
            stderr="No module named pytest",
        )

    monkeypatch.setattr("arelis.tools.diagnostics.subprocess.run", fake_run)
    result = await DiagnosticsTool().run()
    assert not result.ok
    assert "pytest" in result.output.lower()


@pytest.mark.asyncio
async def test_timeout_is_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=600)

    monkeypatch.setattr("arelis.tools.diagnostics.subprocess.run", fake_run)
    result = await DiagnosticsTool().run()
    assert not result.ok
    assert "timed out" in result.output.lower()
    assert "invent" in result.output.lower()


@pytest.mark.asyncio
async def test_missing_tests_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("arelis.tools.diagnostics.PROJECT_ROOT", tmp_path)
    result = await DiagnosticsTool().run()
    assert not result.ok
    assert "tests/" in result.output


@pytest.mark.asyncio
async def test_refuses_to_nest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARELIS_IN_DIAGNOSTICS", "1")
    called = {"n": 0}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        called["n"] += 1
        return subprocess.CompletedProcess(args[0], 0, stdout=_GREEN, stderr="")

    monkeypatch.setattr("arelis.tools.diagnostics.subprocess.run", fake_run)
    result = await DiagnosticsTool().run()
    assert not result.ok
    assert "nest" in result.output.lower()
    assert called["n"] == 0


def test_diagnostics_is_registered(tmp_path: Path) -> None:
    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    registry = build_tool_registry({"tools": {}, "agent": {}}, workspace)
    assert registry.get("diagnostics") is not None
    assert not registry.needs_confirm("diagnostics", {})


def test_success_counts_as_diagnostics_evidence() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "diagnostics",
        ok=True,
        output="10 passed",
        data={"summary": "10 passed"},
    )
    assert ledger.has_ok("diagnostics")


@pytest.mark.parametrize(
    "text",
    (
        "run diagnostics",
        "hey arelis, run diagnostics",
        "please run diagnostics",
        "Run Diagnostics now",
    ),
)
def test_phrases_are_diagnostics_asks(text: str) -> None:
    assert detect_diagnostics_ask(text)
    need = detect_exactness_need(text)
    assert need.needs_diagnostics
    assert "diagnostics" in need.kinds


@pytest.mark.parametrize(
    "text",
    (
        "run your tests",
        "run the tests",
        "self-test",
        "health check",
        "how does pytest work",
        "write a test for this function",
        "what's the weather",
        "run diagnostic imaging",
        "car diagnostics",
        "I ran diagnostics yesterday",
        "please run diagnostic",
        "run diagnostics on my car",
        "run diagnostics on the fridge",
        "don't run diagnostics",
        "do not run diagnostics",
        "never run diagnostics",
    ),
)
def test_other_wording_is_not_diagnostics(text: str) -> None:
    assert not detect_diagnostics_ask(text)
    assert not detect_exactness_need(text).needs_diagnostics


def test_skill_card_only_on_run_diagnostics() -> None:
    tools = {"diagnostics", "calculator", "send_sms"}
    assert "diagnostics" in select_skill_ids(
        "run diagnostics", available_tools=tools
    )
    assert "diagnostics" not in select_skill_ids(
        "health check", available_tools=tools
    )
    assert "diagnostics" not in select_skill_ids(
        "run your tests", available_tools=tools
    )
    assert "sms" not in select_skill_ids(
        "run diagnostics", available_tools=tools
    )


def test_skill_subset_offers_diagnostics_only_on_that_ask() -> None:
    available = set(ALWAYS_ON_TOOLS) | {"diagnostics", "send_sms", "weather"}
    on = filter_tool_names(
        available,
        role="fast",
        text="run diagnostics",
        enabled=True,
        skill_subset=True,
    )
    assert "diagnostics" in on
    assert "send_sms" not in on
    off = filter_tool_names(
        available,
        role="fast",
        text="what's the weather today?",
        enabled=True,
        skill_subset=True,
    )
    assert "diagnostics" not in off
    assert "diagnostics" not in select_skill_ids(
        "run diagnostics on my car",
        available_tools={"diagnostics", "calculator", "send_sms"},
    )


def test_last_summary_line_wins() -> None:
    blob = """\
===== 10 passed in 0.10s =====
FAILED tests/test_late.py::test_it - assert 0
===== 1 failed, 9 passed in 0.20s =====
"""
    parsed = parse_pytest(blob, "", 1, 0.2)
    assert parsed["failed"] == 1
    assert parsed["passed"] == 9
    assert parsed["green"] is False


def test_counts_can_live_on_stderr() -> None:
    parsed = parse_pytest("", "===== 2 failed, 1 passed in 0.05s =====\n", 1, 0.05)
    assert parsed["failed"] == 2
    assert parsed["passed"] == 1
    assert parsed["green"] is False


def test_xfailed_and_warnings_are_not_failures() -> None:
    blob = "===== 3 passed, 1 xfailed, 2 warnings in 0.30s =====\n"
    parsed = parse_pytest(blob, "", 0, 0.3)
    assert parsed["passed"] == 3
    assert parsed["xfailed"] == 1
    assert parsed["warnings"] == 2
    assert parsed["failed"] == 0
    assert parsed["green"] is True
    report = format_report(parsed, root=Path("."))
    assert "the suite is green" in report.lower()
    assert "warning" in report.lower()


def test_failed_run_is_not_ok_evidence() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "diagnostics",
        ok=False,
        output="pytest is not installed",
        data={},
    )
    assert not ledger.has_ok("diagnostics")


def test_shipped_surface_hides_diagnostics_unless_asked() -> None:
    available = set(ALWAYS_ON_TOOLS) | {"diagnostics", "send_sms", "weather"}
    hello = filter_tool_names(
        available,
        role="fast",
        text="hello",
        enabled=False,
        skill_subset=False,
    )
    assert "diagnostics" not in hello
    asked = filter_tool_names(
        available,
        role="fast",
        text="run diagnostics",
        enabled=False,
        skill_subset=False,
    )
    assert "diagnostics" in asked
    car = filter_tool_names(
        available,
        role="fast",
        text="run diagnostics on my car",
        enabled=False,
        skill_subset=False,
    )
    assert "diagnostics" not in car


@pytest.mark.asyncio
async def test_suite_argument_cannot_narrow_the_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_run(cmd: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["cmd"] = list(cmd)  # type: ignore[arg-type]
        return subprocess.CompletedProcess(cmd, 0, stdout=_GREEN, stderr="")  # type: ignore[arg-type]

    monkeypatch.setattr("arelis.tools.diagnostics.subprocess.run", fake_run)
    result = await DiagnosticsTool().run(suite="unit")
    assert result.ok
    cmd = seen["cmd"]
    assert isinstance(cmd, list)
    assert "unit" not in cmd
    assert "-k" not in cmd
    assert tuple(cmd[4:]) == PYTEST_FLAGS


@pytest.mark.asyncio
async def test_missing_python_is_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("python")

    monkeypatch.setattr("arelis.tools.diagnostics.subprocess.run", fake_run)
    result = await DiagnosticsTool().run()
    assert not result.ok
    assert "python" in result.output.lower()


@pytest.mark.asyncio
async def test_oserror_is_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("permission denied")

    monkeypatch.setattr("arelis.tools.diagnostics.subprocess.run", fake_run)
    result = await DiagnosticsTool().run()
    assert not result.ok
    assert "permission denied" in result.output.lower()
