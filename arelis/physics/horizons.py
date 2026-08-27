"""Parse JPL Horizons VECTOR tables. Observer tables stay in catalog.py."""

from __future__ import annotations

import re
from dataclasses import dataclass

from arelis.physics.constants import AU_M, DAY_S

_XYZ = re.compile(
    r"X\s*=\s*([+\-0-9.EDed]+)\s+Y\s*=\s*([+\-0-9.EDed]+)\s+Z\s*=\s*([+\-0-9.EDed]+)",
    re.IGNORECASE,
)
_VXYZ = re.compile(
    r"VX\s*=\s*([+\-0-9.EDed]+)\s+VY\s*=\s*([+\-0-9.EDed]+)\s+VZ\s*=\s*([+\-0-9.EDed]+)",
    re.IGNORECASE,
)
_JD = re.compile(r"([0-9]{6,}\.[0-9]+)\s*=")
_SOE = "$$SOE"
_EOE = "$$EOE"


@dataclass(frozen=True)
class VectorState:
    """Barycentric state. SI metres and metres/second."""

    x: float
    y: float
    z: float
    vx: float
    vy: float
    vz: float
    units: str
    epoch_jd: float | None = None


def parse_vector_table(blob: str, *, units: str = "KM-S") -> VectorState:
    """Read the first $$SOE block. units is KM-S or AU-D as Horizons OUT_UNITS."""
    text = blob or ""
    start = text.find(_SOE)
    end = text.find(_EOE)
    if start < 0 or end < 0 or end <= start:
        raise ValueError("Horizons VECTOR table has no $$SOE/$$EOE block.")
    block = text[start:end]
    pos = _XYZ.search(block)
    vel = _VXYZ.search(block)
    if pos is None or vel is None:
        raise ValueError("Horizons VECTOR table has no X/Y/Z or VX/VY/VZ.")
    x, y, z = (float(pos.group(i)) for i in range(1, 4))
    vx, vy, vz = (float(vel.group(i)) for i in range(1, 4))
    kind = (units or "KM-S").upper()
    if kind in {"KM-S", "KM-T"}:
        scale_r = 1_000.0
        scale_v = 1_000.0 if kind == "KM-S" else 1_000.0 / DAY_S
    elif kind in {"AU-D", "AU-T"}:
        scale_r = AU_M
        scale_v = AU_M / DAY_S
    else:
        raise ValueError(f"Unknown Horizons OUT_UNITS {units!r}.")
    jd_m = _JD.search(block)
    epoch_jd = float(jd_m.group(1)) if jd_m else None
    return VectorState(
        x=x * scale_r,
        y=y * scale_r,
        z=z * scale_r,
        vx=vx * scale_v,
        vy=vy * scale_v,
        vz=vz * scale_v,
        units="SI",
        epoch_jd=epoch_jd,
    )
