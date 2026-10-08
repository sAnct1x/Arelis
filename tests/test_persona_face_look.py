"""The baked face: a young adult mouth, smaller eyes, a longer chin."""

from __future__ import annotations

import numpy as np


def _world_span(mask: np.ndarray, view_width: float, pixels: int) -> float:
    cols = np.flatnonzero(mask)
    if len(cols) < 2:
        return 0.0
    return float(cols[-1] - cols[0] + 1) / float(pixels) * view_width


def test_closed_lips_stay_pale_and_the_open_mouth_is_not_black():
    """A resting smile is light pink. An open mouth is a soft plum, not a black hole."""
    from arelis.ui.persona_face.engine import Rig, paint_mouth

    rig = Rig(320)
    closed = paint_mouth(rig, 320, 0.0)
    cover = closed[..., 3] > 50
    assert int(cover.sum()) > 30
    alpha = closed[..., 3:4].astype(np.float32) / 255.0
    pale = closed[..., :3].astype(np.float32) / np.maximum(alpha, 1e-3)
    pale = pale[cover]
    assert float(pale.mean()) > 50.0
    assert float(np.percentile(pale.mean(axis=1), 70)) > 80.0

    opened = paint_mouth(rig, 320, 1.0)
    hole = opened[..., 3] > 50
    assert int(hole.sum()) > 30
    alpha = opened[..., 3:4].astype(np.float32) / 255.0
    dark = opened[..., :3].astype(np.float32) / np.maximum(alpha, 1e-3)
    dark = dark[hole]
    assert float(dark.mean()) > 30.0
    assert float(np.percentile(dark.mean(axis=1), 20)) > 12.0


def test_her_eyes_are_smaller_and_her_chin_is_narrower():
    """Early twenties: the eye opening is about 9 percent under the v2.3 width, and the jaw is slimmer."""
    from arelis.ui.persona_face.engine import EYE_Y, VIEW, Rig, paint_eyes, paint_face, unstretch_y

    width = 360
    rig = Rig(width)
    eyes = paint_eyes(rig, width, 0.0, (0.0, 0.0))
    x0, x1, y0, y1 = VIEW
    span_x = x1 - x0
    height = eyes.shape[0]
    cy = round((EYE_Y - y0) / (y1 - y0) * (height - 1))
    mid = round((0.0 - x0) / span_x * (width - 1))
    opening = 0.0
    for dy in range(-6, 7):
        row = eyes[cy + dy, mid:, 3]
        opening = max(opening, _world_span(row > 128, span_x, width))
    # v2.3 opening on this bake is about 0.111. Nine percent under that is about 0.101.
    assert 0.096 < opening < 0.106

    face = paint_face(rig, width)
    alpha = face[..., 3].astype(np.float32) / 255.0
    height = alpha.shape[0]
    view_y = y0 + (np.arange(height) + 0.5) * ((y1 - y0) / height)
    local = np.asarray(unstretch_y(view_y), dtype=np.float64)
    row_i = int(np.argmin(np.abs(local - 0.22)))
    jaw = _world_span(alpha[row_i] > 0.92, span_x, width)
    # v2.3 skin at this row is about 0.284 wide. The longer jaw is narrower.
    assert 0.23 < jaw < 0.272
