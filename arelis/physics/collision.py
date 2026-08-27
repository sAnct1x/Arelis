"""Catalog stop-spheres. No mesh, no DEM, no death.

Airless bodies: IAU mean radius. Worlds with air: mean radius plus a cited
envelope. Gas giants: the catalog radius is the 1-bar level.

Travel to warps the eye to ~8× IAU radius, which is outside this sphere.
WASD is a free camera and is not clipped. Massless probes are HUD sketches
and are not clipped either.

clip_relative / first_hit_on_segment stay as the tested definition of the
sphere. The live N-body no longer steps a vehicle through them.
"""

from __future__ import annotations

import math

from arelis.physics.constants import BODY_BY_NAME

# Metres *beyond* IAU mean radius. Giants stay at 1-bar (extra 0).
# Citations belong on the HUD.
ATMOSPHERE_M: dict[str, tuple[float, str]] = {
    "Earth": (100_000.0, "Karman line 100 km (FAI). LEO is above this."),
    "Venus": (200_000.0, "~200 km envelope; cloud tops ~70 km. No aero."),
    "Mars": (80_000.0, "~80 km envelope (homopause scale). No aero."),
    "Titan": (600_000.0, "haze to ~600 km. No aero."),
}


def stop_radius_m(name: str) -> tuple[float, str]:
    """Hard stop distance from body centre, plus a one-line citation."""
    spec = BODY_BY_NAME.get(name)
    if spec is None:
        return 0.0, "unknown body"
    extra, note = ATMOSPHERE_M.get(name, (0.0, "IAU mean radius (1-bar for giants)."))
    if extra <= 0.0:
        if spec.kind == "star":
            note = "photosphere (IAU nominal solar radius)."
        elif spec.kind in {"planet", "asteroid"} and spec.name not in ATMOSPHERE_M:
            if spec.name in {"Jupiter", "Saturn", "Uranus", "Neptune"}:
                note = "IAU 1-bar radius. That is the atmosphere, not rock."
            else:
                note = "IAU mean radius. No atmosphere envelope catalogued."
        else:
            note = "IAU mean radius. Airless."
    return spec.radius + extra, note


def clip_relative(
    px: float,
    py: float,
    pz: float,
    vx: float,
    vy: float,
    vz: float,
    bx: float,
    by: float,
    bz: float,
    bvx: float,
    bvy: float,
    bvz: float,
    r_stop: float,
    *,
    pad: float = 1.0,
) -> tuple[float, float, float, float, float, float, bool]:
    """Hold a test particle on the stop-sphere. Kill inward relative speed only."""
    dx, dy, dz = px - bx, py - by, pz - bz
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    limit = max(float(r_stop) + pad, 1.0)
    if dist >= limit:
        return px, py, pz, vx, vy, vz, False
    if dist < 1.0:
        dx, dy, dz, dist = 1.0, 0.0, 0.0, 1.0
    ux, uy, uz = dx / dist, dy / dist, dz / dist
    nx, ny, nz = bx + ux * limit, by + uy * limit, bz + uz * limit
    rvx, rvy, rvz = vx - bvx, vy - bvy, vz - bvz
    inward = rvx * ux + rvy * uy + rvz * uz
    if inward < 0.0:
        rvx -= inward * ux
        rvy -= inward * uy
        rvz -= inward * uz
    return nx, ny, nz, bvx + rvx, bvy + rvy, bvz + rvz, True


def first_hit_on_segment(
    x0: float,
    y0: float,
    z0: float,
    x1: float,
    y1: float,
    z1: float,
    bx: float,
    by: float,
    bz: float,
    r_stop: float,
    *,
    pad: float = 1.0,
) -> tuple[float, float, float, float] | None:
    """First contact of p0→p1 with the stop-sphere. Body fixed during the slice.

    Returns (t, ix, iy, iz) with t in [0, 1], or None if the segment misses.
    A start already inside is t=0 at p0.
    """
    limit = max(float(r_stop) + pad, 1.0)
    fx, fy, fz = x0 - bx, y0 - by, z0 - bz
    dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
    c = fx * fx + fy * fy + fz * fz - limit * limit
    if c <= 0.0:
        return 0.0, x0, y0, z0
    a = dx * dx + dy * dy + dz * dz
    if a < 1e-20:
        return None
    b = 2.0 * (fx * dx + fy * dy + fz * dz)
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None
    t = (-b - math.sqrt(disc)) / (2.0 * a)
    if t < 0.0 or t > 1.0:
        return None
    return t, x0 + t * dx, y0 + t * dy, z0 + t * dz
