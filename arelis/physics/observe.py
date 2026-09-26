"""The camera is an observer. It is not a body.

Physics keeps the true state: IAS15, GMST, catalogs, clocks. Measure
anything at any time. The plate only spends a frame when the observer
would notice — `NOTICE_PX` of screen motion since the last commit.

Distance changes the rate (same ω, more pixels). Time accumulates:
leave Reality open overnight and the terminator eventually crosses the
budget, then one correct frame. Sleep the process and the first wake
has a huge dt — same one frame, current physics.
"""

from __future__ import annotations

import math

# Half a pixel. Below this the observer cannot tell a new frame from the last.
NOTICE_PX = 0.5


def accumulated_px(px_s: float, dt_s: float) -> float:
    """Screen motion in pixels over a sim interval. Physics is not scaled."""
    return max(0.0, float(px_s)) * max(0.0, float(dt_s))


def time_to_notice(px_s: float, notice: float = NOTICE_PX) -> float:
    """Sim seconds until `px_s` crawls `notice` pixels. inf if it never will."""
    rate = max(float(px_s), 0.0)
    if rate <= 1e-12:
        return float("inf")
    return float(notice) / rate


def due(*, px_s: float, dt_s: float, notice: float = NOTICE_PX) -> bool:
    """True when the observer would see a change. False is not a pause."""
    return accumulated_px(px_s, dt_s) >= float(notice)


def spin_px_s(px_r: float, omega_rad_s: float) -> float:
    """Texture / terminator crawl on a disc. Same ω, more pixels when closer."""
    return max(0.0, float(px_r)) * abs(float(omega_rad_s))


def orbit_px_s(*, speed_m_s: float, depth_m: float, scale: float) -> float:
    """On-screen slide of a body vs an inertial eye. Same estimator as the plate."""
    return (max(0.0, float(speed_m_s)) / max(float(depth_m), 1.0)) * max(
        0.0, float(scale)
    )


def clock_step_s(px_s: float, *, cap_s: float = 3600.0, floor_s: float = 1.0) -> float:
    """Bin width for `system.t` in a frame cache. One bin ≈ one noticeable crawl."""
    dt = time_to_notice(px_s)
    if not math.isfinite(dt) or dt >= cap_s:
        return cap_s
    return max(floor_s, dt)
