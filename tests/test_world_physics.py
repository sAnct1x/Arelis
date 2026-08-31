"""Rung 2: g, throw, place, bounce. No camera."""

from __future__ import annotations

import time

from arelis.spatial.depth import world_to_apparent
from arelis.spatial.scene import GRAVITY, STILL_SPEED, Disc, WorldScene


def _plane(*bodies: Disc) -> WorldScene:
    """2D engine tests inject discs. The live stage is a sphere."""
    scene = WorldScene()
    scene.bodies = list(bodies) if bodies else [Disc()]
    return scene


def test_a_flick_releases_with_velocity() -> None:
    scene = _plane()
    scene.apply_pointer(0.40, 0.50, True, t=1.00)
    scene.apply_pointer(0.62, 0.50, True, t=1.10)
    scene.apply_pointer(0.62, 0.50, False, t=1.10)
    assert not scene.disc.attached
    assert scene.disc.vx > STILL_SPEED
    assert scene.last_release_speed == scene.disc.vx
    x0 = scene.disc.x
    scene.step(0.05)
    assert scene.disc.x > x0


def test_a_still_release_is_a_place() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=2.00)
    scene.apply_pointer(0.501, 0.500, True, t=2.10)
    scene.apply_pointer(0.501, 0.500, False, t=2.10)
    assert scene.disc.vx == 0.0
    assert scene.disc.vy == 0.0
    assert scene.last_release_speed == 0.0
    x0 = scene.disc.x
    y0 = scene.disc.y
    scene.step(0.20)
    assert abs(scene.disc.x - x0) < 1e-9
    assert scene.disc.y > y0


def test_a_drop_from_rest_falls() -> None:
    scene = _plane()
    scene.disc.y = 0.30
    scene.disc.vx = 0.0
    scene.disc.vy = 0.0
    y0 = scene.disc.y
    e0 = scene.energy()
    for _ in range(12):
        scene.step(0.016)
    assert scene.disc.y > y0
    assert abs(scene.disc.x - 0.5) < 1e-12
    assert scene.disc.vy > 0
    assert abs(scene.energy() - e0) < 0.02


def test_a_throw_arcs_under_g() -> None:
    scene = _plane()
    scene.disc.x = 0.25
    scene.disc.y = 0.55
    scene.disc.vx = 1.2
    scene.disc.vy = -1.6
    t = 0.0
    x0, y0 = scene.disc.x, scene.disc.y
    for _ in range(20):
        scene.step(0.02)
        t += 0.02
    coast_y = y0 + (-1.6) * t
    assert scene.disc.x > x0
    assert scene.disc.y > coast_y
    assert scene.disc.vy > -1.6


def test_held_disc_does_not_fall() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.40, True, t=1.0, who="Right", kind="fist")
    y0 = scene.disc.y
    scene.step(0.20)
    assert scene.disc.attached
    assert abs(scene.disc.y - y0) < 1e-12


def test_walls_reverse_velocity() -> None:
    scene = _plane()
    scene.disc.x = 0.90
    scene.disc.y = 0.50
    scene.disc.vx = 2.0
    scene.disc.vy = 0.0
    e0 = scene.energy()
    scene.step(0.02)
    assert scene.disc.vx < 0
    assert scene.disc.radius <= scene.disc.x <= 1.0 - scene.disc.radius + 1e-9
    assert scene.energy() < e0


def test_floor_bounce_loses_energy() -> None:
    scene = _plane()
    scene.disc.y = 0.85
    scene.disc.vy = 1.5
    e0 = scene.energy()
    scene.step(0.05)
    assert scene.disc.y <= 1.0 - scene.disc.radius + 1e-9
    assert scene.disc.vy <= 0
    assert scene.energy() < e0


def test_a_landed_place_sits() -> None:
    scene = _plane()
    scene.disc.y = 1.0 - scene.disc.radius
    scene.disc.vx = 0.0
    scene.disc.vy = 0.0
    for _ in range(8):
        scene.step(0.016)
    assert abs(scene.disc.y - (1.0 - scene.disc.radius)) < 1e-9
    assert scene.disc.vy == 0.0


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


