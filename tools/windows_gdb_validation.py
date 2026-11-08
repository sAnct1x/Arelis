"""Opt-in sacrificial hosted-Windows proof; NEVER invoked by HUD tests/CI by default."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

MAX_THREADS = 16
MAX_FRAMES = 12
MAX_BYTES = 262144
WALL_SECONDS = 24
MODULES = {"Qt6Core.dll", "Qt6Gui.dll", "Qt6Quick.dll", "python314.dll", "ntdll.dll"}
SYMBOLS = {
    "QEventLoop::exec",
    "QCoreApplication::exec",
    "QGuiApplication::exec",
    "QCoreApplication::processEvents",
    "QQuickWindow::event",
    "QQuickWindow::mousePressEvent",
    "QQuickWindow::mouseReleaseEvent",
    "QSGRenderThread::run",
    "QSGRenderThread::syncAndRender",
    "QSGRenderThread::waitForEvent",
    "QSGThreadedRenderLoop::polishAndSync",
    "QThread::exec",
    "QWaitCondition::wait",
    "QWindowsGuiEventDispatcher::processEvents",
    "QEventDispatcherWin32::processEvents",
    "QRhiD3D11::beginFrame",
}


class ProofError(Exception):
    """No external error text is persisted or printed."""


def value(text, key):
    match = re.search(r"(?:^|[,{}])" + re.escape(key) + r'="((?:\\.|[^"\\])*)"', text)
    if not match:
        raise ProofError
    try:
        return json.loads('"' + match[1] + '"')
    except (ValueError, TypeError) as exc:
        raise ProofError from exc


def frames(text):
    # Parse only bounded frame records; never echo unknown fields, args or error text.
    records = re.findall(r"frame=\{([^{}]*)\}", text)
    if not records or len(records) > MAX_FRAMES or text.count("frame=") != len(records):
        raise ProofError
    result = []
    for record in records:
        symbol = value(record, "func")
        item = {"symbol": symbol if symbol in SYMBOLS else "unresolved"}
        try:
            module = value(record, "from").replace("\\", "/").rsplit("/", 1)[-1]
        except ProofError:
            module = ""
        if module in MODULES:
            item["module"] = module
        result.append(item)
    return result


def native_thread(text):
    target = value(text, "target-id")
    match = re.fullmatch(r"Thread (0x[0-9a-fA-F]+|[0-9]+)\.(0x[0-9a-fA-F]+|[0-9]+)", target)
    if not match:
        raise ProofError
    return int(match[2], 16 if match[2].startswith("0x") else 10)


class BoundedPipe:
    def __init__(self, stream):
        self.lines = queue.Queue(maxsize=512)
        self.failed = threading.Event()
        threading.Thread(target=self._read, args=(stream,), daemon=True).start()

    def _read(self, stream):
        size = 0
        line = bytearray()
        try:
            while data := stream.read(1):
                size += 1
                if size > MAX_BYTES or len(line) >= 8192:
                    raise ProofError
                line.extend(data)
                if data == b"\n":
                    self.lines.put_nowait(line.decode("utf-8", errors="strict").strip())
                    line.clear()
            raise ProofError
        except (ProofError, UnicodeError, OSError, queue.Full):
            self.failed.set()

    def take(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or (self.failed.is_set() and self.lines.empty()):
            raise ProofError
        try:
            return self.lines.get(timeout=remaining)
        except queue.Empty as exc:
            raise ProofError from exc


class Debugger:
    def __init__(self, executable, deadline):
        self.deadline = deadline
        self.token = 0
        self.version = None
        self.executable = executable
        self.process = None
        self.output = None

    def start(self):
        # Caller owns this object BEFORE spawn; retain process even if pipe startup fails.
        self.process = subprocess.Popen(
            [
                self.executable,
                "-nx",
                "-nh",
                "--quiet",
                "--interpreter=mi2",
                "-iex",
                "set auto-load off",
                "-iex",
                "set debuginfod enabled off",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self.output = BoundedPipe(self.process.stdout)

    def command(self, command, deadline=None):
        self.token += 1
        token = str(self.token)
        self.process.stdin.write((token + command + "\n").encode("ascii"))
        self.process.stdin.flush()
        while True:
            line = self.output.take(self.deadline if deadline is None else deadline)
            if re.search(r"GNU gdb \(GDB\) 17\.1(?:\\n| )", line):
                self.version = "17.1"
            if line.startswith(token + "^done"):
                return line
            if line.startswith(token + "^error"):
                raise ProofError
            # Async/stream records remain transient, bounded, and NEVER logged.

    def detach(self, deadline):
        self.command("-target-detach", deadline)
        remaining = self.command("-thread-info", deadline)
        if not re.search(r"(?:^|,)threads=\[\](?:,|$)", remaining):
            raise ProofError


def collect(debugger, state):
    listing = debugger.command("-thread-list-ids")
    ids = re.findall(r'thread-id="([0-9]+)"', listing)
    if not ids or len(ids) > MAX_THREADS or len(ids) != len(set(ids)):
        raise ProofError
    captured = {}
    for thread in ids:
        info = debugger.command("-thread-info " + thread)
        tid = native_thread(info)
        role = "gui" if tid == state["gui"] else "render" if tid == state["render"] else None
        if role:
            stack = frames(
                debugger.command(f"-stack-list-frames --thread {thread} 0 {MAX_FRAMES - 1}")
            )
            captured[role] = stack
    if set(captured) != {"gui", "render"}:
        raise ProofError
    if any(
        not any(frame["symbol"].startswith("Q") for frame in stack) for stack in captured.values()
    ):
        raise ProofError
    return captured


def state_from(pipe, deadline):
    try:
        state = json.loads(pipe.take(deadline))
    except ValueError as exc:
        raise ProofError from exc
    if not isinstance(state, dict):
        raise ProofError
    if set(state) != {"gui", "render", "gtick", "rtick", "ack"}:
        raise ProofError
    if any(type(v) is not int or v < 0 or v > 2**63 - 1 for v in state.values()):
        raise ProofError
    return state


def sacrificial_child():
    # Ordinary child scene only, NOT a native-handle probe or the failing HUD.
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    app = QGuiApplication([])
    engine = QQmlApplicationEngine()
    engine.loadData(b"""import QtQuick
