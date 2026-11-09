"""Exercise diagnostic persistence without weakening the isolated test verdict."""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.overseer_render_diagnostics import Diagnostics, diagnostic_output, run_child, sanitize


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


@pytest.mark.parametrize("mode", ["fatal", "python-fatal", "timeout"])
def test_diagnostics_survives_native_failure_and_predeadline_stack(tmp_path, mode):
    script = """
import sys,time
from pathlib import Path
from tests.overseer_render_diagnostics import Diagnostics
out=Diagnostics(Path(sys.argv[1]))
if sys.argv[2] == "timeout" and sys.platform != "win32":time.sleep(.7)
out.arm_trace(0.1)
out.record("before-failure")
if sys.argv[2] == "fatal":
 from PySide6.QtCore import qFatal
 out.install_messages()
 qFatal("QRhi context fatal token=HIDDEN /private/user/file")
elif sys.argv[2] == "python-fatal":
 import os
 os.abort()
else:
 if sys.platform != "win32":
  import ctypes
  libc=ctypes.PyDLL(None)
  while True:libc.sleep(20)  # Hold the GIL: parent/native signal still dumps.
 else:time.sleep(20)
"""
    env = dict(
        os.environ,
        ARELIS_OVERSEER_DIAGNOSTICS=str(tmp_path),
        ARELIS_OVERSEER_DEADLINE=str(time.monotonic() + 15.5),
    )
    if mode != "timeout":
        result = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path), mode],
            env=env,
            capture_output=True,
            timeout=5,
        )
        assert result.returncode != 0
    else:
        with pytest.raises(subprocess.TimeoutExpired):
            run_child(
                [sys.executable, "-c", script, str(tmp_path), mode],
                cwd=Path.cwd(),
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=1.5,
            )
    output = diagnostic_output(tmp_path)
    assert "before-failure" in output
    assert "HIDDEN" not in output and "/private/user" not in output
    assert "native.raw:" in output
    # Actual Windows Qt fatal delivery can terminate without calling Python's
    # fatal handler. Qt severity+nonzero/persistence is still mandatory; the
    # separate public Python os.abort route retains the stack-delivery contract.
    if mode != "fatal" or sys.platform != "win32":
        assert 'File "<string>"' in output
    if mode == "fatal":
        assert "QRhi context fatal" in output
        rows = [json.loads(line) for line in (tmp_path / "render.jsonl").read_text().splitlines()]
        assert any(row.get("event") == "qt" and row.get("kind") == "3" for row in rows)
    elif mode == "python-fatal":
        assert "Fatal Python error" in output
    else:
        assert "most recent call first" in output
        if sys.platform != "win32":
            parent = [
                json.loads(line) for line in (tmp_path / "parent.jsonl").read_text().splitlines()
            ]
            kinds = [row["event"] for row in parent]
            assert "snapshot-waiting-for-registration" in kinds
            assert (
                kinds.index("snapshot-ready-observed")
                < kinds.index("snapshot-sent")
                < kinds.index("child-timeout-killed")
            )
            assert next(row["seconds"] for row in parent if row["event"] == "snapshot-sent") < 1.5


def test_diagnostic_qt_handler_preserves_original_capture_and_severity(tmp_path):
    diag = Diagnostics(tmp_path)
    captured = []
    diag.previous = lambda *args: captured.append(args)
    context = SimpleNamespace(category="qt.rhi.general")
    original = "QRhi context token=HIDDEN"
    diag.message(3, context, original)
    assert captured == [(3, context, original)]
    assert "HIDDEN" not in (tmp_path / "render.jsonl").read_text()


