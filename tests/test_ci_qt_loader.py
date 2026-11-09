"""Read-only Linux loader metadata must not become a test gate."""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import ci_qt_loader as loader


def test_loader_workflow_is_linux_only_advisory_before_unchanged_tests():
    workflow = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
    steps = next(
        job["steps"]
        for job in workflow["jobs"].values()
        if any(step.get("name") == "Pytest" for step in job.get("steps", []))
    )
    diagnostic = next(step for step in steps if step.get("name") == "Qt xcb loader metadata")
    assert diagnostic["if"] == "runner.os == 'Linux' && steps.tier.outputs.tier != 'docs'"
    assert diagnostic["continue-on-error"] is True
    assert diagnostic["timeout-minutes"] == 1
    assert diagnostic["run"] == "python -m scripts.ci_qt_loader"
    assert steps.index(next(s for s in steps if s.get("name") == "Install package")) < steps.index(
        diagnostic
    )
    assert steps.index(diagnostic) < steps.index(
        next(s for s in steps if s.get("name") == "Pytest")
    )


@pytest.mark.parametrize("outcome", ["ok", "nonzero", "timeout", "missing", "oserror", "truncated"])
def test_tool_metadata_is_bounded_sanitized_and_preserves_failure(monkeypatch, outcome):
    monkeypatch.setattr(
        loader.shutil, "which", lambda name: None if outcome == "missing" else "/tool/ldd"
    )

    def run(command, **kwargs):
        assert command == ["/tool/ldd", "/private/install/libqxcb.so"]
        assert kwargs["timeout"] == 10
        assert kwargs["check"] is False
        assert kwargs["stderr"] == subprocess.STDOUT
        payload = b"libxcb-cursor.so.0 => not found\nQRhi Authorization: Bearer DUMMY_AUTH_SENTINEL\n/private/DUMMY_PATH_SENTINEL\n"
        if outcome == "truncated":
            payload += b"x" * loader.LIMIT
        kwargs["stdout"].write(payload)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 10)
        if outcome == "oserror":
            raise OSError("DUMMY_ERROR_SENTINEL")
        return SimpleNamespace(returncode=1 if outcome == "nonzero" else 0)

    monkeypatch.setattr(loader.subprocess, "run", run)
    record = loader.inspect_tool("ldd", ["/private/install/libqxcb.so"])
    rendered = json.dumps(record)
    for secret in ("DUMMY_AUTH_SENTINEL", "DUMMY_PATH_SENTINEL", "DUMMY_ERROR_SENTINEL"):
        assert secret not in rendered
    assert len(rendered) < loader.LIMIT + 300
    if outcome == "missing":
        assert record == {"status": "tool-missing"}
        return
    assert "libxcb-cursor.so.0 => not found" in record["output"]
    assert record["truncated"] is (outcome == "truncated")
    if outcome in ("ok", "nonzero", "truncated"):
        assert record["status"] == "completed"
        assert record["returncode"] == (1 if outcome == "nonzero" else 0)
    else:
        assert record["status"] == ("timeout" if outcome == "timeout" else "unavailable")
        assert "returncode" not in record


@pytest.mark.parametrize("state", ["present", "missing", "api-error"])
def test_report_resolves_installed_qt_api_and_only_whitelisted_packages(
    monkeypatch, tmp_path, capsys, state
):
    marker = object()

    def path(kind):
        assert kind is marker
        if state == "api-error":
            raise RuntimeError("DUMMY_IMPORT_SECRET")
        return str(tmp_path)

    info = SimpleNamespace(path=path, LibraryPath=SimpleNamespace(PluginsPath=marker))
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", SimpleNamespace(QLibraryInfo=info))
    plugin = tmp_path / "platforms" / "libqxcb.so"
    if state == "present":
        plugin.parent.mkdir()
        plugin.touch()
    calls = []

    def inspect(name, args):
        calls.append((name, args))
        return {"status": "tool-missing"}

    monkeypatch.setattr(loader, "inspect_tool", inspect)
    assert loader.main() == 0
    output = capsys.readouterr().out
    assert str(tmp_path) not in output
    assert "DUMMY_IMPORT_SECRET" not in output
    report = json.loads(output)
    if state == "present":
        assert calls[0] == ("ldd", [str(plugin)])
        assert report["ldd"] == {"status": "tool-missing"}
    else:
        assert len(calls) == 1
        assert "ldd" not in report
        assert report["plugin"] == (
            "Qt-API-unavailable"
            if state == "api-error"
            else "missing-at-Qt-PluginsPath/platforms/libqxcb.so"
        )
    name, args = calls[-1]
    assert name == "dpkg-query"
    assert args[:2] == ["-W", "-f=${binary:Package}\t${db:Status-Status}\t${Version}\n"]
    assert args[2:] == [
        "libxcb-cursor0",
        "libxcb-icccm4",
        "libxcb-util1",
        "libxcb-image0",
        "libxcb-keysyms1",
        "libxcb-randr0",
        "libxcb-render-util0",
        "libxcb-shm0",
        "libxcb-sync1",
        "libxcb-xfixes0",
        "libxcb-render0",
        "libxcb-shape0",
        "libxcb-xkb1",
        "libxcb1",
        "libxkbcommon0",
        "libxkbcommon-x11-0",
        "libx11-xcb1",
        "libx11-6",
        "libgl1",
        "libegl1",
        "libdbus-1-3",
    ]
