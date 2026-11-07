"""Exercise diagnostic persistence without weakening the isolated test verdict."""

import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tests.overseer_render_diagnostics import Diagnostics, diagnostic_output, sanitize


def test_diagnostics_only_persists_sanitized_bounded_metadata(tmp_path):
    diag = Diagnostics(tmp_path)
    diag.record(
        "qt",
        message="QRhi /private/user/key.txt C:\\Users\\name\\file.py token=HIDDEN https://host/?key=HIDDEN",
    )
    data = json.loads((tmp_path / "render.jsonl").read_text())
    assert data["event"] == "qt"
    assert all(secret not in data["message"] for secret in ("HIDDEN", "private", "Users", "host"))
    for _ in range(100):
        diag.record("qt", message="x" * 10000)
    assert (tmp_path / "render.jsonl").stat().st_size <= 256 * 1024
    assert (
        sanitize("secret=HIDDEN password=HIDDEN api_key=HIDDEN")
        == "secret=<redacted> password=<redacted> api_key=<redacted>"
    )


@pytest.mark.parametrize("mode", ["fatal", "timeout"])
def test_diagnostics_survives_native_failure_and_predeadline_stack(tmp_path, mode):
    script = """
import sys,time
from pathlib import Path
from PySide6.QtCore import qFatal
from tests.overseer_render_diagnostics import Diagnostics
out=Diagnostics(Path(sys.argv[1]));out.arm_trace(0.1);out.install_messages()
out.record("before-failure")
if sys.argv[2] == "fatal":qFatal("QRhi context fatal token=HIDDEN /private/user/file")
else:time.sleep(20)
"""
    env = dict(os.environ)
    if mode == "fatal":
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), mode],
            env=env,
            capture_output=True,
            timeout=5,
        )
        assert result.returncode != 0
    else:
        with pytest.raises(subprocess.TimeoutExpired):
            subprocess.run(
                [sys.executable, "-c", script, str(tmp_path), mode],
                env=env,
                capture_output=True,
                timeout=1,
            )
    output = diagnostic_output(tmp_path)
    assert "before-failure" in output
    assert "HIDDEN" not in output and "/private/user" not in output
    assert "native.raw:" in output
    assert 'File "<string>"' in output
    if mode == "fatal":
        assert "QRhi context fatal" in output
    else:
        assert "Timeout" in output


def test_diagnostic_qt_handler_preserves_original_capture_and_severity(tmp_path):
    diag = Diagnostics(tmp_path)
    captured = []
    diag.previous = lambda *args: captured.append(args)
    context = SimpleNamespace(category="qt.rhi.general")
    original = "QRhi context token=HIDDEN"
    diag.message(3, context, original)
    assert captured == [(3, context, original)]
    assert "HIDDEN" not in (tmp_path / "render.jsonl").read_text()
