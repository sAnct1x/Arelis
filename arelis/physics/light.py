"""Sunlight as a finite disk. Occluders cut umbra and penumbra.

Sky geometry, not a photon Monte Carlo. Night is dark. Software globes
and the GL shader share these fractions.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from arelis.physics.constants import BODY_BY_NAME

# Probes are 5 m. They do not eclipse a planet.
_MIN_OCC_R = 1.0e5
MAX_OCCLUDERS = 8
R_SUN = BODY_BY_NAME["Sun"].radius
_MOON_A_M = 384_399_000.0

Occ = tuple[float, float, float, float]


def _circle_overlap(r: np.ndarray, R: np.ndarray, d: np.ndarray) -> np.ndarray:
    """Intersection area of two circles, radii r and R, centre distance d."""
    r = np.asarray(r, dtype=np.float64)
    R = np.asarray(R, dtype=np.float64)
    d = np.asarray(d, dtype=np.float64)
    out = np.zeros(np.broadcast(r, R, d).shape, dtype=np.float64)
    none = d >= (r + R) - 1.0e-15
    inside = d <= np.abs(R - r) + 1.0e-15
    part = ~(none | inside)
    out[inside] = math.pi * np.minimum(r[inside], R[inside]) ** 2
    if not np.any(part):
        return out
    rp, Rp, dp = r[part], R[part], np.maximum(d[part], 1.0e-15)
    r2, R2, d2 = rp * rp, Rp * Rp, dp * dp
    a = np.clip((d2 + r2 - R2) / (2.0 * dp * rp), -1.0, 1.0)
    b = np.clip((d2 + R2 - r2) / (2.0 * dp * Rp), -1.0, 1.0)
    k = (-dp + rp + Rp) * (dp + rp - Rp) * (dp - rp + Rp) * (dp + rp + Rp)
    out[part] = r2 * np.arccos(a) + R2 * np.arccos(b) - 0.5 * np.sqrt(np.maximum(k, 0.0))
    return out


def _cover_frac(alpha: np.ndarray, beta: np.ndarray, sep: np.ndarray) -> np.ndarray:
    """Fraction of the solar disk (radius alpha) covered by an occluder (beta)."""
    alpha = np.maximum(np.asarray(alpha, dtype=np.float64), 1.0e-18)
    beta = np.asarray(beta, dtype=np.float64)
    sep = np.asarray(sep, dtype=np.float64)
    cover = np.zeros(alpha.shape, dtype=np.float64)
    total = (beta >= alpha) & (sep <= (beta - alpha))
    cover[total] = 1.0
    annular = (alpha > beta) & (sep <= (alpha - beta))
    cover[annular] = (beta[annular] / alpha[annular]) ** 2
    part = ~((sep >= alpha + beta) | total | annular)
    if np.any(part):
        area = _circle_overlap(alpha[part], beta[part], sep[part])
        cover[part] = np.clip(area / (math.pi * alpha[part] ** 2), 0.0, 1.0)
    return cover


def sun_lit_fraction(
    x: float | np.ndarray,
    y: float | np.ndarray,
    z: float | np.ndarray,
    sun: tuple[float, float, float],
    occluders: Sequence[Occ],
    *,
    sun_radius: float = R_SUN,
) -> np.ndarray:
    """1 = full solar disk, 0 = umbra. Penumbra is the open interval."""
    xa = np.asarray(x, dtype=np.float64)
    ya = np.asarray(y, dtype=np.float64)
    za = np.asarray(z, dtype=np.float64)
    shape = np.broadcast_shapes(xa.shape, ya.shape, za.shape)
    x = np.broadcast_to(xa, shape).reshape(-1)
    y = np.broadcast_to(ya, shape).reshape(-1)
    z = np.broadcast_to(za, shape).reshape(-1)
    sx, sy, sz = sun
    dx, dy, dz = sx - x, sy - y, sz - z
    d_sun = np.maximum(np.sqrt(dx * dx + dy * dy + dz * dz), 1.0)
    ux, uy, uz = dx / d_sun, dy / d_sun, dz / d_sun
    alpha = np.arcsin(np.clip(sun_radius / d_sun, 0.0, 1.0))
    vis = np.ones(x.shape, dtype=np.float64)
    for ox, oy, oz, rad in occluders:
        if rad <= 0.0:
            continue
        oxd, oyd, ozd = ox - x, oy - y, oz - z
        d_o = np.maximum(np.sqrt(oxd * oxd + oyd * oyd + ozd * ozd), 1.0)
        in_front = d_o < d_sun
        buried = d_o <= rad
        oxn, oyn, ozn = oxd / d_o, oyd / d_o, ozd / d_o
        cos = np.clip(ux * oxn + uy * oyn + uz * ozn, -1.0, 1.0)
        facing = cos > 0.0
        sep = np.arccos(cos)
        beta = np.arcsin(np.clip(rad / d_o, 0.0, 1.0))
        hit = in_front & facing & ~buried
        cover = np.zeros_like(vis)
        if np.any(hit):
            cover[hit] = _cover_frac(alpha[hit], beta[hit], sep[hit])
        cover[buried] = 1.0
        vis = vis * (1.0 - cover)
    return vis.reshape(shape)


def sun_lit_at(
    point: tuple[float, float, float],
    sun: tuple[float, float, float],
    occluders: Sequence[Occ],
    *,
    sun_radius: float = R_SUN,
) -> float:
    return float(
        np.asarray(
            sun_lit_fraction(
                point[0], point[1], point[2], sun, occluders, sun_radius=sun_radius
            )
        )
    )


def earthshine_scale(
    moon: tuple[float, float, float],
    earth: tuple[float, float, float],
    sun: tuple[float, float, float],
) -> float:
    """Earth as a Lambert bounce on the Moon. Brightest at new Moon, ~0 at full."""
    mx, my, mz = moon
    ex, ey, ez = earth
    sx, sy, sz = sun
    emx, emy, emz = mx - ex, my - ey, mz - ez
    esx, esy, esz = sx - ex, sy - ey, sz - ez
    em = math.hypot(emx, emy, emz) or 1.0
    es = math.hypot(esx, esy, esz) or 1.0
    cos = max(-1.0, min(1.0, (emx * esx + emy * esy + emz * esz) / (em * es)))
    phase = 0.5 * (1.0 + cos)
    return 0.03 * phase * (_MOON_A_M / em) ** 2


def occluders_for(
    body_name: str,
    body_xyz: tuple[float, float, float],
    particles: Sequence[object],
    sun: object | None,
    *,
    parent: str | None = None,
) -> list[Occ]:
    """Spheres that can cover the solar disk as seen from this body."""
    if sun is None or body_name == "Sun":
        return []
    bx, by, bz = body_xyz
    d_sun = math.hypot(sun.x - bx, sun.y - by, sun.z - bz) or 1.0
    sun_ang = math.asin(min(1.0, R_SUN / d_sun))
    ranked: list[tuple[float, Occ]] = []
    for p in particles:
        if getattr(p, "tracer", False) or p.name in {body_name, "Sun"}:
            continue
        rad = float(p.radius)
        if rad < _MIN_OCC_R:
            continue
        d = math.hypot(p.x - bx, p.y - by, p.z - bz)
        if d < 1.0:
            continue
        ang = math.asin(min(1.0, rad / d))
        is_family = parent == p.name or getattr(p, "parent", None) == body_name
        if not is_family and ang < 0.12 * sun_ang:
            continue
        ranked.append((ang, (float(p.x), float(p.y), float(p.z), rad)))
    ranked.sort(key=lambda row: row[0], reverse=True)
    return [row[1] for row in ranked[:MAX_OCCLUDERS]]
