"""LDR star look: a photosphere at true size, plus a camera flare.

The FBO is 8-bit, so this is not HDR bloom. The flare size comes from how
unresolved the disc is (a point source vs a resolved photosphere), not from
a viewport fill and not from a few R_sun of K-corona painted as a doughnut.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class StarFlare:
    """Pixel-space flare for one frame.

    disc_px: photosphere radius
    bloom_px: soft core around the disc (or the point)
    spike_px: diffraction length from the centre
    spike_gain: 0..1, never zero — close-up still has hairlines
    unresolved: 1 when the sun is a point, 0 when the disc fills the view
    """

    disc_px: float
    bloom_px: float
    spike_px: float
    spike_gain: float
    unresolved: float

    @property
    def extent_px(self) -> float:
        # Pad so the fade dies inside the mesh. A tight quad reads as a card.
        return max(self.spike_px, self.bloom_px, self.disc_px * 1.04) * 1.28


def angular_px(radius: float, depth: float, fb_h: int, fov_y: float) -> float:
    """Photosphere radius in pixels from the same FOV the viewport uses."""
    half = math.tan(max(float(fov_y), 1e-4) * 0.5)
    return float(radius) / max(float(depth), 1.0) / half * (max(int(fb_h), 1) * 0.5)


def star_flare(disc_px: float, fb_h: int) -> StarFlare:
    """Camera PSF + limb wash. Not an AU-scale sprite."""
    h = max(int(fb_h), 1)
    disc = max(float(disc_px), 0.0)
    unresolved = math.exp(-disc / 10.0)
    bloom = disc + min(7.5 - 5.0 * unresolved, 0.03 * h)
    spike = disc + min(28.0 - 18.0 * unresolved, 0.05 * h)
    gain = 0.52 + 0.42 * unresolved
    return StarFlare(disc, bloom, spike, gain, unresolved)
