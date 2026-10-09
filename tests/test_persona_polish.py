"""Approved face, clean thoughts, and a plate that disappears into the theme."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from arelis.core.events import Event, EventType
from arelis.ui.event_host import dispatch_event
from arelis.ui.persona_face.motion import Frame

_INTERNAL = (
    "thinking\u2026 (fast: qwen3.5:9b)",
    "Role 'fast' -> model qwen3.5:9b",
    "round 1/8 weather",
    "phase=model role=fast",
    "timing  total=48.3s model=48.3s",
    "loading the model...",
    "waiting for the conversation model...",
    "Ready for the first reply.",
)
_REASON = "The moon pulls the water, so the tide rises."


def _plain(window) -> str:
    return window.chat.view.toPlainText()


def test_expanded_thought_keeps_reasoning_and_drops_internal_lines(arelis_window, qt_app, caplog):
    import logging

    caplog.set_level(logging.INFO)
    """A turn's thought is her reasoning. Status and model lines stay off that block."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window.persona_dock.show()
    window._set_busy(True)
    for line in _INTERNAL:
        dispatch_event(window, Event(EventType.THINKING, {"text": line}))
    dispatch_event(window, Event(EventType.THINKING, {"text": _REASON}))
    window.chat.expand_thinking()
    qt_app.processEvents()
    shown = _plain(window)
    assert _REASON in shown
    assert "round " not in shown
    assert "phase=" not in shown
    assert "timing total" not in shown
    assert "timing  total" not in shown
    assert "Role " not in shown
    assert "loading the model" not in shown
    assert "fast:" not in shown
    logged = caplog.text
    assert "phase=" in logged
    assert "Role " in logged
    # She is open, so the latest internal line is on her caption, not dropped.
    assert window.persona_panel.status_text()
    window.persona_dock.hide()
    window.close()


def test_a_turn_with_no_reasoning_has_no_thought_line(arelis_window, qt_app):
    """Only internal lines do not open a thought."""
    window = arelis_window()
    window.show()
    qt_app.processEvents()
    window._set_busy(True)
    dispatch_event(window, Event(EventType.THINKING, {"text": "round 2/8 search"}))
    dispatch_event(window, Event(EventType.THINKING, {"text": "phase=fanout n=1"}))
    window.chat.expand_thinking()
    qt_app.processEvents()
    shown = _plain(window)
    assert "round " not in shown
    assert "phase=" not in shown
    assert "Thinking for" not in shown
    window.persona_dock.hide()
    window.close()


# Cheek centre on the v2.4 closeup, the lower cheek just right of the nose.
_CHEEK = np.array([189.0, 179.0, 199.0])
_LAYERS: dict | None = None


def _layers() -> dict:
    global _LAYERS
    if _LAYERS is None:
        from arelis.ui.persona_face.engine import bake_layers

        _LAYERS = bake_layers(220)
    return _LAYERS