def test_diagnostic_snapshot_does_not_replace_existing_native_exit_guard(tmp_path):
    script = """
import faulthandler,sys,time
from pathlib import Path
from tests.overseer_render_diagnostics import Diagnostics
faulthandler.dump_traceback_later(0.2, exit=True, file=sys.stderr)
Diagnostics(Path(sys.argv[1])).arm_trace(0.1)
time.sleep(20)
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, timeout=3
    )
    assert result.returncode == 1
    assert b"Timeout" in result.stderr


@pytest.mark.parametrize(
    "credential",
    [
        'token="DUMMY_SENSITIVE_VALUE"',
        "token='DUMMY_SENSITIVE_VALUE'",
        '{"token": "DUMMY_SENSITIVE_VALUE"}',
        "{'token': 'DUMMY_SENSITIVE_VALUE'}",
        "Authorization: Bearer DUMMY_SENSITIVE_VALUE",
        "Authorization: Basic DUMMY_SENSITIVE_VALUE",
        'authorization = bearer "DUMMY_SENSITIVE_VALUE"',
        "AUTHORIZATION: BASIC 'DUMMY_SENSITIVE_VALUE'",
        '{"Authorization": "Bearer DUMMY_SENSITIVE_VALUE"}',
        '{"api_key": "DUMMY_SENSITIVE_VALUE"}',
        "password = 'DUMMY_SENSITIVE_VALUE with spaces'",
        'client_secret="DUMMY_SENSITIVE_VALUE"',
        "access_token=DUMMY_SENSITIVE_VALUE",
        "Proxy-Authorization: Basic DUMMY_SENSITIVE_VALUE",
        'token="DUMMY_SENSITIVE_VALUE unterminated',
        'token="DUMMY_SENSITIVE_VALUE \\"quoted\\" tail"',
    ],
)
def test_credential_forms_never_persist_or_escape_diagnostics(tmp_path, credential):
    diag = Diagnostics(tmp_path)
    original = "QRhi " + credential
    captured = []
    diag.previous = lambda *args: captured.append(args)
    context = SimpleNamespace(category="qt.rhi.general")
    diag.message(1, context, original)
    diag.record("qt", message="QRhi OpenGL backend2 device Mesa")
    # Native trace text is sanitized at read time too, not merely record time.
    (tmp_path / "native.raw").write_text(original)
    persisted = (tmp_path / "render.jsonl").read_text()
    emitted = diagnostic_output(tmp_path)
    assert "DUMMY_SENSITIVE_VALUE" not in persisted
    assert "DUMMY_SENSITIVE_VALUE" not in emitted
    assert "<redacted>" in persisted and "<redacted>" in emitted
    assert "QRhi OpenGL backend2 device Mesa" in persisted
    assert "QRhi OpenGL backend2 device Mesa" in emitted
    assert captured == [(1, context, original)]
    for row in persisted.splitlines():
        json.loads(row)


_SWAPCHAIN_DUMMY = (
    "Failed to create D3D11 swapchain: COM error 0x81234567: Access is denied. "
    "(Width=1280 Height=800 Format=28 SampleCount=1 BufferCount=2 "
    "Scaling=1 SwapEffect=4 Stereo=0)"
)
_HRESULT_CASES = {
    "valid-code": (_SWAPCHAIN_DUMMY, 0x81234567),
    "uint32-max": (_SWAPCHAIN_DUMMY.replace("0x81234567", "0xFFFFFFFF"), 0xFFFFFFFF),
    "uint32-zero": (_SWAPCHAIN_DUMMY.replace("0x81234567", "0x00000000"), 0),
    "second-size-mixed-hex": (
        _SWAPCHAIN_DUMMY.replace("1280", "900")
        .replace("800", "700")
        .replace("0x81234567", "0xabcDEF12"),
        0xABCDEF12,
    ),
    "generic-address": ("QRhi object at 0x81234567", None),
    "prefix": ("QRhi forwarded: " + _SWAPCHAIN_DUMMY, None),
    "suffix-address": (_SWAPCHAIN_DUMMY + " at 0x81234567", None),
    "newline": (_SWAPCHAIN_DUMMY + "\n", None),
    "missing-descriptor": (_SWAPCHAIN_DUMMY.split(" (", 1)[0], None),
    "uint32-overflow": (_SWAPCHAIN_DUMMY.replace("0x81234567", "0x181234567"), None),
    "short-code": (_SWAPCHAIN_DUMMY.replace("0x81234567", "0x1234567"), None),
    "nonhex-code": (_SWAPCHAIN_DUMMY.replace("0x81234567", "0xZZZZZZZZ"), None),
    "negative-descriptor": (_SWAPCHAIN_DUMMY.replace("Width=1280", "Width=-1280"), None),
    "overflow-descriptor": (_SWAPCHAIN_DUMMY.replace("Width=1280", "Width=4294967296"), None),
    "nonboolean-stereo": (_SWAPCHAIN_DUMMY.replace("Stereo=0", "Stereo=2"), None),
    "reordered-descriptor": (
        _SWAPCHAIN_DUMMY.replace("Width=1280 Height=800", "Height=800 Width=1280"),
        None,
    ),
    "quoted-credential": ('QRhi token="' + _SWAPCHAIN_DUMMY + '"', None),
    "json-credential": (json.dumps({"token": _SWAPCHAIN_DUMMY}), None),
    "credential-prefix": ('QRhi token="DUMMY_HRESULT_SECRET" ' + _SWAPCHAIN_DUMMY, None),
    "bearer-suffix": (_SWAPCHAIN_DUMMY + " Authorization: Bearer DUMMY_HRESULT_SECRET", None),
    "credential-descriptor": (
        _SWAPCHAIN_DUMMY.replace("Width=1280", 'Width=token="DUMMY_HRESULT_SECRET"'),
        None,
    ),
    "credential-reason": (
        _SWAPCHAIN_DUMMY.replace("Access is denied.", 'token="DUMMY_HRESULT_SECRET"'),
        None,
    ),
}


@pytest.mark.parametrize("message, expected", _HRESULT_CASES.values(), ids=_HRESULT_CASES)
def test_only_complete_swapchain_descriptor_preserves_structured_uint32(
    tmp_path, message, expected
):
    diag = Diagnostics(tmp_path)
    captured = []
    diag.previous = lambda *args: captured.append(args)
    context = SimpleNamespace(category="default")
    diag.message(3, context, message)
    persisted = (tmp_path / "render.jsonl").read_text()
    row = json.loads(persisted)
    output = diagnostic_output(tmp_path)
    assert captured == [(3, context, message)]
    assert row["kind"] == "3" and row["category"] == "default"
    assert row["message"] == sanitize(message[:4096])
    assert not re.search(r"0x[0-9a-fA-F]+", persisted + output)
    assert "DUMMY_HRESULT_SECRET" not in persisted and "DUMMY_HRESULT_SECRET" not in output
    if expected is None:
        assert "hresult_u32" not in row and '"hresult_u32"' not in output
    else:
        assert type(row["hresult_u32"]) is int
        assert row["hresult_u32"] == expected
        assert 0 <= row["hresult_u32"] <= 0xFFFFFFFF
        assert f'"hresult_u32": {expected}' in output


@pytest.mark.parametrize("mode", ["return", "fatal", "exception"])
def test_checkpoint_is_flushed_before_call_and_only_marks_normal_return(tmp_path, mode):
    script = """
