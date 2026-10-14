"""A script that printed the number is a computed warrant, same as python."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.core.claims import ExactnessNeed
from arelis.core.evidence import EvidenceLedger
from arelis.core.loop_helpers import _exactness_finish_refuse
from arelis.tools.run_script import RunScriptTool

_MATH = ExactnessNeed(True, False, False, False, kinds=("math",))
_ANSWER = "The output is 144."


def _refuse(ledger: EvidenceLedger) -> str | None:
    return _exactness_finish_refuse(
        _ANSWER,
        exact_need=_MATH,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
    )


def test_run_script_stdout_counts_as_a_computed_warrant() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "run_script",
        ok=True,
        output="exit: 0\n\nstdout:\n144",
        data={"exit": 0, "stdout": "144"},
    )
    assert ledger.has_ok("calc")
    assert _refuse(ledger) is None


def test_a_failed_script_is_not_a_computed_warrant() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "run_script",
        ok=False,
        output="exit: 1\n\nstderr:\nboom",
        data={"exit": 1, "stdout": ""},
    )
    assert not ledger.has_ok("calc")
    assert _refuse(ledger) is not None


def test_an_empty_stdout_is_not_a_computed_warrant() -> None:
    ledger = EvidenceLedger()
    ledger.record_tool(
        "run_script",
        ok=True,
        output="exit: 0\n\n(no output, print the result, or write a file I can read)",
        data={"exit": 0, "stdout": ""},
    )
    assert not ledger.has_ok("calc")
    assert _refuse(ledger) is not None


@pytest.mark.asyncio
async def test_a_real_script_print_satisfies_the_math_gate(tmp_path: Path) -> None:
    script = tmp_path / "sq2.py"
    script.write_text("print(12 * 12)\n", encoding="utf-8")
    result = await RunScriptTool([str(tmp_path)]).run(path="sq2.py")
    assert result.ok, result.output
    ledger = EvidenceLedger()
    ledger.record_tool(
        "run_script",
        ok=result.ok,
        output=result.output,
        data=result.data,
    )
    assert "144" in " ".join(item.span for item in ledger.items if item.ok)
    assert _refuse(ledger) is None


@pytest.mark.asyncio
async def test_stored_stdout_matches_the_python_warrant_cap(tmp_path: Path) -> None:
    script = tmp_path / "wide.py"
    script.write_text("print('x' * 500)\n", encoding="utf-8")
    result = await RunScriptTool([str(tmp_path)]).run(path="wide.py")
    assert result.ok, result.output
    assert result.data["stdout"] == "x" * 200
    ledger = EvidenceLedger()
    ledger.record_tool(
        "run_script",
        ok=result.ok,
        output=result.output,
        data=result.data,
    )
    spans = [item.span for item in ledger.items if item.ok and item.kind == "calc"]
    assert spans == ["x" * 200]
    assert ledger.has_ok("calc")