def _world_patch(image: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    from arelis.ui.persona_face.engine import VIEW

    x0, x1, y0, y1 = VIEW
    height, width, _ = image.shape
    left, right, top, bottom = box
    px0 = int((left - x0) / (x1 - x0) * (width - 1))
    px1 = int((right - x0) / (x1 - x0) * (width - 1))
    py0 = int((top - y0) / (y1 - y0) * (height - 1))
    py1 = int((bottom - y0) / (y1 - y0) * (height - 1))
    return image[py0:py1, px0:px1]


def test_baked_skin_is_lavender_like_the_approved_closeup():
    """Cheek centre stays within 12 levels of (189, 179, 199) on each channel.

    That is the lower cheek on the v2.4 closeup. Blue sits at least 12 above
    green. The drifted plate was grey, with blue only a couple above green,
    and about 60 levels darker than this.
    """
    from arelis.ui.persona_face.bake import composite_rest, flatten_on_black

    plate = flatten_on_black(composite_rest(_layers()))
    patch = _world_patch(plate, (-0.02, 0.08, 0.10, 0.16))[..., :3].astype(np.float64)
    mean = patch.mean(axis=(0, 1))
    assert np.all(np.abs(mean - _CHEEK) <= 12.0), mean
    assert float(mean[2] - mean[1]) >= 12.0
    from arelis.ui.persona_face.engine import EYE_X, EYE_Y, VIEW

    height, width, _ = plate.shape
    x0, x1, y0, y1 = VIEW
    ex = int((EYE_X - x0) / (x1 - x0) * (width - 1))
    ey = int((EYE_Y - y0) / (y1 - y0) * (height - 1))
    eye = plate[ey - 8 : ey + 10, ex - 8 : ex + 8, :3].astype(np.float64)
    chroma = float((eye[..., 2] - eye[..., 1]).max())
    assert chroma > 60.0


def test_back_hair_is_strands_behind_her_neck():
    """Behind the neck, between the side locks, the back layer is strand hair.

    A flat fill of that same average has column deviation near 0 (under 1
    level even with rounding). This field measures well above 4, which is
    the cut a flat block fails and a strand texture still clears.
    """
    from arelis.ui.persona_face.bake import composite_rest

    plate = composite_rest(_layers())
    patch = _world_patch(plate, (-0.06, 0.06, 0.50, 0.80))
    alpha = patch[..., 3].astype(np.float64)
    assert float(alpha.mean()) > 40.0
    rgb = patch[..., :3].astype(np.float64)
    mean = rgb.mean(axis=(0, 1))
    assert float(mean[2] - mean[1]) >= 4.0
    # Deviation across the row. A flat block is ~0. Strands are not.
    deviation = float(rgb.mean(axis=-1).std(axis=1).mean())
    assert deviation > 4.0, deviation


def test_composited_hair_has_no_horizontal_stripes():
    """No hair row jumps more than 3 levels away from both neighbours.

    Slice warps overlapped by a fraction of a pixel and added, which drew a
    bright line on every band. A whole phase frame does not.
    """
    from arelis.ui.persona_face.bake import composite_rest

    plate = composite_rest(_layers())
    # Back hair under the chin, between the side locks. A slice warp stripes
    # this whole column. Feature edges on the face are not in the box.
    hair = _world_patch(plate, (-0.10, 0.10, 0.56, 0.88))
    rows = hair[..., :3].astype(np.float64).mean(axis=(1, 2))
    for index in range(1, len(rows) - 1):
        left = abs(float(rows[index] - rows[index - 1]))
        right = abs(float(rows[index] - rows[index + 1]))
        assert not (left > 3.0 and right > 3.0), (index, left, right)


def _panel_on(theme: str, qt_app):
    from arelis.ui.persona_face.panel import PersonaPanel
    from arelis.ui.theme import apply_theme, color

    apply_theme(theme)
    backdrop = color("bg0")
    panel = PersonaPanel()
    panel.resize(280, 360)
    panel.set_bake_delay(0)
    panel.show()
    qt_app.processEvents()
    deadline = time.monotonic() + 40.0
    while not panel.bake_ready and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    assert panel.bake_ready
    panel._timer.stop()
    panel._mode = "face"
    panel.avatar.reveal = 1.0
    panel.avatar.frame = Frame(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0)
    panel.repaint()
    qt_app.processEvents()
    pix = QPixmap(panel.size())
    pix.fill(backdrop)
    painter = QPainter(pix)
    panel.render(painter, QPoint(0, 0))
    painter.end()
    return panel, pix.toImage(), backdrop


def _rgba_gap(image, backdrop) -> np.ndarray:
    from PySide6.QtGui import QImage

    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = converted.width()
    height = converted.height()
    buf = np.frombuffer(converted.constBits(), dtype=np.uint8, count=height * width * 4)
    rgb = buf.reshape((height, width, 4))[..., :3].astype(np.int16)
    tone = np.array([backdrop.red(), backdrop.green(), backdrop.blue()], dtype=np.int16)
    return np.max(np.abs(rgb - tone), axis=-1)


def test_her_plate_matches_each_theme_just_outside_the_figure(qt_app):
    """Night, sodium and filament: no faint rectangle outside the figure.

    Solid pixels are the hair and the face. A veil more than 14 pixels away
    from that solid is the plate, and it has to sit within 2 levels of the dock.
    """
    from arelis.ui.theme import apply_theme

    for theme in ("night", "sodium", "filament"):
        panel, image, backdrop = _panel_on(theme, qt_app)
        gap = _rgba_gap(image, backdrop)
        solid = gap > 25
        near = solid.copy()
        for _ in range(14):
            grown = near.copy()
            grown[1:] |= near[:-1]
            grown[:-1] |= near[1:]
            grown[:, 1:] |= near[:, :-1]
            grown[:, :-1] |= near[:, 1:]
            near = grown
        haze = (gap >= 3) & (gap <= 14) & (~near)
        assert int(haze.sum()) < 40, (theme, int(haze.sum()))
        panel.close()
    apply_theme("sodium")


def test_hair_tips_move_and_roots_stay_and_busy_is_quieter(qt_app):
    """A few seconds of flow moves the tips. The roots and the face barely move.

    Busy cuts the same drive, so the tip shift is smaller than calm.
    """
    from arelis.ui.persona_face.motion import Motion
    from arelis.ui.persona_face.panel import PersonaPanel

    calm = Motion(seed=3)
    busy = Motion(seed=3)
    calm_tips = []
    busy_tips = []
    for step in range(80):
        t = step * 0.05
        calm_tips.append(
            abs(
                calm.step(
                    t, 0.05, state="rest", speaking=False, model_busy=False, loudness=0.0
                ).hair_tip
            )
        )
        busy_tips.append(
            abs(
                busy.step(
                    t, 0.05, state="rest", speaking=False, model_busy=True, loudness=0.0
                ).hair_tip
            )
        )
    assert max(calm_tips) > max(busy_tips) + 0.05

    panel = PersonaPanel()
    panel.resize(220, 300)
    panel.set_bake_delay(0)
    panel.show()
    deadline = time.monotonic() + 40.0
    while not panel.bake_ready and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    assert panel.bake_ready
    deadline = time.monotonic() + 90.0
    while panel.avatar.phases_ready() < 8 and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.02)
    assert panel.avatar.phases_ready() >= 8
    panel._timer.stop()
    panel._mode = "face"
    panel.avatar.reveal = 1.0

    def grab(frame: Frame) -> np.ndarray:
        panel.avatar.frame = frame
        panel.avatar.repaint()
        QApplication.processEvents()
        image = panel.grab().toImage()
        converted = image.convertToFormat(image.format())
        return _rgba(converted)

    still = Frame(0, 0, 0, 0.0, 0.0, 0.0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0, 0.0)
    later = Frame(0, 0, 0, 0.04, 0.2, 0.85, 0, 0, 0, 0, 1, 1, 0, False, 0, 0, 4.0)
    first = grab(still)
    second = grab(later)
    height, width, _ = first.shape
    diff = np.abs(first.astype(np.int16) - second.astype(np.int16))[..., :3].mean(axis=-1)
    # Scalp side stays put. The lower side lock is the tips. The cheek is the face.
    roots = diff[int(height * 0.11) : int(height * 0.17), int(width * 0.28) : int(width * 0.40)]
    tips = diff[int(height * 0.43) : int(height * 0.52), int(width * 0.50) : int(width * 0.68)]
    face = diff[int(height * 0.27) : int(height * 0.35), int(width * 0.40) : int(width * 0.55)]
    assert float(tips.mean()) > float(roots.mean()) + 1.5
    assert float(tips.mean()) > float(face.mean()) + 1.5
    assert float(face.mean()) < 2.0
    panel.close()


def _rgba(image) -> np.ndarray:
    from PySide6.QtGui import QImage

    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width = converted.width()
    height = converted.height()
    bits = converted.constBits()
    buf = np.frombuffer(bits, dtype=np.uint8, count=height * width * 4)
    return buf.reshape((height, width, 4)).copy()
