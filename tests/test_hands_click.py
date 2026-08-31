"""Pinch-tap click vs pinch-travel grab. No camera."""

from __future__ import annotations

from arelis.spatial.gesture import GestureMachine, GestureParams, PinchClick
from arelis.spatial.scene import WorldScene
from tests.test_spatial_rung0 import _frame, _pinch_hand


def _machine() -> GestureMachine:
    return GestureMachine(
        GestureParams(frames_on=1, frames_off=1, pinch_off=1, click_travel=0.035)
    )


def test_pinch_click_is_frozen_at_down() -> None:
    machine = _machine()
    machine.step(_frame((_pinch_hand(0.04, origin=(0.30, 0.40)),), t=1.0))
    frozen = machine.tracks[0].frozen_xy
    machine.step(_frame((_pinch_hand(0.20, origin=(0.31, 0.40)),), t=1.05))
    clicks = machine.consume_clicks()
    assert len(clicks) == 1
    assert isinstance(clicks[0], PinchClick)
    assert frozen is not None
    assert abs(clicks[0].x - frozen[0]) < 1e-9


def test_pinch_travel_is_a_grab_not_a_click() -> None:
    machine = _machine()
    machine.step(_frame((_pinch_hand(0.04, origin=(0.30, 0.40)),), t=1.0))
    assert machine.tracks[0].dragging is False
    machine.step(_frame((_pinch_hand(0.04, origin=(0.50, 0.40)),), t=1.05))
    assert machine.tracks[0].dragging is True
    machine.step(_frame((_pinch_hand(0.20, origin=(0.51, 0.40)),), t=1.10))
    assert machine.consume_clicks() == []


def test_fist_palm_turn_rotates_the_disc() -> None:
    scene = WorldScene()
    scene.apply_pointer(0.50, 0.50, True, t=1.0, who="Right", kind="fist", angle=0.0)
    a0 = scene.disc.angle
    scene.apply_pointer(0.50, 0.50, True, t=1.1, who="Right", kind="fist", angle=0.4)
    assert scene.disc.angle == a0 + 0.4
