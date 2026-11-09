"""A stalled Sentinel backend must not stall the desktop event loop."""
from __future__ import annotations

import threading

from PySide6.QtCore import QThread, QTimer

from arelis import sentinel_control
from arelis.ui import overseer_runtime
from arelis.ui.sentinel_host import SentinelWindow


def test_snapshot_wait_is_bounded_to_one_worker_and_gui_keeps_running(qtbot, monkeypatch):
    win = SentinelWindow()
    qtbot.addWidget(win)
    started, release = threading.Event(), threading.Event()
    calls = []
    applied = []

    def fetch(*_args):
        calls.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        return {"units": []}

    monkeypatch.setattr(sentinel_control, "bridge_target", lambda: ("127.0.0.1", 9, "test"))
    monkeypatch.setattr(overseer_runtime, "fetch_snapshot", fetch)
    monkeypatch.setattr(win, "apply_snapshot", lambda body: applied.append((body, QThread.currentThread())))
    try:
        win._poll_snapshot()
        assert started.wait(1)
        for _ in range(10):
            win._poll_snapshot()
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        qtbot.waitUntil(lambda: bool(ticks))
        assert len(calls) == 1
        assert calls[0] != threading.get_ident()
        assert applied == []
        release.set()
        qtbot.waitUntil(lambda: bool(applied))
        assert applied == [({"units": []}, win.thread())]
        assert not win._io_pending
    finally:
        release.set()


def test_restart_removes_old_session_token_before_spawning(tmp_path, monkeypatch):
    token_file = tmp_path / "data" / "session_token"
    token_file.parent.mkdir()
    token_file.write_text("old-session-token")
    monkeypatch.setattr(sentinel_control, "_runtime_root", lambda: tmp_path)
    monkeypatch.setattr(sentinel_control, "_sentinel_root", lambda: tmp_path)
    monkeypatch.setattr(sentinel_control, "headless_argv", lambda: ["test-child"])
    monkeypatch.setattr(sentinel_control, "_process", None)
    monkeypatch.setattr(sentinel_control, "_stopped", False)
    seen = []

    def spawn(*_args, **_kwargs):
        seen.append(token_file.exists())
        raise OSError("test spawn stops here")

    monkeypatch.setattr(sentinel_control, "_spawn", spawn)
    sentinel_control.start()
    assert seen == [False]