def test_reset_kills_the_throw() -> None:
    scene = _plane()
    scene.apply_pointer(0.40, 0.50, True, t=0.0)
    scene.apply_pointer(0.70, 0.50, True, t=0.10)
    scene.apply_pointer(0.70, 0.50, False, t=0.10)
    scene.reset()
    assert scene.disc.vx == 0.0
    assert scene.disc.x == 0.5
    assert not scene.disc.attached


def test_far_pinch_does_not_steal_a_coasting_disc() -> None:
    scene = _plane()
    scene.disc.x = 0.20
    scene.disc.vx = 1.0
    scene.apply_pointer(0.90, 0.90, True, t=5.0)
    assert not scene.disc.attached
    assert scene.disc.vx == 1.0


def test_a_late_unpinch_still_throws_the_flick() -> None:
    """Unpinch used to wait so long the trail was a crawl, so the disc sat."""
    scene = _plane()
    scene.apply_pointer(0.40, 0.50, True, t=1.00, who="Right")
    scene.apply_pointer(0.70, 0.50, True, t=1.10, who="Right")
    scene.apply_pointer(0.70, 0.50, True, t=1.35, who="Right")
    scene.apply_pointer(0.70, 0.50, False, t=1.35, who="Right")
    assert not scene.disc.attached
    assert scene.disc.vx > STILL_SPEED


def test_the_same_hand_cannot_regrab_the_throw() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=1.00, who="Right")
    scene.apply_pointer(0.70, 0.50, True, t=1.10, who="Right")
    scene.apply_pointer(0.70, 0.50, False, t=1.10, who="Right")
    assert scene.disc.vx > 0
    scene.apply_pointer(0.70, 0.50, True, t=1.18, who="Right")
    assert not scene.disc.attached


def test_the_other_hand_cannot_steal_or_drop_the_disc() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=1.0, who="Right")
    assert scene.disc.attached
    assert scene.disc.holder == "Right"
    scene.apply_pointer(0.90, 0.90, True, t=1.1, who="Left")
    assert scene.disc.x == 0.50
    assert scene.disc.holder == "Right"
    assert not scene.disc.scaler
    scene.apply_pointer(0.90, 0.90, False, t=1.2, who="Left")
    assert scene.disc.attached
    scene.apply_pointer(0.55, 0.50, False, t=1.3, who="Right")
    assert not scene.disc.attached


def test_two_fists_do_not_scale_the_disc() -> None:
    scene = _plane()
    scene.apply_pointer(0.48, 0.50, True, t=1.0, who="Right", kind="fist")
    r0 = scene.disc.radius
    scene.apply_pointer(0.48, 0.50, True, t=1.1, who="Right", kind="fist")
    scene.apply_pointer(0.56, 0.50, True, t=1.1, who="Left", kind="fist")
    assert not scene.disc.scaler
    assert scene.disc.holder == "Right"
    assert scene.disc.radius == r0


def test_pinch_on_the_face_grabs() -> None:
    """One-hand pinch is XY grab. Two-pinch still scales."""
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=1.0, who="Right", kind="pinch")
    assert scene.disc.attached
    assert scene.disc.holder == "Right"
    assert not scene.disc.scaler


