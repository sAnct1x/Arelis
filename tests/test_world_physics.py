"""Rung 2: g, throw, place, bounce. Pinch is XY grab. Fist is rotate+Z."""

from __future__ import annotations

from arelis.spatial.scene import GRAVITY, Disc, WorldScene


def _plane(*bodies: Disc) -> WorldScene:
    """2D engine tests inject discs. The live stage is a sphere."""
    scene = WorldScene()
    scene.bodies = list(bodies) if bodies else [Disc()]
    return scene


def test_a_still_release_is_a_place() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=2.00, who="Right", kind="pinch")
    scene.apply_pointer(0.501, 0.500, True, t=2.10, who="Right", kind="pinch")
    scene.apply_pointer(0.501, 0.500, False, t=2.10, who="Right", kind="open")
    assert scene.disc.vx == 0.0
    assert scene.disc.vy == 0.0
    assert scene.last_release_speed == 0.0
    x0 = scene.disc.x
    y0 = scene.disc.y
    scene.step(0.20)
    assert abs(scene.disc.x - x0) < 1e-9
    assert scene.disc.y > y0


def test_energy_is_in_the_take_row() -> None:
    scene = _plane()
    scene.disc.y = 0.40
    row = scene.to_log()
    assert row["energy"] == round(scene.energy(), 8)
    assert row["energy"] > 0
    assert row["attached"] is False
    assert row["holder"] == ""
    assert len(row["bodies"]) == 1
    assert GRAVITY > 0


def test_the_other_hand_cannot_steal_or_drop_the_disc() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=1.0, who="Right", kind="pinch")
    assert scene.disc.attached
    assert scene.disc.holder == "Right"
    scene.apply_pointer(0.90, 0.90, True, t=1.1, who="Left", kind="pinch")
    assert scene.disc.x == 0.50
    assert scene.disc.holder == "Right"
    assert not scene.disc.scaler
    scene.apply_pointer(0.90, 0.90, False, t=1.2, who="Left", kind="open")
    assert scene.disc.attached
    scene.apply_pointer(0.55, 0.50, False, t=1.3, who="Right", kind="open")
    assert not scene.disc.attached


def test_two_detections_of_one_pinch_do_not_scale() -> None:
    """MediaPipe often emits Left+Right for one fist. That is not a stretch."""
    scene = _plane()
    r0 = scene.disc.radius
    scene.apply_pointer(0.50, 0.50, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(0.52, 0.50, True, t=1.0, who="Left", kind="pinch")
    assert not scene.disc.scaler
    assert scene.disc.attached
    assert scene.disc.radius == r0
    scene.apply_pointer(0.50, 0.50, True, t=1.06, who="Right", kind="pinch")
    scene.apply_pointer(0.58, 0.50, True, t=1.06, who="Left", kind="pinch")
    assert not scene.disc.scaler
    assert scene.disc.radius == r0


