"""Monocular z for rung 3. Declared estimator: pinhole + assumed palm.

MediaPipe Hands z is wrist-relative, not camera depth. Using it is the
leap-at-the-lens. This path uses 2D palm span (index MCP–pinky MCP)
against the C920 HFOV and a fixed adult palm. Relative, then mapped
into the world box. Metres are logged; the box is 0 = near, 1 = far.

A still wrist that changes palm span but not wrist–middle reach is a
twist. Hold z. A still wrist where palm and reach both grow or both
shrink vs the last committed span is a dolly — update z. A moving
wrist is XY. Palm and reach both change when you drag; that is not
closer. Take 20260823T224851Z slew hid it; without slew the ball
grew while the hand just translated. Rebase the still span while
the wrist moves so a later pause is not a fake punch. Slew is gone.
1€ still smooths a real punch.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from arelis.spatial.one_euro import OneEuro
from arelis.spatial.types import Hand

ESTIMATOR = "palm_pinhole"
# Index MCP to pinky MCP, adult. Not a cal. Bake-off winner until a take says no.
PALM_M = 0.085
# Logitech C920, canvas C920 truth.
C920_HFOV_DEG = 70.4
# Desk reach. Closer/farther than this still clamps — no shader infinity.
Z_M_NEAR = 0.22
Z_M_FAR = 1.05
STILL_WRIST = 0.035
# Cumulative scale vs the start of the still period, not one frame.
DOLLY_SCALE = 0.04
# Starter sphere in scene.py. Unity draw gain there so rest size is the radius.
Z_WORLD_REF = 0.42
Z_M_REF = Z_M_NEAR + (Z_M_FAR - Z_M_NEAR) * Z_WORLD_REF


def palm_span_xy(hand: Hand, *, aspect: float) -> float:
    """Palm width in units of frame width. y is aspect-corrected."""
    return hand.palm_span_xy(aspect=aspect)


def pinhole_z_m(span_xy: float, *, hfov_deg: float = C920_HFOV_DEG) -> float:
    """Camera-plane distance in metres from a width-normalized palm span."""
    span = max(float(span_xy), 1e-4)
    half = math.tan(math.radians(hfov_deg) / 2.0)
    return PALM_M / (2.0 * span * half)


def metres_to_world(z_m: float) -> float:
    """0 = near the lens, 1 = back of the box."""
    t = (float(z_m) - Z_M_NEAR) / (Z_M_FAR - Z_M_NEAR)
    return min(1.0, max(0.0, t))


def world_to_metres(z: float) -> float:
    """Inverse of metres_to_world. Clamped to the desk box."""
    depth = min(1.0, max(0.0, float(z)))
    return Z_M_NEAR + (Z_M_FAR - Z_M_NEAR) * depth


def world_to_apparent(radius: float, z: float) -> float:
    """Draw size from the same pinhole. Apparent ∝ 1/z_m. Floor is 0.22 m."""
    z_m = max(Z_M_NEAR, world_to_metres(z))
    return float(radius) * (Z_M_REF / z_m)


def _is_dolly(old_palm: float, new_palm: float, old_reach: float, new_reach: float) -> bool:
    """True when palm and wrist–middle MCP both grew or both shrank.

    A fist at the lens grows palm faster than reach. Matching ratios
    refused take 20260823T212326Z. Twist is reach that does not move.
    """
    if old_palm < 1e-4 or old_reach < 1e-4 or new_palm < 1e-4 or new_reach < 1e-4:
        return False
    palm_r = new_palm / old_palm
    reach_r = new_reach / old_reach
    if abs(palm_r - 1.0) < DOLLY_SCALE or abs(reach_r - 1.0) < DOLLY_SCALE:
        return False
    return (palm_r > 1.0) == (reach_r > 1.0)


@dataclass
class _Slot:
    filt: OneEuro = field(default_factory=lambda: OneEuro(min_cutoff=1.0, beta=0.007))
    wrist: tuple[float, float] | None = None
    z: float = 0.5
    t: float = -1.0
    span: float = 0.0
    reach: float = 0.0
    still_span: float = 0.0
    still_reach: float = 0.0


@dataclass
class DepthBank:
    """One z per named hand. Twist holds; a camera-axis dolly does not."""

    slots: dict[str, _Slot] = field(default_factory=dict)

    def reset(self) -> None:
        self.slots.clear()

    def observe(
        self,
        who: str,
        hand: Hand,
        *,
        t: float,
        width: int,
        height: int,
    ) -> float:
        aspect = float(width) / max(float(height), 1.0)
        span = palm_span_xy(hand, aspect=aspect)
        reach = hand.reach_span_xy(aspect=aspect)
        world = metres_to_world(pinhole_z_m(span))
        key = str(who or "") or "_"
        slot = self.slots.setdefault(key, _Slot())
        wrist = hand.xy(0)
        if slot.still_span < 1e-4:
            slot.wrist = wrist
            slot.span = span
            slot.reach = reach
            slot.still_span = span
            slot.still_reach = reach
            z = min(1.0, max(0.0, slot.filt(world, t)))
            slot.z = z
            slot.t = t
            return z
        moved = False
        if slot.wrist is not None:
            moved = math.hypot(wrist[0] - slot.wrist[0], wrist[1] - slot.wrist[1]) >= STILL_WRIST
        slot.wrist = wrist
        slot.span = span
        slot.reach = reach
        if moved:
            slot.still_span = span
            slot.still_reach = reach
            return slot.z
        if not _is_dolly(slot.still_span, span, slot.still_reach, reach):
            return slot.z
        z = min(1.0, max(0.0, slot.filt(world, t)))
        slot.z = z
        slot.t = t
        slot.still_span = span
        slot.still_reach = reach
        return z
