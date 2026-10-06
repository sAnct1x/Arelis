"""Pinned NASA planetary and Mars-moon facts for grounding answers.

Values copied from NASA Planetary Fact Sheets (metric + Earth ratios),
the Mars Fact Sheet satellite table, and JPL notes on Phobos rise/set.
Do not invent finer precision than these sheets.
"""

from __future__ import annotations

import re
from typing import Any

# Same clause-negation idea as intent_catalog.first_unnegated, kept local so
# physics does not import core.
_CLAUSE_NEGATION = re.compile(
    r"(?i)\b(?:(?<!why\s)don['\u2019]?t|do\s+not|never(?!\s+mind)|no\s+need"
    r"|didn['\u2019]?t|shouldn['\u2019]?t|why\s+(?:did|would)\s+you)\b"
)


def _first_unnegated(pattern: re.Pattern[str], text: str) -> re.Match[str] | None:
    raw = text or ""
    for hit in pattern.finditer(raw):
        prefix = raw[: max(0, hit.start())]
        clause = re.split(r"[.!?;\n]", prefix)[-1]
        if not _CLAUSE_NEGATION.search(clause):
            return hit
    return None


# https://nssdc.gsfc.nasa.gov/planetary/factsheet/
EQUATORIAL_DIAMETER_KM: dict[str, int] = {
    "Mercury": 4879,
    "Venus": 12104,
    "Earth": 12756,
    "Moon": 3475,
    "Mars": 6792,
    "Jupiter": 142984,
    "Saturn": 120536,
    "Uranus": 51118,
    "Neptune": 49528,
}

# https://nssdc.gsfc.nasa.gov/planetary/factsheet/planet_table_ratio.html
DIAMETER_RATIO_TO_EARTH: dict[str, float] = {
    "Mercury": 0.383,
    "Venus": 0.949,
    "Moon": 0.2724,
    "Mars": 0.532,
    "Jupiter": 11.21,
    "Saturn": 9.45,
    "Uranus": 4.01,
    "Neptune": 3.88,
}

# https://nssdc.gsfc.nasa.gov/planetary/factsheet/planet_table_ratio.html
MASS_RATIO_TO_EARTH: dict[str, float] = {
    "Mercury": 0.0553,
    "Venus": 0.815,
    "Mars": 0.107,
    "Jupiter": 317.8,
    "Saturn": 95.2,
    "Uranus": 14.5,
    "Neptune": 17.1,
}

# https://nssdc.gsfc.nasa.gov/planetary/factsheet/jupiterfact.html
JUPITER_VOLUME_RATIO_TO_EARTH = 1321.33

LARGEST_PLANET = "Jupiter"

# https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html
MARS_MOON_COUNT = 2
MARS_DAY_HOURS = 24.6597  # length of day; about 24 hours 40 minutes

# Mars Fact Sheet, Satellites of Mars.
# Rise/set: https://www.jpl.nasa.gov/news/nasa-orbiter-eyes-phobos-over-mars-horizon/
# and https://pds-rings.seti.org/press_releases/pages/PIA06xxx/PIA06340.html
PHOBOS: dict[str, Any] = {
    "mean_distance_km": 9378,
    "orbit_period_days": 0.31891,  # about 7 hours 39 minutes
    "axis_radii_km": (13.0, 11.4, 9.1),  # about 26 x 23 x 18 km
    "order": "inner",
}

DEIMOS: dict[str, Any] = {
    "mean_distance_km": 23459,
    "orbit_period_days": 1.26244,  # about 30 hours 18 minutes
    "axis_radii_km": (7.8, 6.0, 5.1),  # about 16 x 12 x 10 km
    "order": "outer",
}

_PREFIX = (
    "Reference facts from NASA fact sheets. Use these numbers and directions; "
    "do not contradict them:"
)

_P = r"(?:Mercury|Venus|Earth|Mars|Jupiter|Saturn|Uranus|Neptune)"
_SIZE_WORD = r"(?:bigger|larger|smaller|wider|heavier|biggest|largest|smallest)"

# Size / ranking asks about planets (not street names, candy, concerts).
_PLANET_SIZE_ASK = re.compile(
    r"(?i)(?:"
    r"\b(?:largest|biggest|smallest|tiniest)\s+planet\b|"
    r"\bplanet\s+(?:is\s+)?(?:the\s+)?(?:largest|biggest|smallest)\b|"
    r"\bwhich\s+planet\b[^?]{0,40}\b(?:largest|biggest|smallest|size|wide|wider|big)\b|"
    rf"\bhow\s+(?:big|wide|large|heavy|massive)\s+is\s+(?:the\s+planet\s+)?{_P}\b|"
    rf"\bhow\s+much\s+{_SIZE_WORD}\s+is\s+{_P}\b|"
    rf"\b{_P}\s+{_SIZE_WORD}\s+than\s+{_P}\b|"
    rf"\b{_SIZE_WORD}\s*[,:]?\s+{_P}\s+or\s+{_P}\b|"
    rf"\bhow\s+many\s+Earths\b[^?]{{0,30}}\b{_P}\b|"
    rf"\b{_P}(?:['\u2019]s)?\s+size\b|"
    rf"\b{_P}\s+(?:compared\s+to|vs\.?|versus)\s+{_P}\b|"
    rf"\b(?:diameter|width|mass|size)\s+of\s+{_P}\b|"
    rf"\b{_P}\b[^?]{{0,30}}\b(?:diameter|how\s+wide|how\s+big|times\s+(?:wider|Earth))\b"
    r")"
)

