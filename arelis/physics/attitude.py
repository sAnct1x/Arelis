"""Body-fixed lon/lat for approach globes. Not an IAU W landing model.

Earth: mean obliquity + GMST so the terminator and continents roughly agree.
Moon: mean Earth-facing (tidal lock); optical libration is ignored.
Mapped planets: IAU WGCCRE 2015 linear W at J2000, no precession.
Asteroids and other moons: no spin model — the HUD must say so.
"""

from __future__ import annotations

import math

import numpy as np

from arelis.physics.constants import (
    IAU_W,
    SATURN_POLE_DEC_DEG,
    SATURN_POLE_RA_DEG,
    SUN_POLE_DEC_DEG,
    SUN_POLE_RA_DEG,
    SUN_W0_DEG,
    SUN_WDOT_DEG_PER_DAY,
    IauW,
)

# IAU 2006 obliquity at J2000 (rad)
_EPS = math.radians(23.43927944444444)
_COS_EPS = math.cos(_EPS)
_SIN_EPS = math.sin(_EPS)

_JD2000 = 2_451_545.0

Frame = tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]


def gmst_rad(jd: float) -> float:
    """Approximate GMST. UT1 ≈ TDB; good enough for an approach globe."""
    d = float(jd) - _JD2000
    deg = (280.46061837 + 360.98564736629 * d) % 360.0
    return math.radians(deg)


def spin_jd(epoch_jd: float, t_s: float) -> float:
    """TDB Julian day for W. J2000 until a Horizons epoch exists."""
    if float(epoch_jd) > 0.0:
        return float(epoch_jd) + float(t_s) / 86400.0
    return _JD2000


def earth_lonlat(
    x: float, y: float, z: float, jd: float
) -> tuple[float, float]:
    """ECLIPJ2000 unit vector → Earth-fixed lon/lat (rad)."""
    lon, lat = earth_lonlat_grid(
        np.asarray(x, dtype=np.float64),
        np.asarray(y, dtype=np.float64),
        np.asarray(z, dtype=np.float64),
        jd,
    )
    return float(lon), float(lat)


