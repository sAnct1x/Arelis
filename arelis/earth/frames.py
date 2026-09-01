"""ECEF metres <-> ECLIPJ2000 metres using the solar-lab Earth body.

The Earth-zone store is ECEF. The plate still paints ECLIPJ2000. Once
the globe fills the view, the inspect eye is also ECEF — continents stay
put, contacts move over them. Leave / travel away / reset view drops
that lock and the solar-lab camera is inertial again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arelis.physics.attitude import _earth_frame, gmst_rad, spin_jd

# Inside this many IAU radii the eye rides Earth. Outside, inertial.
EARTH_LOCK_RADII = 24.0


@dataclass(frozen=True)
class EarthCam:
    """Inspect eye in ECEF metres. Not a spacecraft state."""

    eye: tuple[float, float, float]
    look: tuple[float, float, float]
    up: tuple[float, float, float]

# WGS84. Sketch geoid: spherical labels, ellipsoidal radius for height.
WGS84_A = 6_378_137.0
WGS84_F = 1.0 / 298.257223563
WGS84_B = WGS84_A * (1.0 - WGS84_F)
MEAN_R = 6_371_000.0


def nadir_cam(lat_deg: float, lon_deg: float, alt_m: float) -> EarthCam:
    """Birds-eye inspect pose. Look at the surface pin, north-ish up."""
    eye = lla_to_ecef(lat_deg, lon_deg, alt_m)
    look = lla_to_ecef(lat_deg, lon_deg, 0.0)
    north = lla_to_ecef(min(89.0, lat_deg + 0.25), lon_deg, alt_m)
    up = (north[0] - eye[0], north[1] - eye[1], north[2] - eye[2])
    return EarthCam(eye=eye, look=look, up=up)


def julian_unix(unix: float) -> float:
    """Unix seconds → Julian day (UTC≈UT1)."""
    return float(unix) / 86400.0 + 2_440_587.5


def lla_to_sphere(
    lat_deg: float, lon_deg: float, radius: float = MEAN_R
) -> tuple[float, float, float]:
    """Geographic lat/lon on a sphere. Same surface the globe mesh uses."""
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    c = math.cos(lat)
    return (radius * c * math.cos(lon), radius * c * math.sin(lon), radius * math.sin(lat))


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


def ecef_to_geodetic(x: float, y: float, z: float) -> tuple[float, float, float]:
    """WGS84 lat/lon/alt. Look pin and tile fabric, not a HUD sketch."""
    lon = math.degrees(math.atan2(y, x))
    p = math.hypot(x, y)
    e2 = 1.0 - (WGS84_B * WGS84_B) / (WGS84_A * WGS84_A)
    lat = math.atan2(z, p * (1.0 - e2))
    for _ in range(8):
        s = math.sin(lat)
        n = WGS84_A / math.sqrt(1.0 - e2 * s * s)
        lat = math.atan2(z + e2 * n * s, p)
    c = math.cos(lat)
    n = WGS84_A / math.sqrt(1.0 - e2 * math.sin(lat) ** 2)
    if abs(c) > 1.0e-12:
        alt = p / c - n
    else:
        alt = abs(z) - WGS84_B
    return (math.degrees(lat), lon, alt)


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


def earth_eye_locked(
    earth_xyz: tuple[float, float, float],
    earth_radius: float,
    cam_xyz: tuple[float, float, float],
) -> bool:
    """True when the inspect eye is close enough to ride ECEF."""
    dx = cam_xyz[0] - earth_xyz[0]
    dy = cam_xyz[1] - earth_xyz[1]
    dz = cam_xyz[2] - earth_xyz[2]
    reach = max(float(earth_radius), 1.0) * EARTH_LOCK_RADII
    return dx * dx + dy * dy + dz * dz <= reach * reach


def capture_earth_cam(cam, earth_xyz: tuple[float, float, float], jd: float) -> EarthCam:
    """Read the solar-lab camera as an ECEF pose."""
    ex, ey, ez = earth_xyz
    eye = ecliptic_offset_to_ecef((cam.x - ex, cam.y - ey, cam.z - ez), jd)
    fx, fy, fz = cam.forward()
    dist = float(cam.distance) if cam.distance > 1.0 else math.hypot(
        cam.x - ex, cam.y - ey, cam.z - ez
    )
    look_ecl = (cam.x + fx * dist, cam.y + fy * dist, cam.z + fz * dist)
    look = ecliptic_offset_to_ecef(
        (look_ecl[0] - ex, look_ecl[1] - ey, look_ecl[2] - ez), jd
    )
    up = ecliptic_offset_to_ecef(cam.up, jd)
    return EarthCam(eye=eye, look=look, up=up)


def apply_earth_cam(
    cam,
    earth_xyz: tuple[float, float, float],
    jd: float,
    pose: EarthCam,
) -> None:
    """Write an ECEF pose onto the solar-lab camera for this instant."""
    eye = ecef_to_ecliptic(earth_xyz, pose.eye, jd)
    look = ecef_to_ecliptic(earth_xyz, pose.look, jd)
    up = ecef_vel_to_ecliptic(pose.up, jd)
    cam.x, cam.y, cam.z = eye
    cam.aim(look[0], look[1], look[2], up=up)
