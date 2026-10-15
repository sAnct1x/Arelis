"""v12 motion: wink, smile, glances, tilt, nod, a slight turn, more hair sway.

The approved art must be untouched at rest; the new frames are additions; the
head stays inside its limits; and nothing ever snaps back like a loop.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

_REF = Path(__file__).parent / "fixtures" / "persona" / "neutral_target_match.png"
_LAYERS: dict | None = None


def _layers() -> dict:
    global _LAYERS
    if _LAYERS is None:
        from arelis.ui.persona_face.engine import bake_layers

        _LAYERS = bake_layers(220)
    return _LAYERS


def _simulate(seconds: float = 600.0, dt: float = 1.0 / 30.0, seed: int = 7):
    """Idle, speaking, a finished reply, a busy model, then idle again."""
    from arelis.ui.persona_face.motion import Motion

    motion = Motion(seed=seed)
    frames = []
    states = []
    for i in range(int(seconds / dt)):
        t = i * dt
        speaking = 200.0 <= t < 260.0
        busy = 400.0 <= t < 460.0
        if abs(t - 260.0) < dt / 2:
            motion.cue("smile", t)
        state = "thinking" if busy else ("speaking" if speaking else "rest")
        if states and states[-1] != ("busy" if busy else ("speaking" if speaking else "idle")):
            # The panel pushes a frame with dt=0 the moment the state changes.
            motion.step(t, 0.0, state=state, speaking=speaking, model_busy=busy, loudness=None)
        frame = motion.step(
            t,
            dt,
            state=state,
            speaking=speaking,
            model_busy=busy,
            loudness=None,
        )
        frames.append(frame)
        states.append("busy" if busy else ("speaking" if speaking else "idle"))
    return frames, np.asarray(states)


def _series(frames, name: str) -> np.ndarray:
    return np.asarray([getattr(frame, name) for frame in frames], dtype=np.float64)


def test_the_approved_frames_are_untouched_and_the_new_ones_are_added():
    """Wink, smile and glance frames exist; approved eye and mouth frames stay."""
    from arelis.ui.persona_face.engine import BLINK_LEVELS, SMILE_LEVELS, WINK_LEVELS
    from arelis.ui.persona_face.plate import WINK_SIDE

    layers = _layers()
    for index in range(len(BLINK_LEVELS)):
        assert f"eye_{index}" in layers
    for index in range(1, len(WINK_LEVELS) + 1):
        assert f"wink_{index}" in layers
    for index in range(1, len(SMILE_LEVELS) + 1):
        assert f"smile_{index}" in layers
    assert {"glance_0", "glance_1"} <= set(layers)

    eye = layers["eye_0"].astype(np.int16)
    wink = layers[f"wink_{len(WINK_LEVELS)}"].astype(np.int16)
    width = eye.shape[1]
    moved = np.abs(wink - eye).max(axis=-1) > 8
    cols = np.flatnonzero(moved.any(axis=0))
    assert cols.size > 0
    # Only one eye closes: every changed pixel is on the WINK_SIDE half.
    if WINK_SIDE > 0:
        assert cols.min() > width // 2
    else:
        assert cols.max() < width // 2
    # The closed wink matches the closed blink on that eye.
    blink = layers[f"eye_{len(BLINK_LEVELS) - 1}"].astype(np.int16)
    side = slice(width // 2, None) if WINK_SIDE > 0 else slice(0, width // 2)
    assert int(np.abs(wink[:, side] - blink[:, side]).max()) <= 2

    mouth = layers["mouth_0"].astype(np.int16)
    smile = layers[f"smile_{len(SMILE_LEVELS)}"].astype(np.int16)
    assert int((np.abs(smile - mouth).max(axis=-1) > 8).sum()) >= 6
    # Outside the mouth box nothing is drawn by either frame.
    assert int(np.abs(smile[..., 3] - mouth[..., 3]).max()) <= 2


def _grab_premul(widget) -> np.ndarray:
    from PySide6.QtGui import QImage

    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    width, height = image.width(), image.height()
    raw = np.frombuffer(image.constBits(), np.uint8, count=image.sizeInBytes())
    rows = raw.reshape(height, -1)[:, : width * 4].reshape(height, width, 4)
    out = rows.astype(np.float32)
    # Over a dark dock, as she is seen.
    out[..., :3] += np.array([14.0, 16.0, 38.0]) * (1.0 - out[..., 3:4] / 255.0)
    return out


def _grab_alpha(image) -> np.ndarray:
    from PySide6.QtGui import QImage

    image = image.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    width, height = image.width(), image.height()
    raw = np.frombuffer(image.constBits(), np.uint8, count=image.sizeInBytes())
    return raw.reshape(height, -1)[:, : width * 4].reshape(height, width, 4)[..., 3].copy()