# Mars moons / Phobos / Deimos. Avoid Bruno Mars, Mars bar.
_MARS_MOONS_ASK = re.compile(
    r"(?i)(?:"
    r"\bmoons?\s+of\s+Mars\b|"
    r"\bMars(?:['\u2019]s?)?\s+(?:has\s+)?(?:how\s+many\s+)?moons?\b|"
    r"\bhow\s+many\s+moons\s+(?:does\s+)?Mars\b|"
    r"\bdoes\s+Mars\s+have\s+(?:any\s+)?moons?\b|"
    r"\bmoons?\s+(?:orbit|orbits|orbiting|around|circling)\s+Mars\b|"
    r"\bmartian\s+moons?\b|"
    r"\bPhobos\b|"
    r"\bDeimos\b"
    r")"
)

# Names that look like a planet but are not one. Any of these vetoes the block.
_FALSE_MARS = re.compile(
    r"(?i)\b(?:bruno\s+mars|mars\s+bars?|mars\s+inc|mars\s+candy|mars\s+petcare|"
    r"mars,?\s+pa|jupiter,?\s+fl|"
    r"saturn\s+(?:car|vue|sky|ion|aura|outlook|relay)|"
    r"mercury\s+(?:poisoning|levels?|exposure)|"
    r"on\s+saturn\s+street|saturn\s+street)\b"
)

_FALSE_MOON = re.compile(
    r"(?i)\b(?:moon\s+icon|phone'?s\s+moon|emoji|half[\s-]?moon|moon\s+sign)\b"
)

# Sizing the rover itself is not a planet-size ask.
_ROVER_SIZE = re.compile(
    r"(?i)\b(?:how\s+(?:big|wide|large|heavy)|size)\b[^?]{0,20}\bmars\s+rover\b|"
    r"\bmars\s+rover(?:['\u2019]s)?\s+size\b"
)


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _period_hours_minutes(days: float) -> tuple[int, int]:
    total_min = round(days * 24.0 * 60.0)
    hours, minutes = divmod(total_min, 60)
    return hours, minutes


def _size_plain(radii_km: tuple[float, float, float]) -> str:
    """Axis radii from the fact sheet as rounded diameters, e.g. 26 x 23 x 18 km."""
    return "about " + " x ".join(str(round(2.0 * r)) for r in radii_km) + " km"


def _earths_inside_jupiter_plain() -> str:
    return f"About {int(round(JUPITER_VOLUME_RATIO_TO_EARTH, -2)):,} Earths"


def _phobos_laps_per_mars_day() -> int:
    return round(MARS_DAY_HOURS / (float(PHOBOS["orbit_period_days"]) * 24.0))


def _mars_day_plain() -> str:
    # 24.6597 h -> about 24 hours 40 minutes
    return "about 24 hours 40 minutes"


def _phobos_period_plain() -> str:
    h, m = _period_hours_minutes(float(PHOBOS["orbit_period_days"]))
    return f"about {h} hours {m} minutes"


def _deimos_period_plain() -> str:
    h, m = _period_hours_minutes(float(DEIMOS["orbit_period_days"]))
    return f"about {h} hours {m} minutes"


def looks_like_planet_size_ask(text: str) -> bool:
    """True when the person asks which planet is biggest or how big one is."""
    if _FALSE_MARS.search(text or "") or _ROVER_SIZE.search(text or ""):
        return False
    return _first_unnegated(_PLANET_SIZE_ASK, text) is not None


def looks_like_mars_moons_ask(text: str) -> bool:
    """True for Mars moons / Phobos / Deimos, not candy or concerts."""
    raw = text or ""
    if _FALSE_MARS.search(raw) or _FALSE_MOON.search(raw):
        return False
    return _first_unnegated(_MARS_MOONS_ASK, raw) is not None


_PLANET_NAMES = (
    "Mercury",
    "Venus",
    "Earth",
    "Mars",
    "Jupiter",
    "Saturn",
    "Uranus",
    "Neptune",
)


def _named_planets(text: str) -> list[str]:
    raw = text or ""
    hits: list[tuple[int, str]] = []
    for name in _PLANET_NAMES:
        found = re.search(rf"(?i)\b{name}\b", raw)
        if found:
            hits.append((found.start(), name))
    return [name for _, name in sorted(hits)]


