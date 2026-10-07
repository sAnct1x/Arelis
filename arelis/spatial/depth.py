"""Monocular z for rung 3. Declared estimator: pinhole + assumed palm.

MediaPipe Hands z is wrist-relative, not camera depth. Using it is the
leap-at-the-lens. This path uses 2D palm span (index MCP–pinky MCP)
against the C920 HFOV and a fixed adult palm. Relative, then mapped
into the world box. Metres are logged; the box is 0 = near, 1 = far.

Live z is a ratio off rest, not an absolute pinhole. A pinch
foreshortens the palm, and that small span used to read as a metre
away, so the ball sat on the far wall. Rest starts at Z_WORLD_REF.
Both bones growing is closer, including while the hand also slides.
A twist, or the wrist–middle bone turning, rebases and holds z.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from arelis.spatial.one_euro import depth_euro
from arelis.spatial.types import Hand

if TYPE_CHECKING:
    from arelis.spatial.one_euro import OneEuro

# Past this, the hand turned. Span change is foreshortening, not a punch.
YAW_HOLD = 0.22
# One accepted step. Stops a glitch span from crossing the box.
RATIO_CAP = 1.12

ESTIMATOR = "palm_pinhole"
# Index MCP to pinky MCP, adult. Not a cal. Bake-off winner until a take says no.
PALM_M = 0.085
# Logitech C920, canvas C920 truth.
C920_HFOV_DEG = 70.4
# Desk reach. Closer/farther than this still clamps — no shader infinity.
Z_M_NEAR = 0.22
Z_M_FAR = 1.05
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


def _wrap(delta: float) -> float:
    while delta > math.pi:
        delta -= 2.0 * math.pi
    while delta < -math.pi:
        delta += 2.0 * math.pi
    return delta


def _rebase(slot: _Slot, span: float, reach: float, aim: float) -> None:
    slot.still_span = span
    slot.still_reach = reach
    slot.still_aim = aim


def _is_twist(old_palm: float, new_palm: float, old_reach: float, new_reach: float) -> bool:
    """One bone changed, or they changed opposite ways. Not a punch."""
    if old_palm < 1e-4 or old_reach < 1e-4 or new_palm < 1e-4 or new_reach < 1e-4:
        return False
    palm_r = new_palm / old_palm
    reach_r = new_reach / old_reach
    palm_moved = abs(palm_r - 1.0) >= DOLLY_SCALE
    reach_moved = abs(reach_r - 1.0) >= DOLLY_SCALE
    if palm_moved and reach_moved:
        return (palm_r > 1.0) != (reach_r > 1.0)
    return palm_moved or reach_moved


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
    filt: OneEuro = field(default_factory=depth_euro)
    wrist: tuple[float, float] | None = None
    z: float = Z_WORLD_REF
    t: float = -1.0
    span: float = 0.0
    reach: float = 0.0
    still_span: float = 0.0
    still_reach: float = 0.0
    still_aim: float = 0.0


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
        aim = hand.aim_angle()
        key = str(who or "") or "_"
        slot = self.slots.setdefault(key, _Slot())
        wrist = hand.xy(0)
        if slot.t < 0 or slot.still_span < 1e-4:
            slot.wrist = wrist
            slot.span = span
            slot.reach = reach
            slot.still_span = span
            slot.still_reach = reach
            slot.still_aim = aim
            slot.z = Z_WORLD_REF
            slot.t = t
            slot.filt(slot.z, t)
            return slot.z
        slot.wrist = wrist
        slot.span = span
        slot.reach = reach
        if abs(_wrap(aim - slot.still_aim)) >= YAW_HOLD:
            _rebase(slot, span, reach, aim)
            return slot.z
        if _is_dolly(slot.still_span, span, slot.still_reach, reach):
            palm_r = span / slot.still_span
            reach_r = reach / slot.still_reach
            ratio = min(RATIO_CAP, max(1.0 / RATIO_CAP, (palm_r + reach_r) / 2.0))
            z_m = world_to_metres(slot.z) / ratio
            slot.z = min(1.0, max(0.0, slot.filt(metres_to_world(z_m), t)))
            slot.t = t
            _rebase(slot, span, reach, aim)
            return slot.z
        if _is_twist(slot.still_span, span, slot.still_reach, reach):
            _rebase(slot, span, reach, aim)
        return slot.z
