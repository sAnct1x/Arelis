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


