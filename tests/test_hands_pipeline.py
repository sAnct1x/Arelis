"""Cursor lag, handedness blinks, and the color the landmarker actually sees."""

from __future__ import annotations

import numpy as np

from arelis.spatial.backend import present_selfie, sensor_hands
from arelis.spatial.types import FilterBank
from arelis.ui.panels.camera import _sample_yuyv
from tests.hands_pose import frame_of, make_hand


def test_still_hand_stays_put() -> None:
    bank = FilterBank()
    t = 0.0
    last = None
    raw = None
    for i in range(20):
        wobble = 0.002 if i % 2 else -0.002
        raw = make_hand("Right", (0.40 + wobble, 0.50), pose="open")
        last = bank.apply(frame_of(raw, t=t))
        t += 1.0 / 30.0
    assert last is not None and raw is not None
    pointer = last.hands[0].pointer
    assert pointer is not None
    cx, _cy = raw.pinch_centroid()
    assert abs(pointer[0] - cx) < 0.015


def test_selfie_flip_puts_landmarks_back_in_sensor_space() -> None:
    rgb = np.zeros((2, 4, 3), dtype=np.uint8)
    rgb[0, 0] = (9, 8, 7)
    flipped = present_selfie(rgb)
    assert tuple(int(v) for v in flipped[0, -1]) == (9, 8, 7)
    hand = make_hand("Left", (0.20, 0.40), pose="open")
    out = sensor_hands([hand])
    assert out[0].label == "Left"
    assert abs(out[0].xy(0)[0] - 0.80) < 1e-6
    assert abs(out[0].xy(0)[1] - 0.40) < 1e-6


def test_yuyv_keeps_chroma() -> None:
    # Y U Y V for two pixels, V high.
    buf = np.array([[100, 128, 100, 200]], dtype=np.uint8).reshape(-1)
    rgb = _sample_yuyv(buf, 2, 1, 4, 2, 1, uyvy=False)
    assert rgb.shape == (1, 2, 3)
    assert int(rgb[0, 0, 0]) > int(rgb[0, 0, 1]) + 40
    assert int(rgb[0, 1, 0]) > int(rgb[0, 1, 1]) + 40


def _scale_about_wrist(hand, scale: float):
    from arelis.spatial.types import Hand, Landmark

    wx, wy = hand.xy(0)
    marks = tuple(
        Landmark(
            x=wx + (lm.x - wx) * scale,
            y=wy + (lm.y - wy) * scale,
            z=lm.z,
            name=lm.name,
        )
        for lm in hand.landmarks
    )
    return Hand(label=hand.label, landmarks=marks, score=hand.score)


def _spin_about_wrist(hand, radians: float):
    import math

    from arelis.spatial.types import Hand, Landmark

    wx, wy = hand.xy(0)
    c, s = math.cos(radians), math.sin(radians)
    marks = []
    for lm in hand.landmarks:
        dx, dy = lm.x - wx, lm.y - wy
        marks.append(
            Landmark(
                x=wx + c * dx - s * dy,
                y=wy + s * dx + c * dy,
                z=lm.z,
                name=lm.name,
            )
        )
    return Hand(label=hand.label, landmarks=tuple(marks), score=hand.score)


