"""Sim clocks. Warp is a rate, not a new physics."""

from __future__ import annotations

from datetime import UTC, datetime

from arelis.physics.constants import DAY_S, YEAR_S

RATE_REALTIME = 1.0
RATE_HOUR = 3_600.0
RATE_DAY = DAY_S
RATE_YEAR = YEAR_S
RATE_MIN = 1.0e-3
RATE_MAX = 1.0e7

# Unix epoch in Julian days. timestamp() is UTC seconds.
_JD_UNIX = 2_440_587.5
# TT − UTC ≈ TAI + 32.184 s. 2026 leap-second count. TDB − TT is milliseconds
# and is ignored: Earth spin is an approach globe, not a landing model.
TT_MINUS_UTC_S = 69.184
# IAS15 catch-up from a Horizons midnight IC to "now". Older ICs stay put.
SYNC_LOAD_S = 3.0 * DAY_S
# Max IC age for a realtime snap. Warp distance does not matter: we restore
# the Horizons epoch, then integrate only from that instant to UTC now.
SYNC_REALTIME_S = 400.0 * DAY_S

PRESETS: dict[str, float] = {
    "realtime": RATE_REALTIME,
    "hour": RATE_HOUR,
    "day": RATE_DAY,
    "year": RATE_YEAR,
}


def utc_jd(when: datetime | None = None) -> float:
    """Julian day from a UTC datetime. None is wall UTC now."""
    stamp = when or datetime.now(UTC)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    else:
        stamp = stamp.astimezone(UTC)
    return _JD_UNIX + stamp.timestamp() / DAY_S


def tdb_jd_now(when: datetime | None = None) -> float:
    """TDB Julian day for IAS15 catch-up. Horizons vector JD is TDB."""
    return utc_jd(when) + TT_MINUS_UTC_S / DAY_S


def clamp_rate(rate: float) -> float:
    return min(RATE_MAX, max(RATE_MIN, float(rate)))


def rate_label(rate: float) -> str:
    """HUD clock. Do not print a raw 86400 and call it a day."""
    r = float(rate)
    if abs(r - RATE_REALTIME) < 1e-9:
        return "realtime"
    if abs(r - RATE_HOUR) < 1e-3:
        return "1 hour/s"
    if abs(r - RATE_DAY) < 1e-3:
        return "1 day/s"
    if abs(r - RATE_YEAR) < 1.0:
        return "1 year/s"
    if r >= 1.0:
        return f"{r:g}×"
    return f"{r:g}×"


def jd_iso(jd: float) -> str:
    """Gregorian UTC date from Julian day. Second is truncated."""
    if jd <= 1.0e6:
        return ""
    z = int(jd + 0.5)
    f = (jd + 0.5) - z
    if z >= 2_299_161:
        a = int((z - 1_867_216.25) / 36_524.25)
        aa = z + 1 + a - int(a / 4)
    else:
        aa = z
    b = aa + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e) + f
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    di = int(day)
    frac = day - di
    hours = frac * 24.0
    hh = int(hours)
    minutes = (hours - hh) * 60.0
    mm = int(minutes)
    ss = int((minutes - mm) * 60.0)
    return f"{year:04d}-{month:02d}-{di:02d} {hh:02d}:{mm:02d}:{ss:02d} UTC"