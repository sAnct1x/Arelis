"""v12 motion: wink, smile, glances, tilt, nod, a slight turn, more hair sway.

The approved art must be untouched at rest; the new frames are additions; the
head stays inside its limits; and nothing ever snaps back like a loop.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

_REF = Path(__file__).parent / "fixtures" / "persona" / "neutral_98fc399.png"
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


def test_the_rest_pose_transform_is_the_approved_one(qt_app):
    """All v12 values at zero give exactly the pre-v12 sway/breath transform."""
    from PySide6.QtGui import QTransform

    from arelis.ui.persona_face.avatar import PersonaAvatar
    from arelis.ui.persona_face.motion import Frame

    avatar = PersonaAvatar()
    avatar.resize(280, 360)
    avatar.frame = Frame(0.4, 0.3, 0.5, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0)
    rect = avatar._face_rect()
    pivot = avatar._map(0.0, 0.36, rect)
    breath = 1.0 + 0.004 * 0.5
    legacy = QTransform()
    legacy.translate(pivot.x(), pivot.y() + 0.3 * 4.0)
    legacy.rotate(0.4)
    legacy.scale(breath, breath)
    legacy.translate(-pivot.x(), -pivot.y())
    head = avatar.head_transform(rect)
    assert head == legacy
    for kind in ("back", "front", "star", "face"):
        assert avatar._depth(head, rect, kind) == head
    avatar.shutdown()


def test_the_neutral_frame_matches_the_approved_98fc399_render(qt_app):
    """Neutral frame through the real widget, within 2 of the accepted hem pass."""
    from PIL import Image
    from PySide6.QtGui import QImage

    from arelis.ui.persona_face.motion import Frame
    from arelis.ui.persona_face.panel import PersonaPanel
    from arelis.ui.theme import apply_theme

    if not _REF.exists():
        pytest.skip("no reference render")
    apply_theme("night")
    panel = PersonaPanel()
    panel.resize(280, 360)
    panel.set_bake_delay(0)
    panel.show()
    qt_app.processEvents()
    deadline = time.monotonic() + 60.0
    while not panel.bake_ready and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    assert panel.bake_ready
    panel.avatar.shutdown()
    panel._timer.stop()
    panel._mode = "face"
    panel.avatar.reveal = 1.0
    panel.avatar.frame = Frame(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0)
    panel.avatar.repaint()
    qt_app.processEvents()
    image = panel.avatar.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    panel.close()
    width, height = image.width(), image.height()
    ptr = image.constBits()
    got = np.frombuffer(ptr, np.uint8, count=image.sizeInBytes()).reshape(height, -1)[
        :, : width * 4
    ]
    got = got.reshape(height, width, 4).astype(np.int16)
    ref = np.asarray(Image.open(_REF).convert("RGBA")).astype(np.int16)
    if ref.shape != got.shape:
        pytest.skip(f"reference {ref.shape} vs grab {got.shape}: other DPR")
    assert int(np.abs(got - ref).max()) <= 2


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


def test_wink_smile_and_glances_are_reached_by_the_motion():
    """Random, not on a timer: each shows up, with uneven gaps."""
    frames, states = _simulate()
    wink = _series(frames, "wink")
    smile = _series(frames, "smile")
    glance = _series(frames, "glance")
    idle = states == "idle"
    assert wink[idle].max() > 0.99
    assert smile[idle].max() > 0.6
    assert np.abs(glance[idle]).max() > 0.5
    starts = np.flatnonzero((wink[1:] > 0.01) & (wink[:-1] <= 0.01))
    assert len(starts) >= 3
    gaps = np.diff(starts)
    assert gaps.max() - gaps.min() > 30
    # Speaking: she looks toward the chat (left by default) most of the time.
    talking = states == "speaking"
    assert float(np.mean(glance[talking] < -0.3)) > 0.5
    assert float(np.mean(_series(frames, "turn")[talking])) < -0.1
    # No winks while she talks or the model works.
    assert wink[talking].max() == 0.0
    assert wink[states == "busy"].max() == 0.0


def test_head_motion_stays_inside_its_limits(qt_app):
    """Roll a few degrees, a small nod and turn, and tiny squashes."""
    from arelis.ui.persona_face import avatar as avatar_mod
    from arelis.ui.persona_face.motion import MAX_NOD, MAX_ROLL_DEG, MAX_TURN, Frame

    frames, _states = _simulate()
    roll = _series(frames, "roll_deg") + _series(frames, "sway_deg")
    assert np.abs(_series(frames, "roll_deg")).max() <= MAX_ROLL_DEG
    assert np.abs(roll).max() <= MAX_ROLL_DEG + 0.6
    assert np.abs(_series(frames, "nod")).max() <= MAX_NOD
    assert np.abs(_series(frames, "turn")).max() <= MAX_TURN
    assert MAX_ROLL_DEG <= 3.5
    assert avatar_mod.NOD_SQUASH <= 0.015
    assert avatar_mod.TURN_SQUASH <= 0.015
    assert avatar_mod.NOD_SHIFT <= 0.012
    assert avatar_mod.TURN_PARALLAX <= 0.01

    avatar = avatar_mod.PersonaAvatar()
    avatar.resize(280, 360)
    rect = avatar._face_rect()
    avatar.frame = Frame(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0)
    rest = avatar.head_transform(rect)
    avatar.frame = Frame(
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0, nod=MAX_NOD, turn=MAX_TURN
    )
    moved = avatar.head_transform(rect)
    # Squash only: x and y scale within 1.5 % of rest, shift a few pixels.
    assert 0.985 <= moved.m11() / rest.m11() <= 1.0
    assert 0.985 <= moved.m22() / rest.m22() < 1.0
    assert abs(moved.dy() - rest.dy()) <= 0.03 * rect.height()
    front = avatar._depth(moved, rect, "front")
    back = avatar._depth(moved, rect, "back")
    assert 0.0 < front.dx() - back.dx() <= 0.02 * rect.width()
    avatar.shutdown()


def test_no_motion_snaps_or_loops():
    """Smooth across state changes, the hair sweep never skips, nothing repeats."""
    frames, _states = _simulate()
    limits = {
        "roll_deg": 0.12,
        "turn": 0.08,
        "sway_deg": 0.05,
        "hair_tip": 0.05,
        "smile": 0.12,
        "nod": 0.2,
    }
    for name, limit in limits.items():
        steps = np.abs(np.diff(_series(frames, name)))
        assert float(steps.max()) < limit, name

    def _corr(series: np.ndarray, lag: int) -> float:
        centered = series - series.mean()
        return float(np.dot(centered[:-lag], centered[lag:]) / np.dot(centered, centered))

    for name in ("roll_deg", "turn", "hair_tip"):
        series = _series(frames, name)[: 190 * 30]
        for lag_s in (5, 10, 20, 30, 45, 60, 90):
            assert abs(_corr(series, lag_s * 30)) < 0.95, (name, lag_s)


def test_a_busy_model_calms_the_new_motion():
    frames, states = _simulate()
    busy = states == "busy"
    idle = states == "idle"
    for name in ("roll_deg", "turn", "nod"):
        series = _series(frames, name)
        # Skip the first second of the busy span while calm eases in.
        settled = busy & (np.cumsum(busy) > 30)
        assert np.std(series[settled]) < np.std(series[idle]) * 0.75, name
    assert _series(frames, "smile")[busy & (np.cumsum(busy) > 90)].max() < 0.5


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


def test_the_materialize_has_no_box_no_marker_and_no_jump(qt_app):
    """Fade-in frames through the real widget.

    The eye and mouth frames are opaque skin boxes; drawn at part opacity over
    the fading face they used to show as a box. The star used to fly across
    her forehead as a crosshair and the orb's core sat on her nose as a dot.
    """
    from arelis.ui.persona_face.face_src import STAR_AT
    from arelis.ui.persona_face.motion import Frame
    from arelis.ui.persona_face.panel import PersonaPanel

    panel = PersonaPanel()
    panel.resize(370, 600)
    panel.set_bake_delay(0)
    panel.show()
    qt_app.processEvents()
    deadline = time.monotonic() + 90.0
    while not panel.bake_ready and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    assert panel.bake_ready
    panel.avatar.shutdown()
    panel._timer.stop()
    panel._mode = "face"
    avatar = panel.avatar

    frames = []
    for step in range(79):
        u = step / 78.0
        avatar.reveal = u * u * (3.0 - 2.0 * u)
        avatar.frame = Frame(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0)
        frames.append((avatar.reveal, _grab_premul(avatar)))
    panel.close()

    rect = avatar._face_rect()
    image = avatar._images["mouth_0"]
    alpha = _grab_alpha(image)
    ys, xs = np.nonzero(alpha)
    height, width = alpha.shape
    x0 = int(rect.x() + xs.min() / width * rect.width())
    x1 = int(rect.x() + xs.max() / width * rect.width())
    y0 = int(rect.y() + ys.min() / height * rect.height())
    y1 = int(rect.y() + ys.max() / height * rect.height())

    rest = frames[-1][1][..., :3].mean(-1)
    grid_y, grid_x = np.mgrid[0 : rest.shape[0], 0 : rest.shape[1]]
    star = avatar._map(STAR_AT[0], STAR_AT[1], rect)
    away = np.hypot(grid_x - star.x(), grid_y - star.y()) > rect.width() * 0.09
    face = (
        (grid_x > rect.x() + rect.width() * 0.30)
        & (grid_x < rect.x() + rect.width() * 0.70)
        & (grid_y > rect.y() + rect.height() * 0.22)
        & (grid_y < rect.y() + rect.height() * 0.72)
    )

    def edges(lum: np.ndarray) -> np.ndarray:
        rows = slice(y0 + 4, y1 - 4)
        cols = slice(x0 + 4, x1 - 4)
        return np.array(
            [
                lum[rows, x0 + 2 : x0 + 5].mean() - lum[rows, x0 - 5 : x0 - 2].mean(),
                lum[rows, x1 - 4 : x1 - 1].mean() - lum[rows, x1 + 2 : x1 + 5].mean(),
                lum[y0 + 2 : y0 + 5, cols].mean() - lum[y0 - 5 : y0 - 2, cols].mean(),
                lum[y1 - 4 : y1 - 1, cols].mean() - lum[y1 + 2 : y1 + 5, cols].mean(),
            ]
        )

    rest_edges = edges(rest)
    rest_mean = rest[y0:y1, x0:x1].mean()
    jumps = []
    previous = None
    for reveal, frame in frames:
        lum = frame[..., :3].mean(-1)
        if reveal >= 0.25:
            # Inside-minus-outside across the patch border, against the rest
            # frame's own (scaled to this frame's brightness). A box shows here.
            scale = lum[y0:y1, x0:x1].mean() / rest_mean
            assert float(np.abs(edges(lum) - rest_edges * scale).max()) < 5.0, reveal
        if reveal >= 0.2:
            # Nothing on her face is brighter than the finished face: no
            # crosshair, no orb dot.
            assert int(((lum - rest > 30.0) & face & away).sum()) <= 2, reveal
        if previous is not None:
            jumps.append(float(np.abs(frame - previous).mean()))
        previous = frame
    jumps = np.asarray(jumps)
    # A smooth fade: no single frame jumps far above the typical step.
    assert float(jumps.max()) < 2.5 * float(np.median(jumps)), jumps.max()


def _grab_alpha(image) -> np.ndarray:
    from PySide6.QtGui import QImage

    image = image.convertToFormat(QImage.Format.Format_RGBA8888_Premultiplied)
    width, height = image.width(), image.height()
    raw = np.frombuffer(image.constBits(), np.uint8, count=image.sizeInBytes())
    return raw.reshape(height, -1)[:, : width * 4].reshape(height, width, 4)[..., 3].copy()
