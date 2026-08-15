"""Camera instrument panel — no hardware required in CI."""

from __future__ import annotations

from arelis.ui.panels.camera import (
    CAMERA_MULTIMEDIA_AVAILABLE,
    CameraPanel,
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
