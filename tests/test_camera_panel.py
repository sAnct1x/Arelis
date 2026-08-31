"""Camera instrument panel — no hardware required in CI."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QCoreApplication

from arelis.ui.panels.camera import (
    CAMERA_MULTIMEDIA_AVAILABLE,
    CameraPanel,
    PreviewConvertWorker,
    list_video_input_names,
)


def test_list_video_input_names_returns_list() -> None:
    names = list_video_input_names()
    assert isinstance(names, list)
    assert all(isinstance(n, str) for n in names)


def test_camera_panel_constructs_without_hardware(qt_app) -> None:
    panel = CameraPanel()
    assert panel.device_combo.count() >= 1
    assert panel.ask_btn.text().lower().startswith("ask")
    assert panel.track_btn.isHidden()
    panel.set_spatial_available(True)
    assert not panel.track_btn.isHidden()
    assert not panel.reach_slider.isHidden()
    panel.set_spatial_available(False)
    assert panel.track_btn.isHidden()
    assert panel.reach_slider.isHidden()
    # Safe to call stop when never started.
    panel.stop()
    # Snapshot without a live camera must not crash.
    panel.snapshot()
    if not CAMERA_MULTIMEDIA_AVAILABLE or not list_video_input_names():
        problem = panel.problem()
        assert problem is not None
        panel.ask()
        assert panel._ask_after_next_save is False
    panel.close()


def test_camera_ask_flag_clears_when_start_fails(qt_app, monkeypatch) -> None:
    panel = CameraPanel()
    monkeypatch.setattr(panel, "start", lambda: None)
    monkeypatch.setattr(panel, "snapshot", lambda: None)
    panel._running = False
    panel.ask()
    assert panel._ask_after_next_save is False
    panel.close()


def test_preview_worker_emits_image(qt_app, monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.ui.panels.camera.video_frame_to_rgb",
        lambda _frame, _max_width: (np.zeros((8, 8, 3), dtype=np.uint8), 8, 8),
    )
    worker = PreviewConvertWorker()
    got: list = []
    worker.frame_ready.connect(got.append)
    worker.start()
    worker.submit(object())
    deadline = time.perf_counter() + 2.0
    while not got and time.perf_counter() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.02)
    worker.stop_worker()
    worker.wait(1500)
    assert got
    assert not got[0].isNull()
