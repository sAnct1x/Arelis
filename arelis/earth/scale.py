"""Google-style ground scale for the Earth-zone HUD."""

from __future__ import annotations

import math

# Same vertical FOV as the solar-lab inspect eye (`SolarPanel._fov_y`).
# Cesium's stock frustum is π/3 — that made Enter look like a different camera.
EARTH_FOV_Y = 0.70
_FOV_RAD = EARTH_FOV_Y


def ground_width_m(alt_m: float, *, fov_rad: float = _FOV_RAD) -> float:
    """Nadir ground width for the current look, metres."""
    return 2.0 * max(float(alt_m), 8.0) * math.tan(max(0.05, float(fov_rad)) * 0.5)


def nice_meters(span_m: float) -> float:
    """Largest 1–2–5 × 10ⁿ that still fits in span_m."""
    span = max(float(span_m), 1.0)
    exp = math.floor(math.log10(span))
    base = 10.0**exp
    for step in (5.0, 2.0, 1.0):
        if step * base <= span + 1e-9:
            return step * base
    return base


def format_agl(meters: float) -> str:
    """Camera height above the WGS84 sketch — not a DEM."""
    return f"{format_distance(meters)} AGL"


def format_surface(meters: float) -> str:
    """Camera height when Cesium owns the eye. What the distance meter reads."""
    return f"{format_distance(meters)} to surface"


def show_map_scale(*, alt_m: float, mpp: float | None) -> bool:
    """Map bar only when a pixel is a street-or-city length, not a country."""
    if alt_m >= 80_000.0:
        return False
    if mpp is None:
        return True
    return 0.0 < float(mpp) < 400.0


def slant_m(
    eye_ecef: tuple[float, float, float],
    lat: float,
    lon: float,
    *,
    alt_m: float = 0.0,
) -> float:
    """Metres from the eye to a ground pin on the ellipsoid."""
    from arelis.earth.frames import lla_to_ecef

    ground = lla_to_ecef(float(lat), float(lon), float(alt_m))
    return math.dist(eye_ecef, ground)


def format_distance(meters: float) -> str:
    m = float(meters)
    if m >= 1000.0:
        km = m / 1000.0
        if km >= 10.0:
            return f"{km:.0f} km"
        if abs(km - round(km)) < 1e-6:
            return f"{km:.0f} km"
        return f"{km:g} km"
    if m >= 1.0:
        return f"{m:.0f} m"
    return f"{max(1.0, m * 100.0):.0f} cm"


def scale_from_mpp(
    mpp: float,
    *,
    target_px: float = 96.0,
    max_px: float = 160.0,
) -> tuple[float, int, str]:
    """Scale from Cesium metres-per-pixel at the look point."""
    step = max(float(mpp), 1e-6)
    raw = step * max(32.0, float(target_px))
    nice = nice_meters(raw)
    bar_px = round(nice / step)
    bar_px = max(36, min(max_px, bar_px))
    return nice, bar_px, format_distance(nice)


def scale_bar(
    alt_m: float,
    width_px: float,
    *,
    target_px: float = 96.0,
    fov_rad: float = _FOV_RAD,
) -> tuple[float, int, str]:
    """Return (nice metres, bar pixels, label) for a ~target_px bar."""
    wide = max(float(width_px), 1.0)
    ground = ground_width_m(alt_m, fov_rad=fov_rad)
    raw = ground * max(24.0, float(target_px)) / wide
    nice = nice_meters(raw)
    bar_px = round(nice * wide / ground)
    bar_px = max(24, min(int(wide * 0.35), bar_px))
    return nice, bar_px, format_distance(nice)
