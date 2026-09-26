"""Cursor lag, handedness blinks, and the color the landmarker actually sees."""

from __future__ import annotations

import numpy as np

from arelis.spatial.backend import present_selfie, sensor_hands
from arelis.spatial.gesture import follow_hand
from arelis.spatial.types import FilterBank
from arelis.ui.panels.camera import _sample_nv12, _sample_rgb32, _sample_yuyv
from tests.hands_pose import frame_of, make_hand


def test_fast_hand_is_not_stuck_on_the_lowpass() -> None:
    bank = FilterBank()
    t = 0.0
    for _ in range(12):
        bank.apply(frame_of(make_hand("Right", (0.20, 0.50), pose="open"), t=t))
        t += 1.0 / 30.0
    jumped = bank.apply(frame_of(make_hand("Right", (0.70, 0.50), pose="open"), t=t))
    pointer = jumped.hands[0].pointer
    assert pointer is not None
    # beta=0.007 on a 0–1 axis stays near 0.28 after this jump.
    assert pointer[0] > 0.55


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


def test_idle_track_keeps_a_hand_whose_label_blinked() -> None:
    blinked = make_hand("Right", (0.30, 0.50), pose="open")
    kept = follow_hand((blinked,), label="Left", wrist=(0.30, 0.50), idle=True)
    assert kept is blinked
    other = make_hand("Right", (0.70, 0.50), pose="open")
    assert follow_hand((other,), label="Left", wrist=(0.30, 0.50), idle=True) is None


def test_nv12_keeps_chroma() -> None:
    # 4x2, tight stride. High V is red skin, not grey.
    y = np.full((2, 4), 100, dtype=np.uint8)
    uv = np.array([[128, 200, 128, 200]], dtype=np.uint8)
    buf = np.concatenate([y.reshape(-1), uv.reshape(-1)])
    rgb = _sample_nv12(buf, 4, 2, 4, 2, 2)
    assert rgb.shape == (2, 2, 3)
    assert int(rgb[0, 0, 0]) > int(rgb[0, 0, 1]) + 40


def test_yuyv_keeps_chroma() -> None:
    # Y U Y V for two pixels, V high.
    buf = np.array([[100, 128, 100, 200]], dtype=np.uint8).reshape(-1)
    rgb = _sample_yuyv(buf, 2, 1, 4, 2, 1, uyvy=False)
    assert rgb.shape == (1, 2, 3)
    assert int(rgb[0, 0, 0]) > int(rgb[0, 0, 1]) + 40
    assert int(rgb[0, 1, 0]) > int(rgb[0, 1, 1]) + 40


def test_a_curled_close_is_still_a_pinch() -> None:
    from arelis.spatial.gesture import GestureMachine, read_pose

    fist = make_hand("Left", (0.30, 0.50), pose="fist")
    assert read_pose(fist) == "pinch"
    machine = GestureMachine()
    t = 1.0
    for _ in range(4):
        machine.step(frame_of(fist, t=t))
        t += 0.03
    assert [track.state for track in machine.tracks] == ["pinch"]


def test_depth_starts_at_rest_and_a_reach_comes_closer() -> None:
    from arelis.spatial.depth import Z_WORLD_REF, DepthBank

    bank = DepthBank()
    hand = make_hand("Right", (0.50, 0.55), pose="open")
    z0 = bank.observe("Right", hand, t=1.0, width=640, height=360)
    assert abs(z0 - Z_WORLD_REF) < 1e-6
    closer = _scale_about_wrist(hand, 1.25)
    z1 = bank.observe("Right", closer, t=1.2, width=640, height=360)
    assert z1 < z0


def test_turning_the_hand_does_not_punch_the_depth() -> None:
    from arelis.spatial.depth import DepthBank

    bank = DepthBank()
    hand = make_hand("Right", (0.50, 0.55), pose="open")
    z0 = bank.observe("Right", hand, t=1.0, width=640, height=360)
    turned = _spin_about_wrist(hand, 0.6)
    z1 = bank.observe("Right", turned, t=1.1, width=640, height=360)
    assert abs(z1 - z0) < 1e-6


def test_pinch_grab_turns_with_the_wrist_and_ignores_a_flip() -> None:
    from arelis.spatial.scene import WorldScene

    scene = WorldScene()
    sphere = scene.bodies[0]
    scene.apply_pointer(
        sphere.x, sphere.y, True, t=1.0, who="Right", kind="pinch", angle=0.1
    )
    assert sphere.attached
    scene.apply_pointer(
        sphere.x, sphere.y, True, t=1.05, who="Right", kind="pinch", angle=0.3
    )
    assert abs(sphere.angle - 0.2) < 1e-6
    held = sphere.angle
    scene.apply_pointer(
        sphere.x, sphere.y, True, t=1.10, who="Right", kind="pinch", angle=0.3 + 3.0
    )
    assert abs(sphere.angle - held) < 1e-6


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


def test_bgra_sample_is_rgb_and_vectorized() -> None:
    # Two pixels, BGRA: blue, then red.
    row = np.array([255, 0, 0, 255, 0, 0, 255, 255], dtype=np.uint8)
    rgb = _sample_rgb32(row, 2, 1, 8, 2, 1, "Format_BGRA8888")
    assert tuple(int(v) for v in rgb[0, 0]) == (0, 0, 255)
    assert tuple(int(v) for v in rgb[0, 1]) == (255, 0, 0)
