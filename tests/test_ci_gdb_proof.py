"""Placement-only contracts; NOT PowerShell, debugger, or hosted runtime proof."""

from pathlib import Path

import yaml


def test_hosted_proof_is_opt_in_last_windows_step_with_owned_bounded_cleanup():
    workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["test"]["steps"]
    step = next(s for s in steps if s.get("id") == "gdb_sacrificial_proof")
    assert steps[-1] is step
    assert (
        next(i for i, s in enumerate(steps) if s.get("name") == "Install package") < len(steps) - 1
    )
    assert "!cancelled()" in step["if"]
    assert "runner.os == 'Windows'" in step["if"]
    assert "vars.SENTINEL_GDB_PROOF == 'true'" in step["if"]
    assert "steps.tier.outputs.tier != 'docs'" in step["if"]
    assert step["timeout-minutes"] == 1 and step["shell"] == "pwsh"
    assert "continue-on-error" not in step
    assert step["env"] == {"QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "rhi"}
    script = step["run"]
    for required in (
        "tools/windows_gdb_validation.py",
        "--hosted-windows-proof",
        ".WaitForExit(35000)",
        ".WaitForExit(2000)",
        ".Kill($true)",
        "[System.IO.Stream]::Null",
        "$exitCode = 1",
        "exit $exitCode",
    ):
        assert required in script
    assert ".RedirectStandardError = $true" in script
    assert ".RedirectStandardOutput = $false" in script
    for forbidden in (
        "Write-Error",
        "$_",
        "Get-Process",
        "taskkill",
        "Stop-Process",
        "RedirectStandardError = $false",
        "pip install",
        "workflow_dispatch",
        "continue-on-error",
        "Out-File",
    ):
        assert forbidden not in script
    assert [s["name"] for s in steps if s.get("name", "").startswith("Pytest")] == [
        "Pytest",
        "Pytest serial",
        "Pytest not required for this tier",
    ]