def test_one_pinch_does_not_scale() -> None:
    """Not a phone pinch-zoom. One hand never changes radius."""
    scene = _plane()
    r0 = scene.disc.radius
    scene.apply_pointer(0.50 + r0, 0.50, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(0.50 + 0.20, 0.50, True, t=1.06, who="Right", kind="pinch")
    assert scene.disc.attached
    assert scene.disc.radius == r0


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


def test_a_label_flip_does_not_become_a_second_pinch() -> None:
    scene = _plane()
    r0 = scene.disc.radius
    scene.apply_pointer(0.50, 0.50, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(0.50, 0.50, True, t=1.1, who="Left", kind="pinch")
    assert not scene.disc.scaler
    assert scene.disc.radius == r0
    assert scene.disc.holder == "Right"
    assert "Left" not in scene.held_names()


def test_a_fist_plus_a_pinch_does_not_scale() -> None:
    scene = _plane()
    scene.apply_pointer(0.48, 0.50, True, t=1.0, who="Right", kind="fist")
    r0 = scene.disc.radius
    scene.apply_pointer(0.56, 0.50, True, t=1.1, who="Left", kind="pinch")
    assert scene.disc.holder == "Right"
    assert not scene.disc.scaler
    assert scene.disc.radius == r0


def test_two_hands_scale_the_disc() -> None:
    scene = _plane()
    r0 = scene.disc.radius
    scene.apply_pointer(0.44, 0.50, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(0.56, 0.50, True, t=1.1, who="Left", kind="pinch")
    assert scene.disc.scaler == "Left"
    for i, span in enumerate((0.12, 0.16, 0.20, 0.26)):
        t = 1.2 + i * 0.03
        scene.apply_pointer(0.50 - span / 2, 0.50, True, t=t, who="Right", kind="pinch")
        scene.apply_pointer(0.50 + span / 2, 0.50, True, t=t, who="Left", kind="pinch")
    assert scene.disc.radius > r0


def test_two_hands_can_shrink_after_a_grow() -> None:
    """Size follows this frame vs last, not vs the join. Old join-lock
    made shrink after a grow almost impossible."""
    scene = _plane()
    scene.apply_pointer(0.44, 0.50, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(0.56, 0.50, True, t=1.1, who="Left", kind="pinch")
    for i, span in enumerate((0.14, 0.20, 0.28)):
        t = 1.2 + i * 0.03
        scene.apply_pointer(0.50 - span / 2, 0.50, True, t=t, who="Right", kind="pinch")
        scene.apply_pointer(0.50 + span / 2, 0.50, True, t=t, who="Left", kind="pinch")
    grown = scene.disc.radius
    for i, span in enumerate((0.20, 0.12, 0.06, 0.04)):
        t = 1.4 + i * 0.03
        scene.apply_pointer(0.50 - span / 2, 0.50, True, t=t, who="Right", kind="pinch")
        scene.apply_pointer(0.50 + span / 2, 0.50, True, t=t, who="Left", kind="pinch")
    assert scene.disc.radius < grown


def test_letting_go_one_pinch_ends_the_stretch() -> None:
    scene = _plane()
    scene.apply_pointer(0.44, 0.50, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(0.56, 0.50, True, t=1.1, who="Left", kind="pinch")
    scene.apply_pointer(0.56, 0.50, False, t=1.2, who="Left", kind="open")
    assert not scene.disc.attached
    assert not scene.disc.scaler
    assert scene.disc.vx == 0.0


def test_ending_scale_does_not_snap_onto_the_holder() -> None:
    """Two pinches meet in the middle. Releasing one must not jump the disc
    onto the remaining pinch."""
    scene = _plane()
    scene.disc.radius = 0.10
    scene.apply_pointer(0.40, 0.50, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(0.60, 0.50, True, t=1.1, who="Left", kind="pinch")
    mid = scene.disc.x
    scene.apply_pointer(0.60, 0.50, False, t=1.2, who="Left", kind="open")
    assert abs(scene.disc.x - mid) < 0.08
    assert abs(scene.disc.x - 0.40) > 0.02
    assert not scene.disc.attached


def test_a_second_stretch_still_joins_after_the_first() -> None:
    scene = _plane()
    scene.apply_pointer(0.44, 0.50, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(0.56, 0.50, True, t=1.1, who="Left", kind="pinch")
    for i, span in enumerate((0.16, 0.24, 0.32)):
        t = 1.2 + i * 0.03
        scene.apply_pointer(0.50 - span / 2, 0.50, True, t=t, who="Right", kind="pinch")
        scene.apply_pointer(0.50 + span / 2, 0.50, True, t=t, who="Left", kind="pinch")
    scene.apply_pointer(0.66, 0.50, False, t=1.4, who="Left", kind="open")
    grown = scene.disc.radius
    scene.apply_pointer(0.34, 0.50, True, t=1.41, who="Right", kind="pinch")
    scene.apply_pointer(0.66, 0.50, True, t=1.41, who="Left", kind="pinch")
    assert scene.disc.scaler == "Left"
    scene.apply_pointer(0.46, 0.50, True, t=1.50, who="Right", kind="pinch")
    scene.apply_pointer(0.54, 0.50, True, t=1.50, who="Left", kind="pinch")
    assert scene.disc.radius < grown


def test_a_lost_scaler_frame_does_not_end_the_stretch() -> None:
    scene = _plane()
    scene.apply_pointer(0.44, 0.50, True, t=2.0, who="Right", kind="pinch")
    scene.apply_pointer(0.56, 0.50, True, t=2.1, who="Left", kind="pinch")
    assert scene.disc.scaler == "Left"
    scene.drop(t=2.12, who="Left")
    assert scene.disc.scaler == "Left"
    scene.apply_pointer(0.44, 0.50, True, t=2.14, who="Right", kind="pinch")
    scene.apply_pointer(0.56, 0.50, True, t=2.14, who="Left", kind="pinch")
    assert scene.disc.scaler == "Left"
    scene.drop(t=2.16, who="Left")
    scene.apply_pointer(0.44, 0.50, True, t=2.40, who="Right", kind="pinch")
    assert not scene.disc.scaler


def test_a_still_hold_is_not_a_flick() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=1.00, who="Right", kind="fist")
    scene.apply_pointer(0.501, 0.500, True, t=1.10, who="Right", kind="fist")
    assert scene.disc.attached
    assert not scene.is_flicking()


def test_a_sling_is_a_flick() -> None:
    scene = _plane()
    scene.apply_pointer(0.40, 0.50, True, t=1.00, who="Right", kind="fist")
    scene.apply_pointer(0.62, 0.50, True, t=1.10, who="Right", kind="fist")
    assert scene.is_flicking()


def test_the_other_hand_can_catch_a_drop() -> None:
    scene = _plane()
    scene.apply_pointer(0.50, 0.50, True, t=1.00, who="Right", kind="fist")
    scene.apply_pointer(0.50, 0.50, False, t=1.10, who="Right", kind="open")
    assert not scene.disc.attached
    scene.apply_pointer(0.50, 0.50, True, t=1.12, who="Left", kind="fist")
    assert scene.disc.attached
    assert scene.disc.holder == "Left"


def test_two_fists_hold_two_discs() -> None:
    scene = _plane(Disc(), Disc(x=0.74, y=0.36))
    first, second = scene.bodies
    scene.apply_pointer(first.x, first.y, True, t=1.0, who="Right", kind="fist")
    scene.apply_pointer(second.x, second.y, True, t=1.0, who="Left", kind="fist")
    assert first.attached and first.holder == "Right"
    assert second.attached and second.holder == "Left"
    y0, y1 = first.y, second.y
    scene.step(0.20)
    assert first.y == y0
    assert second.y == y1


def test_the_second_disc_grabs_before_the_first_is_touched() -> None:
    """Disc 0 used to be the miss fallback, so disc 1 felt unborn."""
    scene = _plane(Disc(), Disc(x=0.74, y=0.36))
    first, second = scene.bodies
    scene.apply_pointer(second.x, second.y, True, t=1.0, who="Left", kind="fist")
    assert second.attached and second.holder == "Left"
    assert not first.attached


def test_a_miss_does_not_fall_through_to_the_first_disc() -> None:
    scene = _plane()
    scene.apply_pointer(0.08, 0.08, True, t=1.0, who="Left", kind="fist")
    assert not any(body.attached for body in scene.bodies)


def test_an_open_idle_hand_does_not_release_the_other_disc() -> None:
    scene = _plane(Disc(), Disc(x=0.74, y=0.36))
    first, second = scene.bodies
    scene.apply_pointer(second.x, second.y, True, t=1.0, who="Left", kind="fist")
    scene.apply_pointer(first.x, first.y, False, t=1.02, who="Right", kind="open")
    assert second.attached and second.holder == "Left"
    assert not first.attached


def test_two_pinches_stretch_one_disc_not_the_other() -> None:
    scene = _plane(Disc(), Disc(x=0.74, y=0.36))
    first, second = scene.bodies
    r1 = second.radius
    cx, cy = first.x, first.y
    scene.apply_pointer(cx - 0.06, cy, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(cx + 0.06, cy, True, t=1.1, who="Left", kind="pinch")
    assert first.scaler == "Left"
    for i, span in enumerate((0.14, 0.20, 0.26)):
        t = 1.2 + i * 0.03
        scene.apply_pointer(cx - span / 2, cy, True, t=t, who="Right", kind="pinch")
        scene.apply_pointer(cx + span / 2, cy, True, t=t, who="Left", kind="pinch")
    assert first.radius > 0.08
    assert second.radius == r1
    assert not second.attached


def test_the_sphere_grabs_in_z() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    assert sphere.kind == "sphere"
    scene.apply_pointer(
        sphere.x, sphere.y, True, t=1.0, who="Left", kind="fist", z=sphere.z
    )
    assert sphere.attached and sphere.holder == "Left"


def test_a_desk_z_still_grabs_without_a_leap() -> None:
    """Hands always have a z. The C920 at a desk is far. That must still grab."""
    scene = WorldScene()
    sphere = scene.bodies[0]
    z0 = sphere.z
    scene.apply_pointer(
        sphere.x, sphere.y, True, t=1.0, who="Left", kind="fist", z=0.95
    )
    assert sphere.attached and sphere.holder == "Left"
    assert abs(sphere.z - z0) < 1e-6


def test_a_free_sphere_falls() -> None:
    """Rung 4. g is on the plane. z is size, not a drop axis."""
    scene = WorldScene()
    sphere = scene.bodies[0]
    y0, z0 = sphere.y, sphere.z
    scene.step(0.40)
    assert sphere.y > y0
    assert sphere.z == z0


def test_a_held_sphere_does_not_fall() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    z = sphere.z
    scene.apply_pointer(sphere.x, sphere.y, True, t=1.0, who="Right", kind="fist", z=z)
    y0 = sphere.y
    scene.step(0.20)
    assert sphere.attached
    assert abs(sphere.y - y0) < 1e-12
    assert sphere.z == z


def test_a_dropped_sphere_falls_on_the_plane() -> None:
    """Let go still. It drops. z does not leap."""
    scene = WorldScene()
    sphere = scene.bodies[0]
    z = sphere.z
    scene.apply_pointer(sphere.x, sphere.y, True, t=1.00, who="Right", kind="fist", z=z)
    scene.apply_pointer(sphere.x, sphere.y, True, t=1.10, who="Right", kind="fist", z=z)
    x1, y1 = sphere.x, sphere.y
    scene.apply_pointer(x1, y1, False, t=1.10, who="Right", kind="open", z=z)
    assert not sphere.attached
    assert sphere.vx == 0.0 and sphere.vy == 0.0
    scene.step(0.20)
    assert sphere.x == x1
    assert sphere.y > y1
    assert sphere.z == z


def test_a_sphere_bounce_does_not_change_z() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    z0 = sphere.z
    sphere.y = 0.85
    sphere.vy = 1.5
    scene.step(0.05)
    assert sphere.y <= 1.0 - sphere.radius + 1e-9
    assert sphere.vy <= 0
    assert sphere.z == z0


def test_a_sphere_on_the_floor_is_still_grabbable() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    sphere.y = 1.0 - sphere.radius
    sphere.vy = 0.0
    scene.apply_pointer(
        sphere.x, sphere.y, True, t=1.0, who="Right", kind="fist", z=sphere.z
    )
    assert sphere.attached


def test_a_near_sphere_rests_on_its_silhouette() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    sphere.z = 0.0
    sphere.y = 0.92
    sphere.vy = 0.8
    scene.step(0.05)
    drawn = world_to_apparent(sphere.radius, 0.0)
    assert sphere.y <= 1.0 - drawn + 1e-9
    scene.apply_pointer(
        sphere.x, sphere.y, True, t=1.0, who="Left", kind="fist", z=0.0
    )
    assert sphere.attached


def test_a_far_sphere_is_grabbable_at_its_solid_radius() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    sphere.z = 1.0
    scene.apply_pointer(
        sphere.x + sphere.radius * 0.8,
        sphere.y,
        True,
        t=1.0,
        who="Right",
        kind="fist",
        z=1.0,
    )
    assert sphere.attached


def test_a_held_sphere_keeps_sliding_across_a_short_lag() -> None:
    """Take 20260823T215537Z: pose skipped ~200 ms while the fist still held."""
    scene = WorldScene()
    sphere = scene.bodies[0]
    z = sphere.z
    scene.apply_pointer(0.40, 0.50, True, t=1.00, who="Right", kind="fist", z=z)
    scene.apply_pointer(0.55, 0.50, True, t=1.10, who="Right", kind="fist", z=z)
    x0 = sphere.x
    sphere._pointer_wall = time.perf_counter() - 0.10
    scene.step(0.05)
    assert sphere.x > x0
    assert sphere.attached


def test_a_long_lag_does_not_invent_motion() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    z = sphere.z
    scene.apply_pointer(0.40, 0.50, True, t=1.00, who="Right", kind="fist", z=z)
    scene.apply_pointer(0.55, 0.50, True, t=1.10, who="Right", kind="fist", z=z)
    x0 = sphere.x
    sphere._pointer_wall = time.perf_counter() - 0.40
    scene.step(0.05)
    assert sphere.x == x0


def test_a_resume_after_a_hitch_does_not_teleport() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    z = sphere.z
    scene.apply_pointer(sphere.x, sphere.y, True, t=1.00, who="Right", kind="fist", z=z)
    scene.apply_pointer(
        sphere.x + 0.02, sphere.y, True, t=1.02, who="Right", kind="fist", z=z
    )
    x0 = sphere.x
    scene.apply_pointer(0.95, sphere.y, True, t=1.17, who="Right", kind="fist", z=z)
    # 0.15 s × XY_SLEW 2.0 = 0.30 cap. Raw clamp jump is ~0.34.
    assert sphere.x - x0 <= 0.31
    assert sphere.x > x0


def test_two_pinches_stretch_the_sphere() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    r0 = sphere.radius
    cx, cy = sphere.x, sphere.y
    scene.apply_pointer(cx - 0.06, cy, True, t=1.0, who="Right", kind="pinch", z=0.9)
    scene.apply_pointer(cx + 0.06, cy, True, t=1.1, who="Left", kind="pinch", z=0.9)
    assert sphere.scaler == "Left"
    for i, span in enumerate((0.14, 0.20, 0.26)):
        t = 1.2 + i * 0.03
        scene.apply_pointer(cx - span / 2, cy, True, t=t, who="Right", kind="pinch", z=0.9)
        scene.apply_pointer(cx + span / 2, cy, True, t=t, who="Left", kind="pinch", z=0.9)
    assert sphere.radius > r0


def test_a_held_sphere_follows_z() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    scene.apply_pointer(
        sphere.x, sphere.y, True, t=1.00, who="Right", kind="fist", z=sphere.z
    )
    scene.apply_pointer(
        sphere.x, sphere.y, True, t=1.05, who="Right", kind="fist", z=0.22
    )
    assert sphere.attached
    assert abs(sphere.z - 0.22) < 1e-6
    scene.apply_pointer(
        sphere.x, sphere.y, True, t=1.10, who="Right", kind="fist", z=0.05
    )
    assert abs(sphere.z - 0.05) < 1e-6


def test_take_row_names_z() -> None:
    scene = WorldScene()
    row = scene.to_log()
    assert row["kind"] == "sphere"
    assert "z" in row
    assert len(row["bodies"]) == 1
    assert row["bodies"][0]["kind"] == "sphere"
    assert "z" in row["bodies"][0]


def test_spawn_adds_a_triangle() -> None:
    scene = WorldScene()
    tri = scene.spawn("triangle")
    assert tri is not None
    assert tri.sides == 3
    assert tri.kind == "triangle"
    assert len(scene.bodies) == 2


def test_a_spawned_triangle_is_grabbable() -> None:
    scene = WorldScene()
    scene.set_gravity(False)
    tri = scene.spawn("triangle")
    assert tri is not None
    scene.apply_pointer(tri.x, tri.y, True, t=1.0, who="Right", kind="fist")
    assert tri.attached


def test_two_bodies_bounce_off_each_other() -> None:
    scene = WorldScene()
    scene.set_gravity(False)
    a = scene.bodies[0]
    a.x, a.y = 0.40, 0.50
    a.vx, a.vy = 0.8, 0.0
    b = scene.spawn("triangle")
    assert b is not None
    b.x, b.y = 0.58, 0.50
    b.vx, b.vy = -0.8, 0.0
    scene.step(0.05)
    assert a.vx < 0.8
    assert b.vx > -0.8


def test_gravity_off_hangs_a_free_body() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    sphere.y = 0.40
    sphere.vy = 0.4
    scene.set_gravity(False)
    assert sphere.vy == 0.0
    y0 = sphere.y
    scene.step(0.20)
    assert abs(sphere.y - y0) < 1e-9


def test_left_pick_targets() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    assert scene.select_at(sphere.x, sphere.y) is sphere
    assert scene.selected is sphere


def test_delete_removes_a_spawned_body() -> None:
    scene = WorldScene()
    tri = scene.spawn("triangle")
    scene.selected = tri
    assert scene.delete()
    assert tri not in scene.bodies
    assert len(scene.bodies) == 1


def test_size_lock_blocks_stretch() -> None:
    scene = WorldScene()
    scene.set_gravity(False)
    sphere = scene.bodies[0]
    r0 = sphere.radius
    sphere.size_locked = True
    cx, cy = sphere.x, sphere.y
    scene.apply_pointer(cx - 0.06, cy, True, t=1.0, who="Right", kind="pinch", z=0.9)
    scene.apply_pointer(cx + 0.06, cy, True, t=1.1, who="Left", kind="pinch", z=0.9)
    scene.apply_pointer(cx - 0.13, cy, True, t=1.2, who="Right", kind="pinch", z=0.9)
    scene.apply_pointer(cx + 0.13, cy, True, t=1.2, who="Left", kind="pinch", z=0.9)
    assert sphere.radius == r0


def test_delete_last_body_leaves_the_box_empty() -> None:
    scene = WorldScene()
    sphere = scene.bodies[0]
    scene.selected = sphere
    assert scene.delete()
    assert scene.bodies == []
    scene.apply_pointer(0.5, 0.5, True, t=1.0, who="Right", kind="fist")
    assert scene.bodies == []
    row = scene.to_log()
    assert row["bodies"] == []
    assert row["kind"] == ""


def test_two_pinches_rotate_a_triangle() -> None:
    scene = WorldScene()
    scene.set_gravity(False)
    tri = scene.spawn("triangle")
    assert tri is not None
    a0 = tri.angle
    cx, cy = tri.x, tri.y
    scene.apply_pointer(cx - 0.06, cy, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(cx + 0.06, cy, True, t=1.1, who="Left", kind="pinch")
    scene.apply_pointer(cx, cy - 0.06, True, t=1.2, who="Right", kind="pinch")
    scene.apply_pointer(cx, cy + 0.06, True, t=1.2, who="Left", kind="pinch")
    assert abs(tri.angle - a0) > 0.5
    assert tri.sides == 3


def test_size_lock_one_pinch_rotates_without_grow() -> None:
    scene = WorldScene()
    scene.set_gravity(False)
    sphere = scene.bodies[0]
    r0 = sphere.radius
    a0 = sphere.angle
    sphere.size_locked = True
    cx, cy = sphere.x, sphere.y
    scene.apply_pointer(cx + 0.08, cy, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(cx, cy + 0.08, True, t=1.1, who="Right", kind="pinch")
    assert sphere.radius == r0
    assert not sphere.attached
    assert abs(sphere.angle - a0) > 0.5


def test_size_lock_two_pinches_rotate_without_grow() -> None:
    scene = WorldScene()
    scene.set_gravity(False)
    sphere = scene.bodies[0]
    r0 = sphere.radius
    x0, y0 = sphere.x, sphere.y
    a0 = sphere.angle
    sphere.size_locked = True
    cx, cy = sphere.x, sphere.y
    scene.apply_pointer(cx - 0.06, cy, True, t=1.0, who="Right", kind="pinch")
    scene.apply_pointer(cx + 0.06, cy, True, t=1.1, who="Left", kind="pinch")
    scene.apply_pointer(cx, cy - 0.06, True, t=1.2, who="Right", kind="pinch")
    scene.apply_pointer(cx, cy + 0.06, True, t=1.2, who="Left", kind="pinch")
    assert sphere.radius == r0
    assert abs(sphere.x - x0) < 1e-9
    assert abs(sphere.y - y0) < 1e-9
    assert abs(sphere.angle - a0) > 0.5
