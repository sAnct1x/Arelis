"""Rung 3 z: pinhole + assumed palm. MediaPipe z is not camera depth."""

from __future__ import annotations

from arelis.spatial.depth import (
    ESTIMATOR,
    Z_M_FAR,
    Z_M_NEAR,
    Z_M_REF,
    DepthBank,
    metres_to_world,
    pinhole_z_m,
    world_to_apparent,
    world_to_metres,
)
from arelis.spatial.types import Hand, Landmark


def _span_hand(span: float, *, origin: tuple[float, float] = (0.40, 0.40)) -> Hand:
    ox, oy = origin
    pts = [(ox, oy, 0.0)] * 21
    pts[5] = (ox, oy, 0.0)
    pts[17] = (ox + span, oy, 0.0)
    lms = tuple(Landmark(x=p[0], y=p[1], z=p[2], name=str(i)) for i, p in enumerate(pts))
    return Hand(label="Right", landmarks=lms, score=1.0)


def _dolly_hand(scale: float, *, origin: tuple[float, float] = (0.40, 0.40)) -> Hand:
    """Palm and wrist–middle MCP scale together. Wrist stays put."""
    ox, oy = origin
    pts = [(ox, oy, 0.0)] * 21
    pts[5] = (ox + 0.06 * scale, oy, 0.0)
    pts[9] = (ox, oy + 0.10 * scale, 0.0)
    pts[17] = (ox + 0.14 * scale, oy, 0.0)
    lms = tuple(Landmark(x=p[0], y=p[1], z=p[2], name=str(i)) for i, p in enumerate(pts))
    return Hand(label="Right", landmarks=lms, score=1.0)


def _twist_hand(*, palm: float, reach: float) -> Hand:
    ox, oy = 0.40, 0.40
    pts = [(ox, oy, 0.0)] * 21
    pts[5] = (ox, oy, 0.0)
    pts[9] = (ox, oy + reach, 0.0)
    pts[17] = (ox + palm, oy, 0.0)
    lms = tuple(Landmark(x=p[0], y=p[1], z=p[2], name=str(i)) for i, p in enumerate(pts))
    return Hand(label="Right", landmarks=lms, score=1.0)


def test_estimator_is_declared() -> None:
    assert ESTIMATOR == "palm_pinhole"


def test_a_larger_palm_is_nearer() -> None:
    near = pinhole_z_m(0.20)
    far = pinhole_z_m(0.05)
    assert near < far
    assert metres_to_world(near) < metres_to_world(far)


def test_apparent_size_is_the_pinhole() -> None:
    """Size × metres is constant. Linear z was take 20260823T213944Z: 1.75×."""
    assert world_to_apparent(0.08, 0.0) > world_to_apparent(0.08, 1.0)
    assert abs(world_to_apparent(0.14, 0.42) - 0.14) < 1e-12
    assert abs(world_to_apparent(0.14, 0.0) - 0.14 * Z_M_REF / Z_M_NEAR) < 1e-12
    assert abs(world_to_apparent(0.14, 1.0) - 0.14 * Z_M_REF / Z_M_FAR) < 1e-12
    a = world_to_apparent(0.14, 0.0) * world_to_metres(0.0)
    b = world_to_apparent(0.14, 0.73) * world_to_metres(0.73)
    assert abs(a - b) < 1e-12


def test_apparent_span_on_the_213944_take_follows_1_over_z() -> None:
    """That take: z 0→0.73. Draw must follow metres, not a straight line."""
    near = world_to_apparent(0.14, 0.0)
    far = world_to_apparent(0.14, 0.73)
    old_line = (1.45 - 0.85 * 0.0) / (1.45 - 0.85 * 0.73)
    assert near / far > old_line
    assert abs((near / far) - (world_to_metres(0.73) / Z_M_NEAR)) < 1e-9


def test_a_still_wrist_holds_z_when_span_changes() -> None:
    """A twist changes palm span. That is not a dolly."""
    bank = DepthBank()
    z0 = bank.observe("Right", _span_hand(0.18), t=1.00, width=1280, height=720)
    z1 = bank.observe("Right", _span_hand(0.09), t=1.10, width=1280, height=720)
    assert z1 == z0


def test_a_twist_with_reach_still_holds_z() -> None:
    """Palm span changes, wrist–middle does not. Still a twist."""
    bank = DepthBank()
    z0 = bank.observe(
        "Right", _twist_hand(palm=0.18, reach=0.10), t=1.00, width=1280, height=720
    )
    z1 = bank.observe(
        "Right", _twist_hand(palm=0.09, reach=0.10), t=1.10, width=1280, height=720
    )
    assert z1 == z0


def test_a_dolly_with_a_still_wrist_updates_z() -> None:
    """Take 20260823T210302Z: push at the C920, wrist still in the image, z glued."""
    bank = DepthBank()
    z0 = bank.observe("Right", _dolly_hand(1.0), t=1.00, width=1280, height=720)
    z1 = bank.observe("Right", _dolly_hand(1.6), t=1.20, width=1280, height=720)
    assert z1 < z0


def test_a_fist_dolly_palm_outpaces_reach() -> None:
    """Take 20260823T212326Z: palm 2.16×, reach 1.44×. Matching ratios refused."""
    bank = DepthBank()
    z0 = bank.observe(
        "Right", _twist_hand(palm=0.044, reach=0.078), t=1.00, width=1280, height=720
    )
    z1 = bank.observe(
        "Right", _twist_hand(palm=0.096, reach=0.112), t=1.20, width=1280, height=720
    )
    assert z1 < z0


def test_a_moving_hand_does_not_change_z_without_a_dolly() -> None:
    """XY drag changes palm in the image. That is not closer."""
    bank = DepthBank()
    z0 = bank.observe(
        "Right", _span_hand(0.12, origin=(0.40, 0.40)), t=1.00, width=1280, height=720
    )
    z1 = bank.observe(
        "Right", _span_hand(0.18, origin=(0.55, 0.42)), t=1.10, width=1280, height=720
    )
    assert z1 == z0


def test_a_dolly_while_the_wrist_moves_holds_z() -> None:
    """XY drag scales palm and reach together. That is still not closer."""
    bank = DepthBank()
    z0 = bank.observe(
        "Right", _dolly_hand(1.0, origin=(0.40, 0.40)), t=1.00, width=1280, height=720
    )
    z1 = bank.observe(
        "Right", _dolly_hand(1.6, origin=(0.52, 0.40)), t=1.20, width=1280, height=720
    )
    assert z1 == z0


def test_a_pull_back_after_a_dolly_updates_z() -> None:
    bank = DepthBank()
    z0 = bank.observe("Right", _dolly_hand(1.0), t=1.00, width=1280, height=720)
    z1 = bank.observe("Right", _dolly_hand(1.8), t=1.30, width=1280, height=720)
    z2 = bank.observe("Right", _dolly_hand(1.0), t=1.60, width=1280, height=720)
    assert z1 < z0
    assert z2 > z1


def test_a_fast_push_is_not_capped_to_a_crawl() -> None:
    """Take 20260823T224851Z: mean |world−raw| 0.33. Slew 0.55 was the freeze."""
    bank = DepthBank()
    z0 = bank.observe("Right", _dolly_hand(1.0), t=1.00, width=1280, height=720)
    z1 = bank.observe("Right", _dolly_hand(1.8), t=1.30, width=1280, height=720)
    assert z1 < z0
    assert (z0 - z1) > 0.55 * 0.30
