"""Mouth, blink, and idle motion for the persona face. No window required."""

from __future__ import annotations

import numpy as np


def _mouth():
    from arelis.ui.persona_face.motion import Mouth

    return Mouth()


def _motion():
    from arelis.ui.persona_face.motion import Motion

    return Motion


def test_louder_speech_opens_her_mouth_further():
    """A loud level leaves her mouth more open than a quiet one above the gate."""
    quiet = _mouth()
    loud = _mouth()
    dt = 1.0 / 30.0
    for _ in range(40):
        quiet.step(0.35, dt, speaking=True)
        loud.step(1.0, dt, speaking=True)
    assert loud.openness > quiet.openness + 0.25
    assert loud.openness > 0.7


def test_her_mouth_opens_quickly_and_closes_more_slowly():
    """Opening reaches most of the way in about three frames. Closing takes longer."""
    mouth = _mouth()
    dt = 1.0 / 30.0
    opened = [mouth.step(1.0, dt, speaking=True) for _ in range(3)]
    assert opened[-1] > 0.75
    # Same number of frames on the way down leaves her partly open.
    closing = [mouth.step(0.0, dt, speaking=True) for _ in range(3)]
    assert closing[-1] > 0.15
    assert closing[-1] < opened[-1] - 0.15
    for _ in range(24):
        mouth.step(0.0, dt, speaking=True)
    assert mouth.openness < 0.05


def test_levels_under_the_gate_keep_her_lips_shut():
    """Quiet gaps below the gate do not part the lips."""
    mouth = _mouth()
    dt = 1.0 / 30.0
    values = [mouth.step(0.08, dt, speaking=True) for _ in range(45)]
    assert max(values) < 0.02


def test_mouth_stays_shut_when_she_is_not_speaking():
    """A loud level source does nothing while speaking is off."""
    mouth = _mouth()
    dt = 1.0 / 30.0
    values = [mouth.step(1.0, dt, speaking=False) for _ in range(20)]
    assert max(values) < 0.02


def test_missing_level_uses_a_synthetic_envelope_only_while_speaking():
    """None from the level source still moves her mouth, and she closes when speech ends."""
    mouth = _mouth()
    dt = 1.0 / 30.0
    spoken = [mouth.step(None, dt, speaking=True) for _ in range(120)]
    assert max(spoken) > 0.25
    assert max(spoken) - min(spoken) > 0.15
    shut = [mouth.step(None, dt, speaking=False) for _ in range(45)]
    assert shut[-1] < 0.05


def test_sway_and_hair_do_not_repeat_over_ten_minutes():
    """Idle sway and hair drift stay in range, move smoothly, and do not loop."""
    motion_cls = _motion()
    motion = motion_cls(seed=4)
    dt = 0.05
    steps = int(600.0 / dt)
    sway = np.empty(steps)
    hair = np.empty(steps)
    blinks: list[float] = []
    t = 0.0
    for i in range(steps):
        frame = motion.step(
            t,
            dt,
            state="rest",
            speaking=False,
            model_busy=False,
            loudness=0.0,
        )
        sway[i] = frame.sway_deg
        hair[i] = frame.hair_tip
        if frame.blink_edge:
            blinks.append(t)
        t += dt

    assert float(np.max(np.abs(sway))) <= 0.6
    assert float(np.max(np.abs(np.diff(sway)))) < 0.08
    assert float(np.max(np.abs(np.diff(hair)))) < 0.12

    def _corr(series: np.ndarray, lag: int) -> float:
        centered = series - series.mean()
        energy = float(np.dot(centered, centered))
        return float(np.dot(centered[:-lag], centered[lag:]) / energy)

    for lag_s in (5, 10, 17, 30, 45, 60, 90, 120):
        lag = int(lag_s / dt)
        assert abs(_corr(sway, lag)) < 0.95
        assert abs(_corr(hair, lag)) < 0.95

    gaps = np.diff(np.asarray(blinks))
    long_gaps = gaps[gaps > 0.45]
    assert len(long_gaps) > 20
    assert float(long_gaps.min()) >= 2.4
    assert float(long_gaps.max()) <= 7.15
    assert float(long_gaps.max() - long_gaps.min()) > 0.5


def test_model_busy_shrinks_her_motion():
    """While the model is generating, sway amplitude drops to about half."""
    motion_cls = _motion()

    def _spread(busy: bool) -> float:
        motion = motion_cls(seed=4)
        values = []
        t = 0.0
        for _ in range(500):
            frame = motion.step(
                t,
                0.05,
                state="thinking",
                speaking=False,
                model_busy=busy,
                loudness=0.0,
            )
            values.append(frame.sway_deg)
            t += 0.05
        return float(np.std(values))

    assert _spread(True) < _spread(False) * 0.7