import sys
from contextlib import nullcontext
from pathlib import Path
from PySide6.QtCore import qFatal
from PySide6.QtWidgets import QApplication
from PySide6.QtQuick import QQuickView
from tests import overseer_render_diagnostics as d
app=QApplication([])
d._diagnostics=d.Diagnostics(Path(sys.argv[1]))
d._diagnostics.arm_trace()
d._diagnostics.install_messages()
view=QQuickView()
d._diagnostics.observe(view)
checkpoint=getattr(d, 'checkpoint', lambda *args: nullcontext())
try:
 with checkpoint(view, 'open-pump'):
  if sys.argv[2]=='fatal':qFatal('QRhi token="DUMMY_CHECKPOINT_SECRET"')
  if sys.argv[2]=='exception':raise RuntimeError('original sentinel')
except RuntimeError as exc:
 assert str(exc)=='original sentinel'
 if sys.argv[2]!='exception':raise
if sys.argv[2]=='return':
 from shiboken6 import delete
 delete(view)
 with checkpoint(view, 'delete-pump'):pass
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path), mode], capture_output=True, timeout=5
    )
    assert (result.returncode != 0) == (mode == "fatal")
    rows = [json.loads(line) for line in (tmp_path / "render.jsonl").read_text().splitlines()]
    checkpoints = [row for row in rows if row["event"] == "checkpoint"]
    entered = [row for row in checkpoints if row["phase"] == "open-pump"]
    assert [row["edge"] for row in entered] == (
        ["enter", "return"] if mode == "return" else ["enter"]
    )
    assert all(row["view"] == 1 and row["valid"] and row["owner_thread"] for row in entered)
    assert all(type(row["visible"]) is bool and type(row["exposed"]) is bool for row in entered)
    if mode == "return":
        deleted = [row for row in checkpoints if row["phase"] == "delete-pump"]
        assert len(deleted) == 2 and all(row["valid"] is False for row in deleted)
    assert "DUMMY_CHECKPOINT_SECRET" not in diagnostic_output(tmp_path)
    assert (tmp_path / "render.jsonl").stat().st_size <= 256 * 1024


def test_view_milestones_are_passive_view_owned_and_do_not_create_handles(qt_app, tmp_path):
    import gc

    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QPlatformSurfaceEvent
    from PySide6.QtQuick import QQuickView

    view = QQuickView()
    diag = Diagnostics(tmp_path)
    diag.observe(view)
    assert hasattr(view, "_overseer_diagnostic_events"), "missing passive view milestones"
    observer = view._overseer_diagnostic_events
    assert observer.parent() is view
    gc.collect()
    # Direct filter delivery exercises metadata only: never synthesize native
    # surface destruction into Qt's real window event handler.
    events = [
        QEvent(kind)
        for kind in (
            QEvent.Type.Show,
            QEvent.Type.Hide,
            QEvent.Type.Close,
            QEvent.Type.Expose,
            QEvent.Type.DeferredDelete,
        )
    ]
    # PySide exposes only the copy constructor; model the two public event
    # accessors rather than injecting a fake native surface into Qt.
    events += [
        SimpleNamespace(
            type=lambda: QEvent.Type.PlatformSurface, surfaceEventType=lambda kind=kind: kind
        )
        for kind in (
            QPlatformSurfaceEvent.SurfaceEventType.SurfaceCreated,
            QPlatformSurfaceEvent.SurfaceEventType.SurfaceAboutToBeDestroyed,
        )
    ]
    for event in events:
        assert observer.eventFilter(view, event) is False
    assert observer.eventFilter(view, QEvent(QEvent.Type.User)) is False
    rows = [json.loads(line) for line in (tmp_path / "render.jsonl").read_text().splitlines()]
    milestones = [row for row in rows if row["event"] == "view-event"]
    assert [row["phase"] for row in milestones] == [
        "show",
        "hide",
        "close",
        "expose",
        "deferred-delete",
        "surface-created",
        "surface-about-to-destroy",
    ]
    assert all(row["view"] == 1 and row["owner_thread"] for row in milestones)
    # Scope guard: neither observer nor checkpoint may create native handles or
    # change lifecycle/render state. The Qt callbacks never pump or consume.
    import ast
    import inspect

    source = inspect.getsource(Diagnostics)
    calls = {
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not calls & {"winId", "create", "processEvents", "sendPostedEvents", "close"}
    view.deleteLater()
