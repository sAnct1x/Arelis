"""CelesTrak TLE + SGP4. Public GP groups. Classified objects stay absent.

Hosts named here are pinned in tests/test_egress.py. Failures return None
so the simulated ISS/shells stay. Needs the sgp4 extra (with .[astro]).
"""

from __future__ import annotations

import math
from urllib.parse import urlparse

import httpx

from arelis.earth.entity import Coverage, Entity
from arelis.earth.frames import julian_unix, teme_to_ecef
from arelis.earth.simulate import ISS_NORAD

# HTTPS so egress sees the host. Query GROUP= on this path.
CELESTRAK_GP = "https://celestrak.org/NORAD/elements/gp.php"
CELESTRAK_HOST = "celestrak.org"

# Named public slices. Mega-constellations are sampled, not a painted shell.
_GROUPS: tuple[tuple[str, int], ...] = (
    ("stations", 80),
    ("gps-ops", 40),
    ("galileo", 40),
    ("glonass", 30),
    ("beidou", 40),
    ("weather", 60),
    ("noaa", 20),
    ("goes", 15),
    ("visual", 160),
    ("geo", 50),
    ("science", 60),
    ("resource", 40),
    ("sarsat", 20),
    ("dmc", 15),
    ("tdrss", 15),
    ("amateur", 40),
    ("cubesat", 40),
    ("oneweb", 60),
    ("iridium-NEXT", 40),
    ("planet", 60),
    ("spire", 40),
    ("last-30-days", 50),
    ("starlink", 180),
    ("education", 20),
    ("engineering", 20),
    ("military", 40),
    ("intelsat", 30),
    ("ses", 20),
    ("orbcomm", 20),
    ("globalstar", 20),
    ("iridium", 20),
    ("other-comm", 20),
)
_SAMPLE_GROUPS = frozenset(
    {
        "starlink",
        "oneweb",
        "planet",
        "spire",
        "last-30-days",
        "military",
        "intelsat",
        "other-comm",
    }
)
_CAP = 1800
_TIMEOUT = 8.0
_STARLINK_TIMEOUT = 12.0
_MIN_R_M = 6_500_000.0
_MAX_R_M = 2.0e8

_CITE = (
    "CelesTrak GP TLE + SGP4. TEME→ECEF via GMST, no polar motion. "
    "GNSS / weather / visual / science / amateur / cubesat / comm groups plus "
    "Starlink / OneWeb / Planet / public-military *samples*. Epoch hours stale. "
    "Not navigation. "
    "The sample is not the shell. Classified objects are absent."
)


