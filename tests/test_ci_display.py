"""Linux display provisioning must not change the existing CI command contract."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.ci_pytest import command, finish

ROOT = Path(__file__).resolve().parents[1]


def _run(tmp_path, mode, runner, code=0, missing=None):
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "commands.jsonl"
    script = (
        f"#!{sys.executable}\n"
        + """import json,os,sys
from pathlib import Path
with open(os.environ['COMMAND_LOG'],'a') as f:f.write(json.dumps([Path(sys.argv[0]).name,*sys.argv[1:]])+'\\n')
if Path(sys.argv[0]).name=='xvfb-run':os.execvp(sys.argv[2],sys.argv[2:])
raise SystemExit(int(os.environ['FAKE_EXIT']))
"""
    )
    for name in ["python", "xvfb-run", "Xvfb"]:
        if name != missing:
            path = binary / name
            path.write_text(script)
            path.chmod(0o755)
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    step = next(
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == ("Pytest serial" if mode == "serial" else "Pytest")
    )
    env = dict(
        os.environ, PATH=str(binary), RUNNER_OS=runner, COMMAND_LOG=str(log), FAKE_EXIT=str(code)
    )
    result = subprocess.run(
        ["/bin/bash", "-e", "-c", re.sub(r"\$\{\{[^}]+\}\}", "contract-fixture", step["run"])],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    rows = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, rows


@pytest.mark.parametrize("mode", ["xdist", "serial"])
@pytest.mark.parametrize("runner", ["Linux", "Windows", "macOS"])
@pytest.mark.parametrize("code", [0, 1, 5])
def test_ci_display_preserves_platform_command_flags_and_exit(tmp_path, mode, runner, code):
    result, rows = _run(tmp_path, mode, runner, code)
    original = ["python", "scripts/ci_pytest.py", mode]
    assert rows == ([["xvfb-run", "-a", *original], original] if runner == "Linux" else [original])
    # In particular, an outer xvfb-run5 must not be mistaken for pytest's
    # existing serial-empty5 -> success rule inside ci_pytest.py.
    assert result.returncode == code
    flags = (
        ["-n", "auto", "-m", "not serial", "--junitxml=pytest-results.xml"]
        if mode == "xdist"
        else ["-m", "serial", "--junitxml=pytest-results-serial.xml"]
    )
    coverage = (
        [
            "--cov=arelis",
            "--cov-branch",
            *(["--cov-append"] if mode == "serial" else []),
            "--cov-report=term-missing",
        ]
        if runner == "Linux"
        else []
    )
    assert command(
        mode, coverage=runner == "Linux", paths=["tests/test_sentinel_overseer_camera.py"]
    ) == [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        *flags,
        *coverage,
        "tests/test_sentinel_overseer_camera.py",
    ]
    assert finish(mode, code) == (0 if mode == "serial" and code == 5 else code)


@pytest.mark.parametrize("mode", ["xdist", "serial"])
@pytest.mark.parametrize("missing", ["xvfb-run", "Xvfb"])
def test_ci_display_fails_closed_before_pytest_when_tool_missing(tmp_path, mode, missing):
    result, rows = _run(tmp_path, mode, "Linux", missing=missing)
    assert result.returncode == 2
    assert missing in result.stderr and "execution environment" in result.stderr
    assert rows == []
