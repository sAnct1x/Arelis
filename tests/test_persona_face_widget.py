"""Persona panel states, pacing, and the baked face. Offscreen only."""

from __future__ import annotations

import threading
import time

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget


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
        == 83
    )
    assert frame_interval_ms(form="face", state="rest", model_busy=True, transitioning=False) == 83
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
    assert panel.timer_interval() == 83

    panel.set_speaking(True)
    panel.tick()
    assert panel.timer_interval() == 33

    panel.set_speaking(False)
    panel.set_model_busy(True)
    panel.set_state("rest")
    clock["t"] = 1.4
    panel.tick()
    assert panel.timer_interval() == 83
    panel.close()


def test_hiding_and_minimizing_stop_the_timer(qt_app):
    """A hidden widget or a minimized window does not keep ticking."""
    panel = _panel(qt_app)
    panel.show()
    qt_app.processEvents()
    assert panel.timer_running()
    panel.hide()
    qt_app.processEvents()
    assert not panel.timer_running()
    panel.show()
    qt_app.processEvents()
    assert panel.timer_running()
    panel.close()

    host = QWidget()
    from arelis.ui.persona_face import PersonaPanel

    docked = PersonaPanel(host)
    docked.set_bake_delay(60.0)
    docked.resize(160, 220)
    host.resize(180, 240)
    host.show()
    qt_app.processEvents()
    assert docked.timer_running()
    host.showMinimized()
    qt_app.processEvents()
    assert not docked.timer_running()
    host.showNormal()
    qt_app.processEvents()
    assert docked.timer_running()
    host.close()


def test_she_starts_as_the_orb_and_thinking_blooms_her(qt_app):
    """Rest begins on the orb. Thinking opens the face. Done plus a quiet minute folds her back."""
    panel = _panel(qt_app)
    clock = {"t": 0.0}
    panel.set_clock(lambda: clock["t"])
    assert panel.form() == "orb"
    assert panel.caption_text() == ""

    from arelis.ui.persona_face.panel import BLOOM_S, FOLD_S

    panel.set_state("thinking")
    opened = BLOOM_S + 0.05
    clock["t"] = opened
    panel.tick()
    assert panel.form() == "face"
    assert panel.caption_text() == "thinking"

    panel.set_state("done")
    assert panel.caption_text() == "done"
    clock["t"] = opened + 2.2
    panel.tick()
    assert panel.caption_text() == ""
    assert panel.form() == "face"

    clock["t"] = opened + 60.0
    panel.tick()
    clock["t"] = opened + 60.0 + FOLD_S + 0.1
    panel.tick()
    assert panel.form() == "orb"
    panel.close()


def test_a_click_on_the_orb_blooms_her(qt_app):
    """Clicking the orb opens the face, and the quiet minute can fold her again."""
    panel = _panel(qt_app)
    clock = {"t": 10.0}
    panel.set_clock(lambda: clock["t"])
    panel.show()
    qt_app.processEvents()
    assert panel.form() == "orb"
    from arelis.ui.persona_face.panel import BLOOM_S

    QTest.mouseClick(panel.avatar, Qt.MouseButton.LeftButton)
    clock["t"] = 10.0 + BLOOM_S + 0.05
    panel.tick()
    assert panel.form() == "face"
    panel.close()


def test_a_click_while_speaking_asks_to_stop(qt_app):
    """A click during speech emits stop_speaking_requested and shows the hint."""
    panel = _panel(qt_app)
    panel.show()
    hits: list[int] = []
    panel.stop_speaking_requested.connect(lambda: hits.append(1))
    panel.set_speaking(True)
    assert panel.caption_text() == "speaking"
    assert "stop" in panel.hint_text()
    QTest.mouseClick(panel.avatar, Qt.MouseButton.LeftButton)
    assert hits == [1]
    panel.close()


def test_status_line_is_plain_text(qt_app):
    """show_status keeps the line, then the clock lets it fade."""
    panel = _panel(qt_app)
    clock = {"t": 0.0}
    panel.set_clock(lambda: clock["t"])
    panel.show_status("one new message")
    assert panel.status_text() == "one new message"
    clock["t"] = 9.0
    panel.tick()
    assert panel.status_text() == ""
    panel.close()


