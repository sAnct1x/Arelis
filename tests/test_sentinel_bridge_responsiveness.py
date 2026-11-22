"""A stalled Sentinel backend must not stall the desktop event loop."""
from __future__ import annotations

import threading
import weakref

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


def test_window_dropped_mid_request_is_freed_on_the_gui_thread(qtbot, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def fetch(*_args):
        started.set()
        assert release.wait(5)
        return {"units": []}

    monkeypatch.setattr(sentinel_control, "bridge_target", lambda: ("127.0.0.1", 9, "test"))
    monkeypatch.setattr(overseer_runtime, "fetch_snapshot", fetch)
    win = SentinelWindow()
    win._poll_snapshot()
    assert started.wait(1)
    worker = next(t for t in threading.enumerate() if t.name == "sentinel-snapshot")
    freed_on = []
    weakref.finalize(win, lambda: freed_on.append(threading.get_ident()))
    del win
    release.set()
    worker.join(5)
    # A window freed on the worker thread cannot stop its timers; they then fire into freed memory.
    qtbot.waitUntil(lambda: bool(freed_on))
    assert freed_on == [threading.get_ident()]


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


def test_unchanged_selection_does_not_reselect_on_every_snapshot_poll(qtbot) -> None:
    """Re-calling selectUnit on every 80 ms poll aborts camera ease mode."""
    win = SentinelWindow()
    qtbot.addWidget(win)
    select_calls: list[str] = []

    class _FakeRoot:
        def __init__(self) -> None:
            self._props: dict[str, object] = {
                "selectedUnitId": "SNT-WRD-001",
                "cameraDistance": overseer_runtime.DEFAULT_CAMERA_DISTANCE,
                "cameraTargetX": 0.0,
                "cameraTargetY": -6.0,
                "cameraTargetZ": -3.0,
                "swarmGroupBy": "caste",
                "swarmSearch": "",
                "collapsedGroups": [],
                "logFilter": "all",
                "logQuery": "",
                "logRepeats": True,
            }

        def property(self, name: str):
            return self._props.get(name)

        def setProperty(self, name: str, value) -> None:
            self._props[name] = value

        def findChildren(self, *_args):
            return []

        def applyFrame(self, _payload) -> None:
            return

        def applyHud(self, _hud) -> None:
            return

        def selectUnit(self, unit_id: str) -> None:
            select_calls.append(unit_id)
            self._props["selectedUnitId"] = unit_id

    root = _FakeRoot()
    win._scene = type("Scene", (), {"rootObject": lambda _self: root})()
    snap = {
        "units": [
            {"unit_id": "SNT-WRD-001", "caste": "warden", "state": "PATROLLING"},
        ],
        "nodes": [],
    }
    win.apply_snapshot(snap)
    win.apply_snapshot(snap)
    assert select_calls == []


def test_native_scene_does_not_start_web_overlay_mask_timer(qtbot, monkeypatch) -> None:
    """_mask_timer only serves the legacy QWebEngineView fallback."""
    win = SentinelWindow()
    qtbot.addWidget(win)
    fake_scene = type("Scene", (), {"rootObject": lambda _self: None})()
    monkeypatch.setattr(win, "_ensure_scene", lambda: fake_scene)
    monkeypatch.setattr(sentinel_control, "overseer_url", lambda: None)
    win.start_entry_sequence()
    assert not win._mask_timer.isActive()
    win._entry_timer.stop()


def test_hud_counts_skip_redundant_label_writes_when_unchanged(qtbot) -> None:
    """Identical unit counts on successive polls must not churn hidden QLabels."""
    win = SentinelWindow()
    qtbot.addWidget(win)
    units = [{"unit_id": "SNT-WRD-001", "caste": "warden", "state": "PATROLLING"}]
    win.apply_hud_counts(units)
    assert win._hud_labels["warden"].text() == "Warden 1"
    writes = 0
    orig = win._hud_labels["warden"].setText

    def counting_set_text(text: str) -> None:
        nonlocal writes
        writes += 1
        orig(text)

    win._hud_labels["warden"].setText = counting_set_text  # type: ignore[method-assign]
    win.apply_hud_counts(units)
    assert writes == 0
    win.apply_hud_counts([*units, {"unit_id": "SNT-WRD-002", "caste": "warden", "state": "PATROLLING"}])
    assert writes == 1
    assert win._hud_labels["warden"].text() == "Warden 2"