def planet_size_reference_lines(text: str = "") -> list[str]:
    """Short lines for planet size / ranking asks."""
    jup = EQUATORIAL_DIAMETER_KM["Jupiter"]
    ratio = DIAMETER_RATIO_TO_EARTH["Jupiter"]
    mass = MASS_RATIO_TO_EARTH["Jupiter"]
    lines = [
        f"Largest planet: {LARGEST_PLANET}.",
        (
            f"Jupiter equatorial diameter {_fmt_int(jup)} km, "
            f"about {round(ratio)} times wider than Earth (diameter ratio {ratio:g}), "
            f"about {round(mass)} times heavier (mass ratio {mass:g})."
        ),
        (
            f"{_earths_inside_jupiter_plain()} would fit inside Jupiter "
            f"(volume ratio {JUPITER_VOLUME_RATIO_TO_EARTH:g})."
        ),
        f"Earth equatorial diameter {_fmt_int(EQUATORIAL_DIAMETER_KM['Earth'])} km.",
    ]
    for name in _named_planets(text):
        if name in ("Jupiter", "Earth"):
            continue
        lines.append(
            f"{name} equatorial diameter {_fmt_int(EQUATORIAL_DIAMETER_KM[name])} km, "
            f"{DIAMETER_RATIO_TO_EARTH[name]:g} times Earth's diameter."
        )
    return lines


def mars_moons_reference_lines(text: str = "") -> list[str]:
    """Short lines for Mars moons / Phobos / Deimos asks."""
    del text
    ph_dist = _fmt_int(int(PHOBOS["mean_distance_km"]))
    de_dist = _fmt_int(int(DEIMOS["mean_distance_km"]))
    return [
        f"Mars has {MARS_MOON_COUNT} moons: Phobos (inner, bigger) and Deimos (outer, smaller).",
        f"A Mars day is {_mars_day_plain()} ({MARS_DAY_HOURS:g} hours).",
        (
            f"Phobos mean distance from Mars center {ph_dist} km; "
            f"orbit period {_phobos_period_plain()} "
            f"({PHOBOS['orbit_period_days']} days); "
            f"goes around about {_phobos_laps_per_mars_day()} times per Mars day; "
            "rises in the west and sets in the east about twice a day; "
            f"size {_size_plain(PHOBOS['axis_radii_km'])}."
        ),
        (
            f"Deimos mean distance from Mars center {de_dist} km; "
            f"orbit period {_deimos_period_plain()} "
            f"({DEIMOS['orbit_period_days']} days), "
            "longer than a Mars day; "
            "rises in the east and sets in the west, slowly; "
            f"size {_size_plain(DEIMOS['axis_radii_km'])}."
        ),
    ]


def reference_facts_message(text: str) -> str | None:
    """One system message with only the facts that match this ask, or None."""
    lines: list[str] = []
    if looks_like_mars_moons_ask(text):
        lines.extend(mars_moons_reference_lines(text))
    if looks_like_planet_size_ask(text):
        lines.extend(planet_size_reference_lines(text))
    if not lines:
        return None
    return _PREFIX + "\n" + "\n".join(lines)


def body_fact_lines(name: str) -> list[str]:
    """Extra catalog lines for solar action=body. Empty when unknown."""
    key = (name or "").strip().title()
    lines: list[str] = []
    if key in EQUATORIAL_DIAMETER_KM:
        diam = EQUATORIAL_DIAMETER_KM[key]
        lines.append(f"equatorial diameter {_fmt_int(diam)} km (NASA fact sheet)")
        ratio = DIAMETER_RATIO_TO_EARTH.get(key)
        if ratio is not None and key != "Earth":
            lines.append(f"{ratio:g} times Earth's diameter (NASA ratio)")
        mass = MASS_RATIO_TO_EARTH.get(key)
        if mass is not None and key == "Jupiter":
            lines.append(f"{mass:g} times Earth's mass (NASA ratio)")
    if key == "Phobos":
        lines.append(
            f"mean distance from Mars center {_fmt_int(int(PHOBOS['mean_distance_km']))} km"
        )
        lines.append(f"orbit period {_phobos_period_plain()} ({PHOBOS['orbit_period_days']} days)")
        lines.append("rises in the west and sets in the east about twice a day")
        lines.append(f"inner moon of Mars; size {_size_plain(PHOBOS['axis_radii_km'])}")
    if key == "Deimos":
        lines.append(
            f"mean distance from Mars center {_fmt_int(int(DEIMOS['mean_distance_km']))} km"
        )
        lines.append(
            f"orbit period {_deimos_period_plain()} ({DEIMOS['orbit_period_days']} days), "
            "longer than a Mars day"
        )
        lines.append("rises in the east and sets in the west, slowly")
        lines.append(f"outer moon of Mars; size {_size_plain(DEIMOS['axis_radii_km'])}")
    return lines


def append_reference_facts(messages: list[dict[str, str]], text: str) -> bool:
    """Append the NASA reference block when the ask matches. Returns True if added."""
    block = reference_facts_message(text)
    if not block:
        return False
    messages.append({"role": "system", "content": block})
    return True
