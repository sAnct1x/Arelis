"""Parker 1958 quiet solar wind. Not MHD, not ENLIL, not a CME catalog.

Radial speed is a cited slow-wind number. Density falls as 1/r². The IMF
winds as φ = φ0 − Ω(r − r_source)/v in the solar equator (IAU pole).
Dynamic pressure at Earth feeds Shue 1998, so the magnetopause and the
wind share one number.

The heliopause radius is a Voyager-era sketch (~120 AU), not a live
termination-shock model.
"""

from __future__ import annotations

import math

import numpy as np

from arelis.physics.attitude import sun_frame_ecliptic
from arelis.physics.constants import AU_M, DAY_S, SUN_WDOT_DEG_PER_DAY

# Slow solar wind, typical 1 AU quiet-day values (Hundhausen / Schwenn-class).
V_SLOW_M_S = 4.00e5
N1_M3 = 7.0e6  # 7 cm^-3 at 1 AU
M_PROTON = 1.672_621_923_69e-27
# Source surface for the spiral sketch. PFSS often uses 2.5 R; 5 R is a
# common Parker start so the wind is already radial.
R_SOURCE_RSUN = 5.0
# Voyager 1 heliopause crossing 2012, order-of-magnitude sketch.
HELIOPAUSE_AU = 120.0
CITE = (
    "Parker 1958 spiral + quiet wind (~400 km/s, n∝1/r²). "
    "Shue 1998 uses this ram pressure. Heliopause ~120 AU (Voyager). "
    "Not MHD, not ENLIL, not a weather model."
)
OMEGA_S = math.radians(SUN_WDOT_DEG_PER_DAY) / DAY_S


def number_density(r_m: float) -> float:
    """Quiet-day protons per m³. n = n1 (1 AU / r)²."""
    r = max(float(r_m), 1.0)
    return N1_M3 * (AU_M / r) ** 2


def dynamic_pressure_npa(r_m: float, *, v_m_s: float = V_SLOW_M_S) -> float:
    """Ram pressure in nPa. P = n m_p v²."""
    p_pa = number_density(r_m) * M_PROTON * float(v_m_s) ** 2
    return p_pa * 1.0e9


def shue_standoff(p_npa: float, *, bz_nt: float = 0.0) -> tuple[float, float]:
    """Shue 1998 r0 (Earth radii) and flaring α. Bz in nT, P in nPa."""
    p = max(float(p_npa), 0.15)
    r0 = (10.22 + 1.29 * math.tanh(0.184 * (float(bz_nt) + 8.14))) * p ** (
        -1.0 / 6.6
    )
    alpha = (0.58 - 0.007 * float(bz_nt)) * (1.0 + 0.024 * math.log(p))
    return r0, alpha


def spiral_phi(phi0: float, r_m: float, r_source_m: float, *, v_m_s: float = V_SLOW_M_S) -> float:
    """Parker azimuth at radius r, solar-equatorial."""
    v = max(float(v_m_s), 1.0)
    return float(phi0) - OMEGA_S * (float(r_m) - float(r_source_m)) / v


def spiral_points(
    phi0: float,
    r0_m: float,
    r1_m: float,
    jd: float,
    *,
    n: int = 192,
    v_m_s: float = V_SLOW_M_S,
) -> np.ndarray:
    """Sun-relative metres in ECLIPJ2000, solar equator."""
    xx, yx, zx = sun_frame_ecliptic(jd)
    del zx
    r0 = max(float(r0_m), 1.0)
    r1 = max(float(r1_m), r0 + 1.0)
    rs = np.geomspace(r0, r1, max(int(n), 8))
    out = np.empty((rs.size, 3), dtype=np.float64)
    for i, r in enumerate(rs):
        phi = spiral_phi(phi0, r, r0_m, v_m_s=v_m_s)
        c, s = math.cos(phi), math.sin(phi)
        # Magnetic-frame equator: x̂, ŷ.
        out[i, 0] = r * (c * xx[0] + s * yx[0])
        out[i, 1] = r * (c * xx[1] + s * yx[1])
        out[i, 2] = r * (c * xx[2] + s * yx[2])
    return out


def heliopause_ring(radius_m: float, jd: float, *, n: int = 96) -> np.ndarray:
    """Sun-relative metres. Solar equator, Voyager-scale radius."""
    xx, yx, zx = sun_frame_ecliptic(jd)
    del zx
    r = max(float(radius_m), 1.0)
    out = np.empty((max(int(n), 8), 3), dtype=np.float64)
    for i in range(out.shape[0]):
        ang = 2.0 * math.pi * i / out.shape[0]
        c, s = math.cos(ang), math.sin(ang)
        out[i, 0] = r * (c * xx[0] + s * yx[0])
        out[i, 1] = r * (c * xx[1] + s * yx[1])
        out[i, 2] = r * (c * xx[2] + s * yx[2])
    return out
