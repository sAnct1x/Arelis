"""Placement-only contracts; NOT PowerShell, debugger, or hosted runtime proof."""

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tools import windows_gdb_outer as outer


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
    assert "github.event_name == 'push'" in step["if"]
    assert "github.ref == 'refs/heads/sentinel/pr6-overseer'" in step["if"]
    assert "vars." not in step["if"]
    assert "steps.tier.outputs.tier != 'docs'" in step["if"]
    assert step["timeout-minutes"] == 1 and step["shell"] == "pwsh"
    assert "continue-on-error" not in step
    assert step["env"] == {"QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "rhi"}
    script = step["run"]
    assert script.strip() == "python -m tools.windows_gdb_outer\nexit $LASTEXITCODE"
    outer = Path("tools/windows_gdb_outer.py").read_text()
    for required in (
        "process.wait(timeout=35)",
        "job.terminate()",
        "job.close()",
        "--job-gated",
        "child_proc._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE",
        "child_proc._windows_cell_python",
        "job.assign(process)",
        'process.stdin.write(b"go\\n")',
    ):
        assert required in outer
    assert "HasExited" not in script and "Get-Process" not in script
    assert "process.poll()" not in outer.replace("root.poll()", "root-status")
    assert [s["name"] for s in steps if s.get("name", "").startswith("Pytest")] == [
        "Pytest",
        "Pytest serial",
        "Pytest not required for this tier",
    ]


@pytest.mark.parametrize(
    "failure", ["root-unconfirmed", "root-clean", "root-timeout", "assign", "terminate"]
)
def test_job_ownership_survives_root_exit_and_unconfirmed_descendants(monkeypatch, failure):
    events = []

    class Job:
        def __init__(self):
            self.live = failure != "root-clean"

        def assign(self, _):
            events.append("assign")
            if failure == "assign":
                raise OSError("DUMMY_PRIVATE_JOB_ERROR")

        def empty(self):
            return not self.live

        def terminate(self):
            events.append("terminate-owned-job")
            if failure == "terminate":
                raise OSError("DUMMY_PRIVATE_JOB_ERROR")
            self.live = False

        def close(self):
            events.append("close-kill-on-close-job")
            self.live = False

    class Gate(io.BytesIO):
        def write(self, data):
            assert events == ["assign"]
            events.append("release-root")
            return super().write(data)

    class Process:
        stdin = Gate()

        def wait(self, timeout):
            if timeout == 35:
                events.append("root-exit-descendants-still-owned")
                if failure == "root-timeout":
                    raise outer.subprocess.TimeoutExpired("DUMMY_PRIVATE_JOB_ERROR", timeout)
                return 0 if failure == "root-clean" else 1
            assert timeout == 1
            events.append("unassigned-root-wait")

        def kill(self):
            events.append("unassigned-root-kill")

    process = Process()
    monkeypatch.setattr(outer.child_proc, "_windows_cell_python", lambda p, e: (p, e))
    monkeypatch.setattr(outer, "sys", SimpleNamespace(executable="existing-python"))

    def spawn(args, **kwargs):
        assert args[-1] == "--job-gated" and kwargs["stderr"] == outer.subprocess.DEVNULL
        return process

    result = outer.supervise(job_factory=Job, spawn=spawn)
    assert result["status"] == ("passed" if failure == "root-clean" else "failed")
    assert "terminate-owned-job" in events and "close-kill-on-close-job" in events
    assert "DUMMY_PRIVATE_JOB_ERROR" not in str(result)
    if failure == "assign":
        assert "release-root" not in events
        assert "unassigned-root-kill" in events
    else:
        assert events.index("root-exit-descendants-still-owned") < events.index(
            "terminate-owned-job"
        )
    assert result["owned_empty"] is (failure != "terminate")


@pytest.mark.parametrize("active", [0, 2])
def test_job_native_adapter_uses_only_private_job_boolean_accounting(monkeypatch, active):
    events = []

    def create(*_):
        return 9  # Dummy non-native handle; no WinAPI call.

    def configure(handle, kind, info, size):
        assert handle == 9 and kind == 9
        assert info._obj.BasicLimitInformation.LimitFlags == 0x2000
        return True

    def query(handle, kind, info, size, _):
        assert handle == 9 and kind == 1 and size == 48
        info._obj.counts[2] = active
        return True

    def terminate(handle, code):
        events.append("terminate")
        return True

    def close(handle):
        events.append("close")
        return True

    kernel = SimpleNamespace(
        CreateJobObjectW=create,
        SetInformationJobObject=configure,
        QueryInformationJobObject=query,
        TerminateJobObject=terminate,
        AssignProcessToJobObject=lambda *a: True,
        CloseHandle=close,
    )
    monkeypatch.setattr(outer.child_proc, "_kernel32", lambda: kernel)
    job = outer.OwnedJob()
    job.assign(SimpleNamespace(_handle=8))
    assert job.empty() is (active == 0)
    job.terminate()
    job.close()
    assert events == ["terminate", "close"]