import QtQuick.Window
Window { width: 80; height: 80; visible: false
 Rectangle { width: 20; height: 20; color: "red"
 NumberAnimation on rotation { from: 0; to: 360; duration: 1000; loops: -1 } }
}""")
    window = engine.rootObjects()[0]
    state = {"gui": threading.get_native_id(), "render": 0, "gtick": 0, "rtick": 0, "ack": 0}
    stop = threading.Event()
    resume = threading.Event()
    rendered_after_resume = threading.Event()

    def rendered():
        state["render"] = threading.get_native_id()
        state["rtick"] += 1
        if resume.is_set():
            rendered_after_resume.set()

    def tick():
        state["gtick"] += 1
        if rendered_after_resume.is_set():
            state["ack"] = 1
        print(json.dumps(state), flush=True)
        if stop.is_set():
            window.close()
            app.quit()

    def read_stop():
        for command in iter(lambda: sys.stdin.buffer.readline(16), b""):
            if command == b"resume\n":
                resume.set()
            elif command == b"quit\n":
                stop.set()
                return

    window.beforeRendering.connect(rendered, Qt.ConnectionType.DirectConnection)
    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(100)
    threading.Thread(target=read_stop, daemon=True).start()
    QTimer.singleShot(28000, app.quit)
    window.show()
    return app.exec()


def stop_owned(process):
    """Independent, sanitized best-effort cleanup; never assert exit after wait failure."""
    if process is None:
        return "not_started", False
    try:
        if process.poll() is not None:
            return "exited", False
    except Exception:
        pass
    try:
        process.kill()
    except Exception:
        pass  # A kill failure must not prevent wait or the OTHER owned cleanup.
    try:
        process.wait(timeout=1)
        return ("exited" if process.poll() is not None else "unconfirmed"), True
    except Exception:
        return "unconfirmed", True


def validate():
    report = {
        "status": "failed",
        "attached": False,
        "detached": False,
        "resumed": False,
        "normal_exit": False,
        "frames": {},
        "phase": "preflight",
        "cleanup": {"debugger": "not_started", "child": "not_started"},
    }
    # No platform impersonation option. Standard privilege attempt permitted ONLY here.
    if (
        sys.platform != "win32"
        or os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_OS") != "Windows"
    ):
        return report
    # Standalone does not import conftest: require its EXACT existing defaults,
    # supplied by the proposed step, rather than silently using Windows QPA.
    if (os.environ.get("QT_QPA_PLATFORM"), os.environ.get("QT_QUICK_BACKEND")) != (
        "offscreen",
        "rhi",
    ):
        return report
    executable = shutil.which("gdb")
    if not executable:
        return report
    started = time.monotonic()
    deadline = started + WALL_SECONDS
    child = None
    debugger = None
    try:
        child = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--child"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        report["phase"] = "child_ready"
        output = BoundedPipe(child.stdout)
        state = state_from(output, deadline)
        while not state["render"] or state["render"] == state["gui"]:
            state = state_from(output, deadline)
        report["phase"] = "attach"
        debugger = Debugger(executable, deadline)
        debugger.start()
        debugger.command("-gdb-set auto-load off")
        debugger.command("-gdb-set debuginfod enabled off")
        debugger.command("-gdb-set print frame-arguments none")
        debugger.command("-gdb-set print entry-values no")
        debugger.command("-gdb-version")
        if debugger.version != "17.1":
            raise ProofError
        debugger.command(f"-target-attach {child.pid}")
        report["attached"] = True
        report["phase"] = "unwind"
        try:
            report["frames"] = collect(debugger, state)
        finally:
            debugger.detach(time.monotonic() + 2)
            report["detached"] = True
        # Ack can only be produced by BOTH render and GUI AFTER this post-detach request.
        report["phase"] = "resume"
        child.stdin.write(b"resume\n")
        child.stdin.flush()
        final = state_from(output, deadline)
        while final["ack"] != 1:
            final = state_from(output, deadline)
        report["resumed"] = final["gtick"] > state["gtick"] and final["rtick"] > state["rtick"]
        child.stdin.write(b"quit\n")
        child.stdin.flush()
        report["phase"] = "exit"
        child.wait(timeout=max(0.01, deadline - time.monotonic()))
        report["normal_exit"] = child.returncode == 0
        if report["detached"] and report["resumed"] and report["normal_exit"]:
            report["status"] = "passed"
    except Exception:
        pass  # Explicit FAILED proof, never a successful test verdict.
    finally:
        try:
            if debugger is not None and not report["detached"]:
                try:
                    debugger.detach(time.monotonic() + 2)
                    report["detached"] = True
                except Exception:
                    pass
        finally:
            # Neither debugger cleanup nor a partial start may abandon the child.
            try:
                process = debugger.process if debugger is not None else None
                report["cleanup"]["debugger"], _ = stop_owned(process)
            finally:
                report["cleanup"]["child"], forced = stop_owned(child)
                if forced or "unconfirmed" in report["cleanup"].values():
                    report["status"] = "failed"
    report["elapsed_ms"] = min(999999, int((time.monotonic() - started) * 1000))
    return report


if __name__ == "__main__":
    if sys.argv[1:] == ["--child"] and sys.platform == "win32":
        sys.exit(sacrificial_child())
    if sys.argv[1:] != ["--hosted-windows-proof"]:
        sys.exit(2)
    try:
        result = validate()
    except BaseException:
        # No unexpected exception/debugger text may escape to persistent job logs.
        result = {"status": "failed", "phase": "internal_error"}
    print(json.dumps(result, sort_keys=True))
    sys.exit(0 if result["status"] == "passed" else 1)
