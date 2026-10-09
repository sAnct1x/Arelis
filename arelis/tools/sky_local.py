"""Rise, set, and altitude for the saved place. Pure Python, no network.

Sun and Moon follow Paul Schlyter's low-precision almanac (Moon perturbations
and topocentric parallax included). Planets use mean orbital elements.
Stars are J2000 positions brought forward by precession. Rise and set use
geometric altitude -0.833 degrees for the Sun, stars, and planets (mean
refraction plus the Sun's semidiameter). The Moon uses parallax plus
semidiameter and 0.566 degrees of horizon refraction for the upper limb.

Checked once against pyephem in a throwaway environment. See the sky tests.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from arelis.tools.base import ToolResult

_H0_DEG = -0.833
_MOON_REFRACT_DEG = 0.566
_MOON_RADIUS_RATIO = 1737.4 / 6378.14
_FLATTEN = 1.0 / 298.257223563

# J2000 mean places, radians, from the pyephem star catalog (epoch J2000).
_STARS: dict[str, tuple[float, float]] = {
    "sirius": (1.7677943368738556, -0.2917512569347837),
    "vega": (4.873565519537831, 0.6769031188613907),
    "arcturus": (3.733526308009419, 0.3347962195997366),
    "capella": (1.3818178210128482, 0.8028163932999165),
    "rigel": (1.3724303730267848, -0.14314563166257863),
    "betelgeuse": (1.549729131091164, 0.12927763271479267),
    "altair": (5.195772395975994, 0.15478141855064734),
    "deneb": (5.416768576804791, 0.7902909845159041),
    "aldebaran": (1.2039309280057842, 0.2881416662850435),
    "antares": (4.317105422983595, -0.4613254715203725),
    "spica": (3.5133171877701335, -0.1948018182988773),
    "polaris": (0.6624312527475755, 1.5579526144612161),
}

_PLANETS = ("mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune")

_ID_TO_NAME = {
    "10": "sun",
    "199": "mercury",
    "299": "venus",
    "499": "mars",
    "599": "jupiter",
    "699": "saturn",
    "799": "uranus",
    "899": "neptune",
    "301": "moon",
}

_DISPLAY = {
    "sun": "Sun",
    "moon": "Moon",
    "mercury": "Mercury",
    "venus": "Venus",
    "mars": "Mars",
    "jupiter": "Jupiter",
    "saturn": "Saturn",
    "uranus": "Uranus",
    "neptune": "Neptune",
    "sirius": "Sirius",
    "vega": "Vega",
    "arcturus": "Arcturus",
    "capella": "Capella",
    "rigel": "Rigel",
    "betelgeuse": "Betelgeuse",
    "altair": "Altair",
    "deneb": "Deneb",
    "aldebaran": "Aldebaran",
    "antares": "Antares",
    "spica": "Spica",
    "polaris": "Polaris",
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def _sind(deg: float) -> float:
    return math.sin(math.radians(deg))


def _cosd(deg: float) -> float:
    return math.cos(math.radians(deg))


def _wrap360(deg: float) -> float:
    return deg % 360.0


def _julian_day(moment: datetime) -> float:
    moment = moment.astimezone(UTC)
    year = moment.year
    month = moment.month
    day = (
        moment.day
        + (moment.hour + (moment.minute + (moment.second + moment.microsecond / 1e6) / 60) / 60)
        / 24
    )
    if month <= 2:
        year -= 1
        month += 12
    century = year // 100
    gregorian = 2 - century + century // 4
    return (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day
        + gregorian
        - 1524.5
    )


def _obliquity(day: float) -> float:
    return 23.4393 - 3.563e-7 * day


def _eccentric_anomaly(mean_deg: float, ecc: float) -> float:
    mean = math.radians(_wrap360(mean_deg))
    ecc_anom = mean
    for _ in range(12):
        ecc_anom = ecc_anom - (ecc_anom - ecc * math.sin(ecc_anom) - mean) / (
            1.0 - ecc * math.cos(ecc_anom)
        )
    return ecc_anom


def _sun_ecliptic(day: float) -> tuple[float, float]:
    """Geocentric ecliptic longitude (deg) and distance (AU)."""
    peri = 282.9404 + 4.70935e-5 * day
    ecc = 0.016709 - 1.151e-9 * day
    mean = 356.0470 + 0.9856002585 * day
    ecc_anom = _eccentric_anomaly(mean, ecc)
    xv = math.cos(ecc_anom) - ecc
    yv = math.sqrt(1.0 - ecc * ecc) * math.sin(ecc_anom)
    true_anom = math.degrees(math.atan2(yv, xv))
    dist = math.hypot(xv, yv)
    return _wrap360(true_anom + peri), dist


def _helio_ecliptic(
    node: float, incl: float, peri: float, axis: float, ecc: float, mean: float
) -> tuple[float, float, float]:
    ecc_anom = _eccentric_anomaly(mean, ecc)
    xv = axis * (math.cos(ecc_anom) - ecc)
    yv = axis * math.sqrt(1.0 - ecc * ecc) * math.sin(ecc_anom)
    true_anom = math.atan2(yv, xv)
    dist = math.hypot(xv, yv)
    arg = true_anom + math.radians(peri)
    node_r = math.radians(node)
    incl_r = math.radians(incl)
    xh = dist * (
        math.cos(node_r) * math.cos(arg) - math.sin(node_r) * math.sin(arg) * math.cos(incl_r)
    )
    yh = dist * (
        math.sin(node_r) * math.cos(arg) + math.cos(node_r) * math.sin(arg) * math.cos(incl_r)
    )
    zh = dist * (math.sin(arg) * math.sin(incl_r))
    return xh, yh, zh


def _planet_elements(name: str, day: float) -> tuple[float, float, float, float, float, float]:
    if name == "mercury":
        return (
            48.3313 + 3.24587e-5 * day,
            7.0047 + 5.00e-8 * day,
            29.1241 + 1.01444e-5 * day,
            0.387098,
            0.205635 + 5.59e-10 * day,
            168.6562 + 4.0923344368 * day,
        )
    if name == "venus":
        return (
            76.6799 + 2.46590e-5 * day,
            3.3946 + 2.75e-8 * day,
            54.8910 + 1.38374e-5 * day,
            0.723330,
            0.006773 - 1.302e-9 * day,
            48.0052 + 1.6021302244 * day,
        )
    if name == "mars":
        return (
            49.5574 + 2.11081e-5 * day,
            1.8497 - 1.78e-8 * day,
            286.5016 + 2.92961e-5 * day,
            1.523688,
            0.093405 + 2.516e-9 * day,
            18.6021 + 0.5240207766 * day,
        )
    if name == "jupiter":
        return (
            100.4542 + 2.76854e-5 * day,
            1.3030 - 1.557e-7 * day,
            273.8777 + 1.64505e-5 * day,
            5.20256,
            0.048498 + 4.469e-9 * day,
            19.8950 + 0.0830853001 * day,
        )
    if name == "saturn":
        return (
            113.6634 + 2.38980e-5 * day,
            2.4886 - 1.081e-7 * day,
            339.3939 + 2.97661e-5 * day,
            9.55475,
            0.055546 - 9.499e-9 * day,
            316.9670 + 0.0334442282 * day,
        )
    if name == "uranus":
        return (
            74.0005 + 1.3978e-5 * day,
            0.7733 + 1.9e-8 * day,
            96.6612 + 3.0565e-5 * day,
            19.18171 - 1.55e-8 * day,
            0.047318 + 7.45e-9 * day,
            142.5905 + 0.011725806 * day,
        )
    return (
        131.7806 + 3.0173e-5 * day,
        1.7700 - 2.55e-7 * day,
        272.8461 - 6.027e-6 * day,
        30.05826 + 3.313e-8 * day,
        0.008606 + 2.15e-9 * day,
        260.2471 + 0.005995147 * day,
    )


def _planet_ecliptic(name: str, day: float) -> tuple[float, float]:
    sun_lon, sun_r = _sun_ecliptic(day)
    earth = (
        sun_r * _cosd(sun_lon + 180.0),
        sun_r * _sind(sun_lon + 180.0),
        0.0,
    )
    node, incl, peri, axis, ecc, mean = _planet_elements(name, day)
    xh, yh, zh = _helio_ecliptic(node, incl, peri, axis, ecc, mean)
    if name in {"jupiter", "saturn"}:
        jup_m = _planet_elements("jupiter", day)[5]
        sat_m = _planet_elements("saturn", day)[5]
        lon = math.degrees(math.atan2(yh, xh))
        lat = math.degrees(math.atan2(zh, math.hypot(xh, yh)))
        dist = math.hypot(xh, yh, zh)
        if name == "jupiter":
            lon += (
                -0.332 * _sind(2 * jup_m - 5 * sat_m - 67.6)
                - 0.056 * _sind(2 * jup_m - 2 * sat_m + 21)
                + 0.042 * _sind(3 * jup_m - 5 * sat_m + 21)
                - 0.036 * _sind(jup_m - 2 * sat_m)
                + 0.022 * _cosd(jup_m - sat_m)
                + 0.023 * _sind(2 * jup_m - 3 * sat_m + 52)
                - 0.016 * _sind(jup_m - 5 * sat_m - 69)
            )
        else:
            lon += (
                0.812 * _sind(2 * jup_m - 5 * sat_m - 67.6)
                - 0.229 * _cosd(2 * jup_m - 4 * sat_m - 2)
                + 0.119 * _sind(jup_m - 2 * sat_m - 3)
                + 0.046 * _sind(2 * jup_m - 6 * sat_m - 69)
                + 0.014 * _sind(jup_m - 3 * sat_m + 32)
            )
        xh = dist * _cosd(lat) * _cosd(lon)
        yh = dist * _cosd(lat) * _sind(lon)
        zh = dist * _sind(lat)
    xg = xh - earth[0]
    yg = yh - earth[1]
    zg = zh - earth[2]
    lon = _wrap360(math.degrees(math.atan2(yg, xg)))
    lat = math.degrees(math.atan2(zg, math.hypot(xg, yg)))
    return lon, lat


def _moon_geocentric(day: float) -> tuple[float, float, float]:
    """Ecliptic lon, lat (deg) and distance in Earth equatorial radii."""
    node = 125.1228 - 0.0529538083 * day
    incl = 5.1454
    peri = 318.0634 + 0.1643573223 * day
    axis = 60.2666
    ecc = 0.054900
    mean = 115.3654 + 13.0649929509 * day
    sun_peri = 282.9404 + 4.70935e-5 * day
    sun_mean = 356.0470 + 0.9856002585 * day
    ecc_anom = _eccentric_anomaly(mean, ecc)
    xv = axis * (math.cos(ecc_anom) - ecc)
    yv = axis * math.sqrt(1.0 - ecc * ecc) * math.sin(ecc_anom)
    true_anom = math.degrees(math.atan2(yv, xv))
    dist = math.hypot(xv, yv)
    lon = _wrap360(true_anom + peri + node)
    xh = dist * (
        _cosd(node) * _cosd(true_anom + peri) - _sind(node) * _sind(true_anom + peri) * _cosd(incl)
    )
    yh = dist * (
        _sind(node) * _cosd(true_anom + peri) + _cosd(node) * _sind(true_anom + peri) * _cosd(incl)
    )
    zh = dist * (_sind(true_anom + peri) * _sind(incl))
    lon = _wrap360(math.degrees(math.atan2(yh, xh)))
    lat = math.degrees(math.atan2(zh, math.hypot(xh, yh)))
    moon_mean_lon = _wrap360(mean + peri + node)
    sun_mean_lon = _wrap360(sun_mean + sun_peri)
    elong = moon_mean_lon - sun_mean_lon
    arg = moon_mean_lon - node
    lon += (
        -1.274 * _sind(mean - 2 * elong)
        + 0.658 * _sind(2 * elong)
        - 0.186 * _sind(sun_mean)
        - 0.059 * _sind(2 * mean - 2 * elong)
        - 0.057 * _sind(mean - 2 * elong + sun_mean)
        + 0.053 * _sind(mean + 2 * elong)
        + 0.046 * _sind(2 * elong - sun_mean)
        + 0.041 * _sind(mean - sun_mean)
        - 0.035 * _sind(elong)
        - 0.031 * _sind(mean + sun_mean)
        - 0.015 * _sind(2 * arg - 2 * elong)
        + 0.011 * _sind(mean - 4 * elong)
    )
    lat += (
        -0.173 * _sind(arg - 2 * elong)
        - 0.055 * _sind(mean - arg - 2 * elong)
        - 0.046 * _sind(mean + arg - 2 * elong)
        + 0.033 * _sind(arg + 2 * elong)
        + 0.017 * _sind(2 * mean + arg)
    )
    dist += -0.58 * _cosd(mean - 2 * elong) - 0.46 * _cosd(2 * elong)
    return _wrap360(lon), lat, dist


def _ecliptic_to_equatorial(lon: float, lat: float, day: float) -> tuple[float, float]:
    eps = _obliquity(day)
    ra = math.degrees(math.atan2(_sind(lon) * _cosd(eps) - _tand(lat) * _sind(eps), _cosd(lon)))
    dec = math.degrees(math.asin(_sind(lat) * _cosd(eps) + _cosd(lat) * _sind(eps) * _sind(lon)))
    return _wrap360(ra), dec


def _tand(deg: float) -> float:
    return math.tan(math.radians(deg))


def _precess(ra_deg: float, dec_deg: float, jd: float) -> tuple[float, float]:
    century = (jd - 2451545.0) / 36525.0
    zeta = (2306.2181 * century + 0.30188 * century**2 + 0.017998 * century**3) / 3600.0
    zee = (2306.2181 * century + 1.09468 * century**2 + 0.018203 * century**3) / 3600.0
    theta = (2004.3109 * century - 0.42665 * century**2 - 0.041833 * century**3) / 3600.0
    ra = math.radians(ra_deg)
    dec = math.radians(dec_deg)
    zeta_r = math.radians(zeta)
    theta_r = math.radians(theta)
    a_term = math.cos(dec) * math.sin(ra + zeta_r)
    b_term = math.cos(theta_r) * math.cos(dec) * math.cos(ra + zeta_r) - math.sin(
        theta_r
    ) * math.sin(dec)
    c_term = math.sin(theta_r) * math.cos(dec) * math.cos(ra + zeta_r) + math.cos(
        theta_r
    ) * math.sin(dec)
    ra2 = math.degrees(math.atan2(a_term, b_term)) + zee
    dec2 = math.degrees(math.asin(max(-1.0, min(1.0, c_term))))
    return _wrap360(ra2), dec2


def _radec(name: str, moment: datetime) -> tuple[float, float, float | None]:
    """RA, Dec in degrees, and Moon distance in Earth radii (else None)."""
    jd = _julian_day(moment)
    day = jd - 2451543.5
    if name == "sun":
        lon, _dist = _sun_ecliptic(day)
        ra, dec = _ecliptic_to_equatorial(lon, 0.0, day)
        return ra, dec, None
    if name == "moon":
        lon, lat, dist = _moon_geocentric(day)
        ra, dec = _ecliptic_to_equatorial(lon, lat, day)
        return ra, dec, dist
    if name in _PLANETS:
        lon, lat = _planet_ecliptic(name, day)
        ra, dec = _ecliptic_to_equatorial(lon, lat, day)
        return ra, dec, None
    ra0, dec0 = _STARS[name]
    ra, dec = _precess(math.degrees(ra0), math.degrees(dec0), jd)
    return ra, dec, None


def _gmst(jd: float) -> float:
    century = (jd - 2451545.0) / 36525.0
    return _wrap360(
        280.46061837
        + 360.98564736629 * (jd - 2451545.0)
        + 0.000387933 * century * century
        - century**3 / 38710000.0
    )


def _hour_angle(moment: datetime, lon_deg: float, ra_deg: float) -> float:
    lst = _gmst(_julian_day(moment)) + lon_deg
    ha = (lst - ra_deg + 180.0) % 360.0 - 180.0
    return ha


def _topocentric(
    ra_deg: float, dec_deg: float, dist_radii: float | None, lat_deg: float, ha_deg: float
) -> tuple[float, float]:
    """Topocentric RA, Dec. Parallax matters for the Moon."""
    if dist_radii is None or dist_radii <= 0:
        return ra_deg, dec_deg
    horiz = math.asin(1.0 / dist_radii)
    geo_lat = math.atan((1.0 - _FLATTEN) ** 2 * math.tan(math.radians(lat_deg)))
    rho_sin = math.sin(geo_lat)
    rho_cos = math.cos(geo_lat)
    dec = math.radians(dec_deg)
    ha = math.radians(ha_deg)
    sin_pi = math.sin(horiz)
    delta_ra = math.atan2(
        -rho_cos * sin_pi * math.sin(ha),
        math.cos(dec) - rho_cos * sin_pi * math.cos(ha),
    )
    dec_topo = math.atan2(
        (math.sin(dec) - rho_sin * sin_pi) * math.cos(delta_ra),
        math.cos(dec) - rho_cos * sin_pi * math.cos(ha),
    )
    ra_topo = _wrap360(ra_deg + math.degrees(delta_ra))
    return ra_topo, math.degrees(dec_topo)


def _alt_az(lat_deg: float, ha_deg: float, dec_deg: float) -> tuple[float, float]:
    lat = math.radians(lat_deg)
    ha = math.radians(ha_deg)
    dec = math.radians(dec_deg)
    sin_alt = math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(ha)
    sin_alt = max(-1.0, min(1.0, sin_alt))
    alt = math.degrees(math.asin(sin_alt))
    az = math.degrees(
        math.atan2(
            math.sin(ha),
            math.cos(ha) * math.sin(lat) - math.tan(dec) * math.cos(lat),
        )
    )
    return alt, (az + 180.0) % 360.0


def _refraction(alt_deg: float) -> float:
    """Apparent minus geometric, degrees. Saemundsson, geometric input."""
    if alt_deg < -1.5:
        return 0.0
    height = max(alt_deg, -1.0)
    arcmin = 1.02 / math.tan(math.radians(height + 10.3 / (height + 5.11)))
    return arcmin / 60.0


def _moon_semidiameter(dist_radii: float) -> float:
    return math.degrees(math.asin(_MOON_RADIUS_RATIO / dist_radii))


def geometric_altaz(
    name: str, moment: datetime, lat_deg: float, lon_deg: float
) -> tuple[float, float, float]:
    """Geometric topocentric altitude, azimuth, and moon semidiameter (0 else)."""
    ra, dec, dist = _radec(name, moment)
    ha = _hour_angle(moment, lon_deg, ra)
    ra_t, dec_t = _topocentric(ra, dec, dist, lat_deg, ha)
    ha_t = _hour_angle(moment, lon_deg, ra_t)
    alt, az = _alt_az(lat_deg, ha_t, dec_t)
    sd = _moon_semidiameter(dist) if dist else 0.0
    return alt, az, sd


def horizon_altitude(name: str, semidiameter: float) -> float:
    if name == "moon":
        return -(_MOON_REFRACT_DEG + semidiameter)
    return _H0_DEG


def _altitude_gap(name: str, moment: datetime, lat_deg: float, lon_deg: float) -> float:
    alt, _az, sd = geometric_altaz(name, moment, lat_deg, lon_deg)
    return alt - horizon_altitude(name, sd)


def _bisect(
    name: str,
    start: datetime,
    end: datetime,
    lat_deg: float,
    lon_deg: float,
) -> datetime:
    lo, hi = start, end
    gap_lo = _altitude_gap(name, lo, lat_deg, lon_deg)
    for _ in range(28):
        mid = lo + (hi - lo) / 2
        gap_mid = _altitude_gap(name, mid, lat_deg, lon_deg)
        if gap_lo == 0 or (gap_lo < 0) == (gap_mid < 0):
            lo, gap_lo = mid, gap_mid
        else:
            hi = mid
    return lo + (hi - lo) / 2


def _next_cross(
    name: str,
    moment: datetime,
    lat_deg: float,
    lon_deg: float,
    *,
    rising: bool,
    span: timedelta,
) -> datetime | None:
    step = timedelta(minutes=5)
    t0 = moment
    t1 = moment + span
    prev_t = t0
    prev = _altitude_gap(name, prev_t, lat_deg, lon_deg)
    t = t0 + step
    while t <= t1:
        gap = _altitude_gap(name, t, lat_deg, lon_deg)
        crossed = (prev < 0 <= gap) if rising else (prev >= 0 > gap)
        if crossed:
            return _bisect(name, prev_t, t, lat_deg, lon_deg)
        prev_t, prev = t, gap
        t += step
    return None


def _span_state(name: str, moment: datetime, lat_deg: float, lon_deg: float) -> str:
    """never_rises, never_sets, or crosses, from a day of samples."""
    step = timedelta(minutes=30)
    gaps = [_altitude_gap(name, moment + step * i, lat_deg, lon_deg) for i in range(0, 49)]
    above = any(g >= 0 for g in gaps)
    below = any(g < 0 for g in gaps)
    if above and not below:
        return "never_sets"
    if below and not above:
        return "never_rises"
    return "crosses"


def _next_transit(name: str, moment: datetime, lat_deg: float, lon_deg: float) -> datetime | None:
    step = timedelta(minutes=5)
    prev_t = moment

    def ha_at(when: datetime) -> float:
        ra, _dec, dist = _radec(name, when)
        ha = _hour_angle(when, lon_deg, ra)
        if dist:
            ra_t, _dec_t = _topocentric(ra, _dec, dist, lat_deg, ha)
            ha = _hour_angle(when, lon_deg, ra_t)
        return ha

    prev = ha_at(prev_t)
    t = moment + step
    end = moment + timedelta(hours=26)
    while t <= end:
        ha = ha_at(t)
        if prev < 0 <= ha:
            lo, hi = prev_t, t
            for _ in range(24):
                mid = lo + (hi - lo) / 2
                if ha_at(mid) < 0:
                    lo = mid
                else:
                    hi = mid
            return lo + (hi - lo) / 2
        prev_t, prev = t, ha
        t += step
    return None


def circumstances(name: str, moment: datetime, lat_deg: float, lon_deg: float) -> dict[str, Any]:
    alt, az, sd = geometric_altaz(name, moment, lat_deg, lon_deg)
    limit = horizon_altitude(name, sd)
    state = _span_state(name, moment - timedelta(hours=1), lat_deg, lon_deg)
    rise = set_ = None
    if state == "crosses":
        rise = _next_cross(name, moment, lat_deg, lon_deg, rising=True, span=timedelta(hours=26))
        set_ = _next_cross(name, moment, lat_deg, lon_deg, rising=False, span=timedelta(hours=26))
    return {
        "alt_geom": alt,
        "alt_app": alt + _refraction(alt),
        "az": az,
        "up": alt >= limit,
        "state": state,
        "rise": rise,
        "set": set_,
        "transit": _next_transit(name, moment, lat_deg, lon_deg),
        "limit": limit,
    }


def canonical_body(raw: str) -> str | None:
    text = " ".join((raw or "").split()).casefold()
    if text.startswith("the "):
        text = text[4:]
    if text in _ID_TO_NAME:
        return _ID_TO_NAME[text]
    if text in _DISPLAY:
        return text
    return None


def _compass(az: float) -> str:
    names = (
        "north",
        "north-northeast",
        "northeast",
        "east-northeast",
        "east",
        "east-southeast",
        "southeast",
        "south-southeast",
        "south",
        "south-southwest",
        "southwest",
        "west-southwest",
        "west",
        "west-northwest",
        "northwest",
        "north-northwest",
    )
    index = int((az + 11.25) // 22.5) % 16
    return names[index]


def _zone_from(snap: Any) -> tzinfo | None:
    name = str(getattr(snap, "timezone", "") or "").strip()
    if name:
        try:
            return ZoneInfo(name)
        except Exception:
            return None
    raw = str(getattr(snap, "utc_offset", "") or "").strip().upper()
    if raw.startswith("UTC"):
        raw = raw[3:]
    if len(raw) >= 6 and raw[0] in "+-" and raw[3] == ":":
        sign = 1 if raw[0] == "+" else -1
        hours = int(raw[1:3])
        minutes = int(raw[4:6])
        return timezone(sign * timedelta(hours=hours, minutes=minutes))
    return None


def _clock(when: datetime, zone: tzinfo, today: datetime) -> str:
    local = when.astimezone(zone)
    clock = local.strftime("%I:%M %p").lstrip("0")
    if local.date() == today.date():
        return clock
    if local.date() == today.date() + timedelta(days=1):
        return f"{clock} tomorrow"
    if local.date() == today.date() - timedelta(days=1):
        return f"{clock} yesterday"
    return f"{clock} on {local.strftime('%b')} {local.day}"


def _sentence_name(name: str, *, start: bool) -> str:
    label = _DISPLAY[name]
    if name in {"sun", "moon"}:
        return f"The {label}" if start else f"the {label}"
    return label


def speak(name: str, sky: dict[str, Any], moment: datetime, zone: tzinfo) -> str:
    who = _sentence_name(name, start=True)
    whom = _sentence_name(name, start=False)
    today = moment.astimezone(zone)
    state = sky["state"]
    if state == "never_sets":
        alt = round(sky["alt_app"])
        line = (
            f"{who} does not set from here. Right now it is {alt} degrees up "
            f"in the {_compass(sky['az'])}."
        )
        if sky["transit"] is not None:
            line += f" It is highest at {_clock(sky['transit'], zone, today)}."
        return line
    if state == "never_rises":
        return f"{who} does not rise from here. Right now it is below the horizon."
    bits: list[str] = []
    if sky["up"]:
        alt = round(sky["alt_app"])
        bits.append(f"Right now {whom} is {alt} degrees up in the {_compass(sky['az'])}.")
    else:
        bits.append(f"Right now {whom} is below the horizon.")
    if sky["rise"] is not None and sky["set"] is not None:
        bits.append(
            f"{who} rises at {_clock(sky['rise'], zone, today)} and sets at "
            f"{_clock(sky['set'], zone, today)}."
        )
    elif sky["rise"] is not None:
        bits.append(f"{who} rises at {_clock(sky['rise'], zone, today)}.")
    elif sky["set"] is not None:
        bits.append(f"{who} sets at {_clock(sky['set'], zone, today)}.")
    if sky["transit"] is not None and state == "crosses":
        bits.append(f"It is highest at {_clock(sky['transit'], zone, today)}.")
    return " ".join(bits)


def _snapshot(location: Any) -> Any | None:
    if location is None:
        return None
    snap = location.snapshot() if hasattr(location, "snapshot") else location
    return snap


def local_sky_result(target: str, location: Any, *, moment: datetime | None = None) -> ToolResult:
    name = canonical_body(target)
    if name is None:
        return ToolResult(
            ok=False,
            output=(
                "Name the Moon, the Sun, a planet from Mercury to Neptune, "
                "or a bright star such as Sirius, Vega, Arcturus, Capella, "
                "Rigel, Betelgeuse, Altair, Deneb, Aldebaran, Antares, Spica, "
                "or Polaris."
            ),
            data={"fail_class": "fail:name", "action": "horizons", "table": "local"},
        )
    snap = _snapshot(location)
    lat = getattr(snap, "latitude", None) if snap is not None else None
    lon = getattr(snap, "longitude", None) if snap is not None else None
    if lat is None or lon is None:
        return ToolResult(
            ok=False,
            output=(
                f"No location is set, so I cannot say where {_sentence_name(name, start=False)} "
                "is from where you are. Set your city and coordinates, then ask again."
            ),
            data={"fail_class": "fail:place", "action": "horizons", "table": "local"},
        )
    zone = _zone_from(snap)
    if zone is None:
        return ToolResult(
            ok=False,
            output=(
                "Your location has no time zone, so I cannot give a local rise "
                "or set time. Set a time zone, then ask again."
            ),
            data={"fail_class": "fail:place", "action": "horizons", "table": "local"},
        )
    when = moment or utc_now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    sky = circumstances(name, when, float(lat), float(lon))
    text = speak(name, sky, when, zone)

    def _iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    return ToolResult(
        ok=True,
        output=text,
        data={
            "action": "horizons",
            "table": "local",
            "body": _DISPLAY[name],
            "alt_deg": round(sky["alt_app"], 3),
            "az_deg": round(sky["az"], 3),
            "up": sky["up"],
            "state": sky["state"],
            "rise": _iso(sky["rise"]),
            "set": _iso(sky["set"]),
            "transit": _iso(sky["transit"]),
        },
    )
