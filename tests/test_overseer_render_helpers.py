"""The native boundary must propagate failures, not turn them into passes."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.overseer_render_helpers import isolated_render


@pytest.mark.parametrize("code,output", [(0, "1 skipped"), (-11, "crash"), (1, "1 failed")])
def test_isolated_render_propagates_native_and_assertion_failures(monkeypatch, code, output):
    monkeypatch.setitem(sys.modules, "coverage", None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=code, stdout=output, stderr=""),
    )
    with pytest.raises(AssertionError, match=output):
        isolated_render()(test_isolated_render_propagates_native_and_assertion_failures)()


def test_isolated_render_bounds_child_and_selects_software_only_when_requested(monkeypatch):
    monkeypatch.setitem(sys.modules, "coverage", None)
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return SimpleNamespace(returncode=0, stdout="1 passed", stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    isolated_render(software=True)(
        test_isolated_render_bounds_child_and_selects_software_only_when_requested
    )()
    cmd, opts = calls[0]
    assert cmd[:3] == [sys.executable, "-m", "pytest"]
    assert "-n0" in cmd
    assert opts["timeout"] == 60
    assert opts["env"]["QT_QUICK_BACKEND"] == "software"
    assert Path(opts["cwd"]).is_dir()


def test_isolated_render_timeout_is_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "coverage", None)

    def hang(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(subprocess.TimeoutExpired):
        isolated_render()(test_isolated_render_timeout_is_failure)()
