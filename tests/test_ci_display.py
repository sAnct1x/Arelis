"""Linux display provisioning must not change the existing CI command contract."""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import ci_pytest
from scripts.ci_pytest import command, finish

ROOT = Path(__file__).resolve().parents[1]


def _step(mode):
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    return next(
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == ("Pytest serial" if mode == "serial" else "Pytest")
    )


def _run(tmp_path, mode, runner, code=0, missing=None):
    assert os.name == "posix", "POSIX shell fixture must not execute on a Windows host"
    shell = shutil.which("bash")
    assert shell is not None, "POSIX CI execution proof requires existing bash"
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
    step = _step(mode)
    env = dict(
        os.environ, PATH=str(binary), RUNNER_OS=runner, COMMAND_LOG=str(log), FAKE_EXIT=str(code)
    )
    result = subprocess.run(
        [shell, "-e", "-c", re.sub(r"\$\{\{[^}]+\}\}", "contract-fixture", step["run"])],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )
    rows = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, rows


@pytest.mark.skipif(
    "os.name != 'posix'",
    reason="POSIX-only Bash execution proof; portable non-Linux contracts run separately",
)
@pytest.mark.parametrize("mode", ["xdist", "serial"])
@pytest.mark.parametrize("code", [0, 1, 5])
def test_linux_display_executes_preserved_command_flags_and_exit(tmp_path, mode, code):
    runner = "Linux"
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


@pytest.mark.skipif(
    "os.name != 'posix'",
    reason="POSIX-only missing-tool execution proof; no other platform tests skipped",
)
@pytest.mark.parametrize("mode", ["xdist", "serial"])
@pytest.mark.parametrize("missing", ["xvfb-run", "Xvfb"])
def test_ci_display_fails_closed_before_pytest_when_tool_missing(tmp_path, mode, missing):
    result, rows = _run(tmp_path, mode, "Linux", missing=missing)
    assert result.returncode == 2
    assert missing in result.stderr and "execution environment" in result.stderr
    assert rows == []


@pytest.mark.parametrize("mode", ["xdist", "serial"])
@pytest.mark.parametrize("runner", ["Windows", "macOS"])
@pytest.mark.parametrize("code", [0, 1, 5])
def test_nonlinux_command_contract_needs_no_posix_host(tmp_path, monkeypatch, mode, runner, code):
    # This is host-portable Python/YAML contract coverage, not an OS/rendering
    # execution claim. Any accidental Bash lookup/launch fails this test.
    def forbidden(*args, **kwargs):
        raise AssertionError("portable command contract attempted POSIX fixture execution")

    monkeypatch.setattr(shutil, "which", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setenv("RUNNER_OS", runner)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    (tmp_path / "ci-tier-paths.txt").write_text(
        "tests/test_sentinel_overseer_camera.py\n", encoding="utf-8"
    )
    calls = []
    monkeypatch.setattr(ci_pytest.subprocess, "call", lambda argv: calls.append(argv) or code)
    branch = _step(mode)["run"].split("\nelse\n", 1)[1].rsplit("\nfi", 1)[0].strip()
    assert branch == f"python scripts/ci_pytest.py {mode}"
    flags = (
        ["-n", "auto", "-m", "not serial", "--junitxml=pytest-results.xml"]
        if mode == "xdist"
        else ["-m", "serial", "--junitxml=pytest-results-serial.xml"]
    )
    assert ci_pytest.main([mode]) == (0 if mode == "serial" and code == 5 else code)
    assert calls == [
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--tb=short",
            *flags,
            "tests/test_sentinel_overseer_camera.py",
        ]
    ]


def test_linux_test_runtime_provisions_exact_missing_xcb_providers():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    step = next(
        s
        for s in workflow["jobs"]["test"]["steps"]
        if s.get("name") == "Install Qt offscreen libraries"
    )
    assert step["if"] == "runner.os == 'Linux' && steps.tier.outputs.tier != 'docs'"
    assert shlex.split(step["run"].replace("\\\n", " ")) == [
        "sudo",
        "apt-get",
        "update",
        "sudo",
        "apt-get",
        "install",
        "-y",
        "libegl1",
        "libxkbcommon-x11-0",
        "libdbus-1-3",
        "libxcb-cursor0",
        "libxcb-icccm4",
        "libxcb-util1",
        "libxcb-image0",
        "libxcb-keysyms1",
        "libxcb-render-util0",
        "libxcb-shape0",
    ]
