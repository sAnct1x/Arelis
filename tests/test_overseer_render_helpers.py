"""The native boundary must propagate failures, not turn them into passes."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.overseer_render_diagnostics import Diagnostics
from tests.overseer_render_helpers import isolated_render


@pytest.mark.parametrize("code,output", [(0, "1 skipped"), (-11, "crash"), (1, "1 failed")])
def test_isolated_render_propagates_native_and_assertion_failures(monkeypatch, code, output):
    monkeypatch.setitem(sys.modules, "coverage", None)

    def failed(*args, **kwargs):
        Diagnostics(Path(kwargs["env"]["ARELIS_OVERSEER_DIAGNOSTICS"])).record("before-fatal")
        return SimpleNamespace(returncode=code, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", failed)
    with pytest.raises(AssertionError, match=output) as error:
        isolated_render()(test_isolated_render_propagates_native_and_assertion_failures)()
    assert "before-fatal" in str(error.value)


def test_isolated_render_bounds_child_and_selects_software_only_when_requested(monkeypatch):
    monkeypatch.setitem(sys.modules, "coverage", None)
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("PYTEST_ADDOPTS", "-n8 -k never_matches")
    isolated_render(software=True)(
        test_isolated_render_bounds_child_and_selects_software_only_when_requested
    )()
    cmd, opts = calls[0]
    assert cmd[:3] == [sys.executable, "-m", "pytest"]
    assert not any(arg.startswith("-n") for arg in cmd)
    assert "tests.overseer_render_diagnostics" in cmd
    assert "PYTEST_ADDOPTS" not in opts["env"]
    assert opts["env"]["QSG_INFO"] == "1"
    assert opts["timeout"] == 60
    assert opts["env"]["QT_QUICK_BACKEND"] == "software"
    assert Path(opts["cwd"]).is_dir()


def test_isolated_render_timeout_is_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "coverage", None)

    def hang(cmd, **kwargs):
        directory = Path(kwargs["env"]["ARELIS_OVERSEER_DIAGNOSTICS"])
        Diagnostics(directory).record("before-timeout")
        (directory / "native.raw").write_text(
            'Thread 0x1234: File "/private/user/a.py", line 12 in stuck'
        )
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(subprocess.TimeoutExpired) as error:
        isolated_render()(test_isolated_render_timeout_is_failure)()
    assert error.value.timeout == 60
    notes = "".join(error.value.__notes__)
    assert "before-timeout" in notes and "in stuck" in notes
    assert "/private/user" not in notes and "0x1234" not in notes
