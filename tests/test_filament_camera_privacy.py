"""Filament never opens the webcam on its own. Hands (which uses it) starts off every launch,
even if it was on last time, and turning Hands off closes the camera."""

from __future__ import annotations

from PySide6.QtTest import QTest

FILAMENT = {"default_width": 1400, "default_height": 900, "theme": "filament", "filament_ack": True}


def _spy_camera(monkeypatch) -> list[str]:
    from arelis.ui.panels import camera as cam

    opened: list[str] = []

    def start(self, *_a, **_k) -> None:
        opened.append("start")
        self._running = True

    monkeypatch.setattr(cam.CameraPanel, "start", start)
    monkeypatch.setattr(cam, "QCamera", lambda *_a, **_k: opened.append("QCamera"))
    monkeypatch.setattr(cam, "QMediaCaptureSession", lambda *_a: opened.append("session"))
    return opened


def test_startup_and_filament_layout_never_open_the_camera(arelis_window, monkeypatch) -> None:
    opened = _spy_camera(monkeypatch)
    # Hands was on in an earlier run (the old saved ui.hands_chip).
    w = arelis_window({"ui": {**FILAMENT, "hands_chip": True}})
    w.show()
    QTest.qWait(1500)
    w.filament._filament_set_chat_open(True)
    QTest.qWait(300)
    assert opened == []
    assert not w.spatial.tracking


def test_turning_hands_off_in_filament_closes_the_camera(arelis_window, monkeypatch) -> None:
    opened = _spy_camera(monkeypatch)
    w = arelis_window({"ui": dict(FILAMENT)})
    w.show()
    QTest.qWait(500)
    w._on_hands_chip(True)
    assert opened == ["start"] and w.spatial.tracking
    w._on_hands_chip(False)
    assert not w.camera._running and not w.spatial.tracking