def earth_lonlat_grid(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, jd: float
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized Earth-fixed lon/lat for ECLIPJ2000 unit vectors."""
    return lonlat_from_frame(x, y, z, _earth_frame(jd))


def moon_lonlat_grid(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    moon: tuple[float, float, float],
    earth: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray]:
    """Mean Earth-facing selenographic lon/lat. No libration."""
    return lonlat_from_frame(x, y, z, _moon_frame(moon, earth))


def equatorial_to_ecliptic(
    x: float, y: float, z: float
) -> tuple[float, float, float]:
    """ICRF equatorial J2000 → ECLIPJ2000. Inverse of the Earth-grid first step."""
    return (
        x,
        y * _COS_EPS + z * _SIN_EPS,
        -y * _SIN_EPS + z * _COS_EPS,
    )


def lonlat_from_frame(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    frame: Frame,
) -> tuple[np.ndarray, np.ndarray]:
    """World unit vectors → body-fixed lon/lat (rad). Frame columns are X,Y,Z."""
    xx, yx, zx = frame
    bx = x * xx[0] + y * xx[1] + z * xx[2]
    by = x * yx[0] + y * yx[1] + z * yx[2]
    bz = x * zx[0] + y * zx[1] + z * zx[2]
    lon = np.arctan2(by, bx)
    lat = np.arcsin(np.clip(bz, -1.0, 1.0))
    return lon, lat


def body_frame_ecliptic(
    name: str,
    jd: float,
    *,
    moon: tuple[float, float, float] | None = None,
    earth: tuple[float, float, float] | None = None,
) -> Frame | None:
    """Body-fixed X,Y,Z in ECLIPJ2000. None when the map is not body-fixed."""
    if name == "Earth":
        return _earth_frame(jd)
    if name == "Moon":
        if moon is None or earth is None:
            return None
        return _moon_frame(moon, earth)
    spec = IAU_W.get(name)
    if spec is None:
        return None
    return _iau_frame(spec, jd)


def spin_caption(name: str) -> str:
    """One inspect/HUD sentence. Does not claim a landing model."""
    if name == "Sun":
        return "Photosphere has no map. Dipole corona is a sketch."
    if name == "Earth":
        return "GMST+obliquity on the globe."
    if name == "Moon":
        return "Mean Earth-facing. Optical libration ignored."
    if name in IAU_W:
        return "IAU W, J2000 (WGCCRE 2015). Map is body-fixed. No precession."
    return "Map is not body-fixed — ecliptic-aligned sphere."


def sun_pole_ecliptic() -> tuple[float, float, float]:
    """IAU WGCCRE 2015 solar north in ECLIPJ2000. Fixed J2000; no precession."""
    ra = math.radians(SUN_POLE_RA_DEG)
    dec = math.radians(SUN_POLE_DEC_DEG)
    cdec = math.cos(dec)
    x, y, z = equatorial_to_ecliptic(
        cdec * math.cos(ra),
        cdec * math.sin(ra),
        math.sin(dec),
    )
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return x / n, y / n, z / n


def sun_frame_ecliptic(jd: float) -> Frame:
    """Carrington / IAU W solar body axes in ECLIPJ2000. For the dipole sketch."""
    return _iau_frame(
        IauW(SUN_POLE_RA_DEG, SUN_POLE_DEC_DEG, SUN_W0_DEG, SUN_WDOT_DEG_PER_DAY),
        jd,
    )


def saturn_pole_ecliptic() -> tuple[float, float, float]:
    """IAU WGCCRE 2015 Saturn north pole in ECLIPJ2000. Fixed J2000; no precession."""
    ra = math.radians(SATURN_POLE_RA_DEG)
    dec = math.radians(SATURN_POLE_DEC_DEG)
    cdec = math.cos(dec)
    x, y, z = equatorial_to_ecliptic(
        cdec * math.cos(ra),
        cdec * math.sin(ra),
        math.sin(dec),
    )
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return x / n, y / n, z / n


def saturn_ring_axes() -> Frame:
    """Local XY = equatorial ring plane, +Z = IAU north. ECLIPJ2000.

    X is the ecliptic node, not Saturn W. Rings are an untextured disc.
    """
    zx, zy, zz = saturn_pole_ecliptic()
    xx, xy, xz = -zy, zx, 0.0
    xl = math.sqrt(xx * xx + xy * xy + xz * xz)
    if xl < 1e-9:
        xx, xy, xz = 1.0, 0.0, 0.0
        xl = 1.0
    xx, xy, xz = xx / xl, xy / xl, xz / xl
    yx = zy * xz - zz * xy
    yy = zz * xx - zx * xz
    yz = zx * xy - zy * xx
    yl = math.sqrt(yx * yx + yy * yy + yz * yz) or 1.0
    return (xx, xy, xz), (yx / yl, yy / yl, yz / yl), (zx, zy, zz)


def _earth_frame(jd: float) -> Frame:
    gst = gmst_rad(jd)
    c, s = math.cos(gst), math.sin(gst)
    x_eq = (c, s, 0.0)
    y_eq = (-s, c, 0.0)
    z_eq = (0.0, 0.0, 1.0)
    return (
        equatorial_to_ecliptic(*x_eq),
        equatorial_to_ecliptic(*y_eq),
        equatorial_to_ecliptic(*z_eq),
    )


def _moon_frame(
    moon: tuple[float, float, float],
    earth: tuple[float, float, float],
) -> Frame:
    mx, my, mz = moon
    ex, ey, ez = earth
    xx, xy, xz = ex - mx, ey - my, ez - mz
    xl = math.sqrt(xx * xx + xy * xy + xz * xz) or 1.0
    xx, xy, xz = xx / xl, xy / xl, xz / xl
    yx = -xy
    yy = xx
    yz = 0.0
    yl = math.sqrt(yx * yx + yy * yy + yz * yz)
    if yl < 1e-12:
        yx, yy, yz = 0.0, 0.0, 1.0
        yl = 1.0
    yx, yy, yz = yx / yl, yy / yl, yz / yl
    zx = xy * yz - xz * yy
    zy = xz * yx - xx * yz
    zz = xx * yy - xy * yx
    return (xx, xy, xz), (yx, yy, yz), (zx, zy, zz)


def _iau_frame(spec: IauW, jd: float) -> Frame:
    """ICRF pole + W → ECLIPJ2000 body axes. Q is the ICRF equatorial node."""
    ra = math.radians(spec.ra_deg)
    dec = math.radians(spec.dec_deg)
    w = math.radians(_w_deg(spec, jd))
    cdec, sdec = math.cos(dec), math.sin(dec)
    px = cdec * math.cos(ra)
    py = cdec * math.sin(ra)
    pz = sdec
    qx, qy, qz = -math.sin(ra), math.cos(ra), 0.0
    cx = py * qz - pz * qy
    cy = pz * qx - px * qz
    cz = px * qy - py * qx
    cl = math.sqrt(cx * cx + cy * cy + cz * cz) or 1.0
    cx, cy, cz = cx / cl, cy / cl, cz / cl
    cw, sw = math.cos(w), math.sin(w)
    xx = cw * qx + sw * cx
    xy = cw * qy + sw * cy
    xz = cw * qz + sw * cz
    yx = py * xz - pz * xy
    yy = pz * xx - px * xz
    yz = px * xy - py * xx
    yx, yy, yz = _unit(yx, yy, yz)
    xx, xy, xz = _unit(xx, xy, xz)
    zx, zy, zz = _unit(px, py, pz)
    return (
        equatorial_to_ecliptic(xx, xy, xz),
        equatorial_to_ecliptic(yx, yy, yz),
        equatorial_to_ecliptic(zx, zy, zz),
    )


def _w_deg(spec: IauW, jd: float) -> float:
    d = float(jd) - _JD2000
    return (spec.w0_deg + spec.wdot_deg_per_day * d) % 360.0


def _unit(x: float, y: float, z: float) -> tuple[float, float, float]:
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return x / n, y / n, z / n