def test_the_bake_stays_off_the_gui_thread_and_reads_as_her_face(qt_app):
    """She stays an orb while the bake runs, then the face has hair, skin, and dark pupils."""
    from arelis.ui.persona_face.bake import VIEW
    from arelis.ui.persona_face.engine import EYE_X, EYE_Y

    panel = _panel(qt_app)
    panel.set_bake_delay(0.0)
    beats = {"n": 0}
    pulse = QTimer()
    pulse.timeout.connect(lambda: beats.__setitem__("n", beats["n"] + 1))
    pulse.start(15)
    panel.show()
    qt_app.processEvents()
    assert panel.form() == "orb"

    deadline = time.monotonic() + 40.0
    while not panel.bake_ready and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    pulse.stop()
    assert panel.bake_ready
    assert beats["n"] > 3
    assert panel.bake_thread_name() != threading.main_thread().name
    assert panel.painted_orb_while_baking()

    sizes = panel.layer_shapes()
    assert sizes["face"][0] >= 140
    assert sizes["face"][1] >= 140
    assert sizes["wisps"] == sizes["face"]
    assert sizes["star"][0] > 0

    image = panel.rest_face_image()
    assert isinstance(image, QImage)
    assert image.width() == sizes["face"][1] or image.width() == sizes["face"][0]
    rgba = _image_rgba(image)
    assert rgba.shape[0] > 0 and rgba[..., 3].max() > 0

    def patch(x: float, y: float, rx: float = 0.03, ry: float = 0.03) -> np.ndarray:
        x0, x1, y0, y1 = VIEW
        height, width, _ = rgba.shape
        cx = (x - x0) / (x1 - x0) * (width - 1)
        cy = (y - y0) / (y1 - y0) * (height - 1)
        px = max(2, int(rx / (x1 - x0) * width))
        py = max(2, int(ry / (y1 - y0) * height))
        x_a = int(np.clip(cx - px, 0, width - 1))
        x_b = int(np.clip(cx + px + 1, x_a + 1, width))
        y_a = int(np.clip(cy - py, 0, height - 1))
        y_b = int(np.clip(cy + py + 1, y_a + 1, height))
        return rgba[y_a:y_b, x_a:x_b, :3].astype(np.float32)

    hair = patch(-0.02, -0.34, 0.06, 0.05).mean(axis=(0, 1))
    assert hair[2] > hair[1]
    assert hair[0] > hair[1]
    face = float(patch(0.0, 0.05, 0.04, 0.04).sum(axis=-1).mean())
    beside = float(patch(0.62, 0.05, 0.04, 0.04).sum(axis=-1).mean())
    assert face > beside + 20.0
    # Pupil sits just inside the iris. Compare the darkest eye pixel with the iris beside it.
    pupil = float(patch(EYE_X, EYE_Y + 0.006, 0.02, 0.016).sum(axis=-1).min())
    iris = float(patch(EYE_X + 0.02, EYE_Y + 0.006, 0.012, 0.012).sum(axis=-1).mean())
    assert pupil < iris - 5.0
    panel.close()


def test_a_blink_does_not_bring_the_orb_back(qt_app):
    """Closing her eyes keeps the calm face. The night light does not paint over her."""
    panel = _panel(qt_app)
    panel.set_bake_delay(0.0)
    clock = {"t": 0.0}
    panel.set_clock(lambda: clock["t"])
    panel.show()
    deadline = time.monotonic() + 40.0
    while not panel.bake_ready and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    assert panel.bake_ready
    from arelis.ui.persona_face.panel import BLOOM_S

    panel.set_state("thinking")
    clock["t"] = BLOOM_S + 0.05
    panel.tick()
    assert panel.form() == "face"
    assert panel.avatar.reveal == 1.0
    # The panel's own timer would push a fresh frame over the held blink
    # during processEvents (a race that failed this test now and then).
    panel._timer.stop()
    held = panel.avatar.frame
    panel.avatar.frame = type(held)(
        held.sway_deg,
        held.bob,
        held.breath,
        held.hair_root,
        held.hair_mid,
        held.hair_tip,
        held.wisp_x,
        held.wisp_y,
        held.gaze_x,
        held.gaze_y,
        held.star,
        held.ring,
        0.55,
        False,
        held.mouth,
        held.slow,
    )
    panel.avatar.repaint()
    qt_app.processEvents()
    assert panel.form() == "face"
    assert panel.avatar.reveal == 1.0
    assert panel.avatar.frame.blink == 0.55
    shot = panel.grab().toImage()
    rgba = _image_rgba(shot.convertToFormat(QImage.Format.Format_RGBA8888))
    height, width, _ = rgba.shape
    face = rgba[int(height * 0.28) : int(height * 0.55), int(width * 0.35) : int(width * 0.65), :3]
    assert float(face.mean()) > 40.0
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
