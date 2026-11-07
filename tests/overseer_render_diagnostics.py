"""Child-only, bounded metadata diagnostics; never change rendering or verdicts.

Raw faulthandler output is transient/private (filenames and stack locations only,
no locals/memory/C stacks). The parent sanitizes it before reporting, including
on TimeoutExpired, then the existing temporary directory is removed.
"""

from __future__ import annotations

import faulthandler
import json
import os
import re
import sys
import threading
import time
import weakref
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_DIRECTORY = "ARELIS_OVERSEER_DIAGNOSTICS"
_LIMIT = 256 * 1024
_ENV = (
    "DISPLAY",
    "QT_QPA_PLATFORM",
    "QT_QUICK_BACKEND",
    "QSG_RHI_BACKEND",
    "QSG_RENDER_LOOP",
    "QSG_INFO",
)


def sanitize(text: str) -> str:
    text = text.replace(str(_ROOT), "<repo>").replace(str(_ROOT).replace("\\", "/"), "<repo>")
    text = re.sub(
        r"(?i)(password|token|secret|authorization|cookie|api[_-]?key)\s*[:=]\s*[^\s,;\"\\]+",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(r"https?://[^\s]+", "<url>", text)
    text = re.sub(r"[A-Za-z]:[\\/][^\s\"'<>]+|(?<![\w<>:])/(?!/)[^\s\"'<>]+", "<path>", text)
    text = re.sub(r"0x[0-9a-fA-F]+", "<address>", text)
    return "".join(c for c in text if c in "\n\t" or ord(c) >= 32)[:_LIMIT]


def diagnostic_output(directory: Path) -> str:
    """Only sanitized, size-bounded diagnostic data leaves the private tempdir."""
    parts = []
    for name in ("render.jsonl", "native.raw"):
        path = directory / name
        if path.exists():
            with path.open("rb") as source:
                text = source.read(_LIMIT).decode("utf-8", errors="replace")
            parts.append(f"{name}:\n{sanitize(text)}")
    return "\nRender diagnostics (native C stack unavailable; no memory dump):\n" + "\n".join(parts)


class Diagnostics:
    def __init__(self, directory: Path):
        self.directory = directory
        self.lock = threading.RLock()
        self.size = 0
        self.started = time.monotonic()
        self.previous = None
        self.trace = None
        self.views = 0

    def record(self, event: str, **data):
        def clean(value):
            if isinstance(value, dict):
                return {key: clean(part) for key, part in value.items()}
            return (
                sanitize(str(value))
                if not isinstance(value, (int, float, bool, type(None)))
                else value
            )

        line = (
            json.dumps(
                clean(
                    {"event": event, "seconds": round(time.monotonic() - self.started, 6), **data}
                )
            )
            + "\n"
        )
        with self.lock:
            if self.size + len(line.encode()) <= _LIMIT:
                with (self.directory / "render.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(line)
                    stream.flush()
                self.size += len(line.encode())

    def arm_trace(self, seconds: float = 45):
        # A native watchdog, independent of the GIL/event loop, before the
        # parent's unchanged60s limit. Never exit/turn a failure into a pass.
        if sys.platform != "win32":
            import resource

            resource.setrlimit(
                resource.RLIMIT_CORE, (0, resource.getrlimit(resource.RLIMIT_CORE)[1])
            )
        self.trace = (self.directory / "native.raw").open("wb")
        options = {"c_stack": False} if sys.version_info >= (3, 14) else {}
        faulthandler.enable(file=self.trace, all_threads=True, **options)
        faulthandler.dump_traceback_later(seconds, file=self.trace, repeat=False, exit=False)
        self.record(
            "watchdog-armed", delay_seconds=seconds, native_c_stack="unavailable; not collected"
        )

    def install_messages(self):
        from PySide6.QtCore import qInstallMessageHandler

        previous = qInstallMessageHandler(self.message)
        if previous != self.message:
            self.previous = previous

    def message(self, kind, context, text):
        category = context.category or "default"
        graphics = category.startswith(("qt.scenegraph", "qt.rhi", "qt.quick3d", "qt.qpa"))
        graphics = graphics or bool(
            re.search(
                r"QRhi|OpenGL|Direct3D|D3D|Vulkan|Metal|render loop|graphics backend|context|MSAA|texture atlas",
                text,
            )
        )
        self.record(
            "qt",
            kind=str(kind),
            category=category,
            message=text[:4096] if graphics else "<non-graphics message redacted>",
        )
        # Preserve pytest-qt's original warning/fatal assertions and capture.
        if self.previous is not None:
            self.previous(kind, context, text)

    def observe(self, view):
        from PySide6.QtCore import Qt, QThread
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtQuick import QQuickView

        ref = weakref.ref(view)
        self.views += 1
        identity = self.views  # Child-local sequence, never a memory address.

        def record(event, **data):
            self.record(event, view=identity, thread=QThread.currentThread().objectName(), **data)

        def initialized():
            window = ref()
            record("scenegraph-initialized", api=str(window.rendererInterface().graphicsApi()))

        root_seen = False

        def status_changed(status):
            nonlocal root_seen
            record("view-status", status=str(status))
            window = ref()
            if status == QQuickView.Status.Ready and not root_seen:
                root = window.rootObject()
                if root is not None:
                    root_seen = True
                    root.destroyed.connect(lambda: record("root-destroyed"))

        view.statusChanged.connect(status_changed)
        view.sceneGraphInitialized.connect(initialized, Qt.ConnectionType.DirectConnection)
        view.sceneGraphInvalidated.connect(
            lambda: record("scenegraph-invalidated"), Qt.ConnectionType.DirectConnection
        )
        view.destroyed.connect(lambda: record("view-destroyed"))
        view.engine().destroyed.connect(lambda: record("engine-destroyed"))
        record(
            "view-created",
            qpa=QGuiApplication.platformName(),
            api=str(view.rendererInterface().graphicsApi()),
        )


_diagnostics = None


@pytest.hookimpl(trylast=True)
def pytest_sessionstart(session):
    global _diagnostics
    directory = os.environ.get(_DIRECTORY)
    if directory is None:
        return
    from PySide6.QtCore import qVersion
    from PySide6.QtQuick import QQuickView

    _diagnostics = Diagnostics(Path(directory))
    allowed = {
        "QT_QPA_PLATFORM": {"offscreen", "xcb", "windows", "cocoa", "minimal", "wayland", "eglfs"},
        "QT_QUICK_BACKEND": {"rhi", "software"},
        "QSG_RHI_BACKEND": {"opengl", "d3d11", "d3d12", "vulkan", "metal", "null"},
        "QSG_RENDER_LOOP": {"threaded", "basic", "windows"},
        "QSG_INFO": {"0", "1"},
    }
    values = {}
    for key in _ENV:
        value = os.environ.get(key)
        valid = (
            bool(re.fullmatch(r"(?:localhost)?:[0-9]+(?:\.[0-9]+)?", value or ""))
            if key == "DISPLAY"
            else value in allowed[key]
        )
        values[key] = value if value is None or valid else "<set; unrecognized/redacted>"
    _diagnostics.record(
        "session-start",
        environment=values,
        python=sys.version.split()[0],
        platform=sys.platform,
        qt=qVersion(),
    )
    deadline = float(os.environ["ARELIS_OVERSEER_DEADLINE"])
    _diagnostics.arm_trace(max(0.001, deadline - time.monotonic() - 15))
    _diagnostics.install_messages()
    original = QQuickView.__init__

    def observed(view, *args, **kwargs):
        _diagnostics.install_messages()
        original(view, *args, **kwargs)
        _diagnostics.observe(view)

    QQuickView.__init__ = observed


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_setup(item):
    if _diagnostics:
        _diagnostics.record("setup-begin", node=item.nodeid)
    yield
    if _diagnostics:
        _diagnostics.record("setup-end")


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_call(item):
    if _diagnostics:
        _diagnostics.install_messages()
        _diagnostics.record("call-begin", node=item.nodeid)
    yield
    if _diagnostics:
        _diagnostics.record("call-end")


@pytest.hookimpl(hookwrapper=True, trylast=True)
def pytest_runtest_teardown(item):
    if _diagnostics:
        _diagnostics.install_messages()
        _diagnostics.record("teardown-begin")
    yield
    if _diagnostics:
        _diagnostics.record("teardown-end")


def pytest_runtest_logreport(report):
    if _diagnostics:
        _diagnostics.record("report", phase=report.when, outcome=report.outcome)


def pytest_sessionfinish(session, exitstatus):
    if _diagnostics:
        _diagnostics.record("session-finish", exitstatus=exitstatus)
        faulthandler.cancel_dump_traceback_later()
        # Keep fatal handling and signal observations alive through Qt shutdown.


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    if _diagnostics and _diagnostics.trace:
        # pytest's faulthandler plugin restores its old destination here. Keep
        # our private stack-only destination alive through interpreter shutdown.
        options = {"c_stack": False} if sys.version_info >= (3, 14) else {}
        faulthandler.enable(file=_diagnostics.trace, all_threads=True, **options)
