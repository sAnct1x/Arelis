"""Mouth, blink, and idle motion for the persona face. No window required."""

from __future__ import annotations


def _mouth():
    from arelis.ui.persona_face.motion import Mouth

    return Mouth()


def _motion():
    from arelis.ui.persona_face.motion import Motion

    return Motion


def test_levels_under_the_gate_keep_her_lips_shut():
    """Quiet gaps below the gate do not part the lips."""
    mouth = _mouth()
    dt = 1.0 / 30.0
    values = [mouth.step(0.08, dt, speaking=True) for _ in range(45)]
    assert max(values) < 0.02