def fetch_celestrak(*, unix: float | None = None) -> list[Entity] | None:
    """None = library missing or every fetch failed. Keep sim."""
    if not _sgp4_ready():
        return None
    now = unix if unix is not None else _now()
    out: list[Entity] = []
    seen: set[int] = set()
    any_ok = False
    for group, budget in _GROUPS:
        text = _get_tle(group)
        if not text:
            continue
        any_ok = True
        stride = 1
        if group in _SAMPLE_GROUPS:
            n = len(parse_tle_blocks(text))
            stride = max(1, n // max(budget, 1))
        for entity in entities_from_tle_text(
            text, unix=now, cap=budget, stride=stride
        ):
            norad = int(entity.meta.get("norad") or 0)
            if norad in seen:
                continue
            seen.add(norad)
            entity.meta = {**entity.meta, "group": group}
            if group in _SAMPLE_GROUPS:
                entity.cite = _CITE
                entity.meta["sample"] = True
            out.append(entity)
            if len(out) >= _CAP:
                return out
    return out if any_ok else None


def entities_from_tle_text(
    text: str, *, unix: float, cap: int = _CAP, stride: int = 1
) -> list[Entity]:
    out: list[Entity] = []
    seen: set[int] = set()
    step = max(1, int(stride))
    for name, line1, line2 in parse_tle_blocks(text)[::step]:
        entity = _entity_from_lines(name, line1, line2, unix)
        if entity is None:
            continue
        norad = int(entity.meta.get("norad") or 0)
        if norad in seen:
            continue
        seen.add(norad)
        out.append(entity)
        if len(out) >= cap:
            break
    return out


def parse_tle_blocks(text: str) -> list[tuple[str, str, str]]:
    lines = [ln.rstrip() for ln in (text or "").splitlines() if ln.strip()]
    out: list[tuple[str, str, str]] = []
    i = 0
    while i < len(lines):
        a = lines[i]
        if a.startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            out.append(("unknown", a, lines[i + 1]))
            i += 2
            continue
        if (
            i + 2 < len(lines)
            and lines[i + 1].startswith("1 ")
            and lines[i + 2].startswith("2 ")
        ):
            out.append((a.strip(), lines[i + 1], lines[i + 2]))
            i += 3
            continue
        i += 1
    return out


def _entity_from_lines(name: str, line1: str, line2: str, unix: float) -> Entity | None:
    try:
        from sgp4.api import Satrec
    except ImportError:
        return None
    try:
        sat = Satrec.twoline2rv(line1, line2)
    except Exception:
        return None
    norad = int(getattr(sat, "satnum", 0) or 0)
    if norad <= 0:
        norad = _norad_from_line(line1)
    if norad <= 0:
        return None
    jd = julian_unix(unix)
    whole = math.floor(jd)
    frac = jd - whole
    try:
        err, r_km, v_km = sat.sgp4(whole, frac)
    except Exception:
        return None
    if int(err) != 0 or r_km is None:
        return None
    try:
        tx, ty, tz = (float(r_km[0]) * 1000.0, float(r_km[1]) * 1000.0, float(r_km[2]) * 1000.0)
        vx, vy, vz = (
            float(v_km[0]) * 1000.0,
            float(v_km[1]) * 1000.0,
            float(v_km[2]) * 1000.0,
        )
    except (TypeError, ValueError, IndexError):
        return None
    r = math.sqrt(tx * tx + ty * ty + tz * tz)
    if r < _MIN_R_M or r > _MAX_R_M:
        return None
    pos = teme_to_ecef((tx, ty, tz), jd)
    vel = teme_to_ecef((vx, vy, vz), jd)
    iss = norad == ISS_NORAD
    label = "ISS" if iss else (name or f"NORAD {norad}")
    if iss:
        label = "ISS"
    return Entity(
        id=f"norad:{norad}",
        cls="satellite",
        layer="iss" if iss else "satellites",
        label=label,
        x=pos[0],
        y=pos[1],
        z=pos[2],
        vx=vel[0],
        vy=vel[1],
        vz=vel[2],
        when_unix=unix,
        source="CelesTrak GP",
        freshness="interpolated",
        confidence=0.7,
        cite=_CITE,
        meta={"norad": norad, "name": name, "r_m": r},
        coverage=Coverage(
            "tle",
            "Public GP only. Classified objects are absent. TLE epoch hours stale.",
        ),
    )


def _norad_from_line(line1: str) -> int:
    try:
        return int(line1[2:7].strip())
    except (TypeError, ValueError):
        return 0


def _sgp4_ready() -> bool:
    try:
        from sgp4.api import Satrec  # noqa: F401
    except ImportError:
        return False
    return True


def _now() -> float:
    import time

    return time.time()


def _host_pinned(host: str | None) -> bool:
    if not host:
        return False
    name = host.lower()
    return name == CELESTRAK_HOST or name.endswith("." + CELESTRAK_HOST)


def _get_tle(group: str) -> str | None:
    url = f"{CELESTRAK_GP}?GROUP={group}&FORMAT=tle"
    if not _host_pinned(urlparse(CELESTRAK_GP).hostname):
        return None
    wait = _STARLINK_TIMEOUT if group == "starlink" else _TIMEOUT
    try:
        with httpx.Client(timeout=wait, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "ArelisEarth/0.2"},
            )
            resp.raise_for_status()
            if not _host_pinned(urlparse(str(resp.url)).hostname):
                return None
            text = resp.text
    except Exception:
        return None
    return text if isinstance(text, str) and "1 " in text else None
