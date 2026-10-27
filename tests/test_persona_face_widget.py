"""Persona panel states, pacing, and the baked face. Offscreen only."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtGui import QImage


def _panel(qt_app, **kwargs):
    from arelis.ui.persona_face import PersonaPanel

    panel = PersonaPanel()
    panel.set_bake_delay(60.0)
    panel.resize(160, 220)
    for key, value in kwargs.items():
        getattr(panel, key)(value)
    return panel


def _pump(qt_app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qt_app.processEvents()
        time.sleep(0.01)


def test_frame_pacing_follows_the_state(qt_app):
    """Orb, calm face, speaking, thinking, and a busy model each pick their interval."""
    from arelis.ui.persona_face.motion import frame_interval_ms

    assert frame_interval_ms(form="orb", state="rest", model_busy=False, transitioning=False) == 100
    assert frame_interval_ms(form="face", state="rest", model_busy=False, transitioning=False) == 50
    assert (
        frame_interval_ms(form="face", state="speaking", model_busy=False, transitioning=False)
        == 33
    )
    assert (
        frame_interval_ms(form="face", state="thinking", model_busy=False, transitioning=False)
        == 100
    )
    assert frame_interval_ms(form="face", state="rest", model_busy=True, transitioning=False) == 100
    assert frame_interval_ms(form="face", state="rest", model_busy=False, transitioning=True) == 33

    panel = _panel(qt_app)
    panel.show()
    qt_app.processEvents()
    assert panel.timer_running()
    assert panel.timer_interval() == 100

    clock = {"t": 0.0}
    panel.set_clock(lambda: clock["t"])
    panel.set_state("thinking")
    from arelis.ui.persona_face.panel import BLOOM_S

    clock["t"] = BLOOM_S + 0.05
    panel.tick()
    assert panel.timer_interval() == 100

    panel.set_speaking(True)
    panel.tick()
    assert panel.timer_interval() == 33

    panel.set_speaking(False)
    panel.set_model_busy(True)
    panel.set_state("rest")
    clock["t"] = 1.4
    panel.tick()
    assert panel.timer_interval() == 100
    panel.close()


def _image_rgba(image: QImage) -> np.ndarray:
    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = converted.width()
    height = converted.height()
    raw = converted.bits()
    # bits() is a memoryview of the frame, including row padding. Copy before
    # `converted` goes out of scope: with no row padding the slice is already
    # contiguous, so without the copy the array would point at freed pixels.
    buf = np.asarray(raw).reshape(height, converted.bytesPerLine())
    return buf[:, : width * 4].copy().reshape(height, width, 4)


def test_motion_off_in_settings_skips_the_fade(qt_app, monkeypatch, tmp_path):
    """ui.motion=false shows her at full strength, no 2.6 s fade (issue 427)."""
    import arelis.ui.motion as motion_mod

    cfg = tmp_path / "config.local.yaml"
    cfg.write_text("ui:\n  motion: false\n", encoding="utf-8")
    monkeypatch.delenv("ARELIS_MOTION", raising=False)
    monkeypatch.setattr(motion_mod, "LOCAL_CONFIG_PATH", cfg)
    monkeypatch.setattr(motion_mod, "_windows_animations_enabled", lambda: True)
    panel = _panel(qt_app)
    try:
        panel.set_state("thinking")
        assert panel.avatar.reveal == 1.0
    finally:
        panel.deleteLater()
