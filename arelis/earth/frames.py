"""ECEF metres <-> ECLIPJ2000 metres using the solar-lab Earth body.

The Earth-zone store is ECEF. The plate is still ECLIPJ2000. This is the
handoff, not a second camera until ride mode asks for one.
"""

from __future__ import annotations

import math

from arelis.physics.attitude import _earth_frame, gmst_rad, spin_jd

# WGS84. Sketch geoid: spherical labels, ellipsoidal radius for height.
WGS84_A = 6_378_137.0
WGS84_F = 1.0 / 298.257223563
WGS84_B = WGS84_A * (1.0 - WGS84_F)
MEAN_R = 6_371_000.0


def julian_unix(unix: float) -> float:
    """Unix seconds → Julian day (UTC≈UT1)."""
    return float(unix) / 86400.0 + 2_440_587.5


def lla_to_ecef(lat_deg: float, lon_deg: float, alt_m: float = 0.0) -> tuple[float, float, float]:
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    s, c = math.sin(lat), math.cos(lat)
    e2 = 1.0 - (WGS84_B * WGS84_B) / (WGS84_A * WGS84_A)
    n = WGS84_A / math.sqrt(1.0 - e2 * s * s)
    x = (n + alt_m) * c * math.cos(lon)
    y = (n + alt_m) * c * math.sin(lon)
    z = (n * (1.0 - e2) + alt_m) * s
    return (x, y, z)


def ecef_to_lla(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Spherical lat/lon/alt. HUD, not a survey."""
    r = math.sqrt(x * x + y * y + z * z) or 1.0
    lat = math.degrees(math.asin(max(-1.0, min(1.0, z / r))))
    lon = math.degrees(math.atan2(y, x))
    return (lat, lon, r - MEAN_R)


def ecef_to_ecliptic(
    earth_xyz: tuple[float, float, float],
    ecef: tuple[float, float, float],
    jd: float,
) -> tuple[float, float, float]:
    xx, yy, zz = _earth_frame(jd)
    ex, ey, ez = earth_xyz
    x, y, z = ecef
    return (
        ex + xx[0] * x + yy[0] * y + zz[0] * z,
        ey + xx[1] * x + yy[1] * y + zz[1] * z,
        ez + xx[2] * x + yy[2] * y + zz[2] * z,
    )


def ecef_vel_to_ecliptic(
    ecef_v: tuple[float, float, float],
    jd: float,
) -> tuple[float, float, float]:
    """Rotate ECEF velocity; skips Earth-spin transport for a sketch trail."""
    xx, yy, zz = _earth_frame(jd)
    vx, vy, vz = ecef_v
    return (
        xx[0] * vx + yy[0] * vy + zz[0] * vz,
        xx[1] * vx + yy[1] * vy + zz[1] * vz,
        xx[2] * vx + yy[2] * vy + zz[2] * vz,
    )


def earth_spin_jd(system_epoch_jd: float, system_t: float) -> float:
    return spin_jd(system_epoch_jd, system_t)


def gmst(jd: float) -> float:
    return gmst_rad(jd)


def teme_to_ecef(
    teme: tuple[float, float, float], jd: float
) -> tuple[float, float, float]:
    """TEME metres → ECEF metres. GMST only; no polar motion. Globe pins, not IERS."""
    theta = gmst_rad(jd)
    c, s = math.cos(theta), math.sin(theta)
    x, y, z = teme
    return (x * c + y * s, -x * s + y * c, z)


def ecliptic_offset_to_ecef(
    offset: tuple[float, float, float], jd: float
) -> tuple[float, float, float]:
    """ECLIPJ2000 offset from Earth's centre → ECEF metres."""
    xx, yy, zz = _earth_frame(jd)
    ox, oy, oz = offset
    return (
        xx[0] * ox + xx[1] * oy + xx[2] * oz,
        yy[0] * ox + yy[1] * oy + yy[2] * oz,
        zz[0] * ox + zz[1] * oy + zz[2] * oz,
    )


def enu_axes(
    lat_deg: float, lon_deg: float
) -> tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]:
    """East, north, up unit vectors in ECEF at this geodetic pin. Spherical ENU."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    slat, clat = math.sin(lat), math.cos(lat)
    slon, clon = math.sin(lon), math.cos(lon)
    east = (-slon, clon, 0.0)
    north = (-slat * clon, -slat * slon, clat)
    up = (clat * clon, clat * slon, slat)
    return (east, north, up)


def enu_to_ecef(
    lat_deg: float,
    lon_deg: float,
    east_m: float,
    north_m: float,
    up_m: float,
    *,
    alt_m: float = 0.0,
) -> tuple[float, float, float]:
    """Local ENU metres at a site → ECEF metres."""
    ox, oy, oz = lla_to_ecef(lat_deg, lon_deg, alt_m)
    east, north, up = enu_axes(lat_deg, lon_deg)
    return (
        ox + east_m * east[0] + north_m * north[0] + up_m * up[0],
        oy + east_m * east[1] + north_m * north[1] + up_m * up[1],
        oz + east_m * east[2] + north_m * north[2] + up_m * up[2],
    )


def ecef_vel_from_track(
    lat_deg: float,
    lon_deg: float,
    speed_mps: float,
    track_deg: float,
    climb_mps: float = 0.0,
) -> tuple[float, float, float]:
    """Ground-track + climb → ECEF velocity. Track is clockwise from north."""
    east, north, up = enu_axes(lat_deg, lon_deg)
    rad = math.radians(track_deg)
    ve = float(speed_mps) * math.sin(rad)
    vn = float(speed_mps) * math.cos(rad)
    vu = float(climb_mps)
    return (
        ve * east[0] + vn * north[0] + vu * up[0],
        ve * east[1] + vn * north[1] + vu * up[1],
        ve * east[2] + vn * north[2] + vu * up[2],
    )
