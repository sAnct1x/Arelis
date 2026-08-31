"""Named Earth destinations. Closed speech, not a web geocode.

Continents and aliases always ship. Countries and cities come from
Natural Earth when the cache is warm. States and provinces use admin-1
when cached, plus a cold list so California still works on a fresh
checkout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_ARTICLE = re.compile(r"(?i)^(the|a|an)\s+")
_KIND_OF = re.compile(
    r"(?i)^(city|state|province|prefecture|country|nation|continent|"
    r"region|territory)\s+of\s+"
)

CONTINENTS: tuple[tuple[str, float, float], ...] = (
    ("Africa", 7.2, 21.0),
    ("Antarctica", -80.0, 0.0),
    ("Asia", 34.0, 100.0),
    ("Europe", 54.0, 15.0),
    ("North America", 48.0, -100.0),
    ("South America", -15.0, -58.0),
    ("Oceania", -18.0, 147.0),
)

ALIASES: dict[str, str] = {
    "usa": "United States",
    "us": "United States",
    "u.s.": "United States",
    "u.s.a.": "United States",
    "america": "United States",
    "the states": "United States",
    "united states of america": "United States",
    "uk": "United Kingdom",
    "u.k.": "United Kingdom",
    "britain": "United Kingdom",
    "great britain": "United Kingdom",
    "gb": "United Kingdom",
    "england": "England",
    "scotland": "Scotland",
    "wales": "Wales",
    "uae": "United Arab Emirates",
    "u.a.e.": "United Arab Emirates",
    "korea": "South Korea",
    "south korea": "South Korea",
    "holland": "Netherlands",
    "the netherlands": "Netherlands",
    "nyc": "New York",
    "new york city": "New York",
    "la": "Los Angeles",
    "l.a.": "Los Angeles",
    "sf": "San Francisco",
    "dc": "Washington",
    "d.c.": "Washington",
    "washington dc": "Washington",
    "washington d.c.": "Washington",
    "oz": "Australia",
    "down under": "Australia",
}

_ADMIN1_FALLBACK: tuple[tuple[str, float, float], ...] = (
    ("Alabama", 32.8, -86.8),
    ("Alaska", 64.2, -153.4),
    ("Arizona", 34.3, -111.7),
    ("Arkansas", 34.9, -92.4),
    ("California", 37.0, -119.4),
    ("Colorado", 39.0, -105.5),
    ("Connecticut", 41.6, -72.7),
    ("Delaware", 39.0, -75.5),
    ("Florida", 28.1, -82.0),
    ("Georgia", 32.7, -83.4),
    ("Hawaii", 20.8, -156.3),
    ("Idaho", 44.4, -114.6),
    ("Illinois", 40.0, -89.4),
    ("Indiana", 39.9, -86.3),
    ("Iowa", 42.0, -93.5),
    ("Kansas", 38.5, -98.3),
    ("Kentucky", 37.8, -85.8),
    ("Louisiana", 31.2, -92.0),
    ("Maine", 45.3, -69.2),
    ("Maryland", 39.1, -76.8),
    ("Massachusetts", 42.3, -71.8),
    ("Michigan", 44.3, -85.4),
    ("Minnesota", 46.3, -94.3),
    ("Mississippi", 32.7, -89.7),
    ("Missouri", 38.4, -92.5),
    ("Montana", 47.1, -110.4),
    ("Nebraska", 41.5, -99.8),
    ("Nevada", 39.3, -116.6),
    ("New Hampshire", 43.7, -71.6),
    ("New Jersey", 40.2, -74.7),
    ("New Mexico", 34.4, -106.1),
    ("New York", 43.0, -75.5),
    ("North Carolina", 35.6, -79.4),
    ("North Dakota", 47.5, -100.3),
    ("Ohio", 40.4, -82.8),
    ("Oklahoma", 35.6, -97.5),
    ("Oregon", 43.9, -120.6),
    ("Pennsylvania", 40.9, -77.8),
    ("Rhode Island", 41.7, -71.6),
    ("South Carolina", 33.9, -80.9),
    ("South Dakota", 44.4, -100.2),
    ("Tennessee", 35.8, -86.4),
    ("Texas", 31.5, -99.3),
    ("Utah", 39.3, -111.7),
    ("Vermont", 44.0, -72.7),
    ("Virginia", 37.5, -78.9),
    ("Washington", 47.4, -120.5),
    ("West Virginia", 38.6, -80.6),
    ("Wisconsin", 44.6, -89.8),
    ("Wyoming", 43.0, -107.6),
    ("Ontario", 50.0, -85.0),
    ("Quebec", 52.0, -72.0),
    ("British Columbia", 54.0, -125.0),
    ("Alberta", 55.0, -115.0),
    ("Manitoba", 55.0, -97.0),
    ("Saskatchewan", 54.0, -106.0),
    ("Nova Scotia", 45.1, -63.2),
    ("New Brunswick", 46.5, -66.1),
    ("Newfoundland and Labrador", 53.0, -60.0),
    ("Prince Edward Island", 46.3, -63.2),
    ("Yukon", 64.0, -135.0),
    ("Northwest Territories", 64.0, -119.0),
    ("Nunavut", 70.0, -90.0),
    ("New South Wales", -32.0, 147.0),
    ("Victoria", -37.0, 144.5),
    ("Queensland", -22.0, 144.0),
    ("Western Australia", -26.0, 122.0),
    ("South Australia", -30.0, 135.0),
    ("Tasmania", -42.0, 147.0),
    ("Northern Territory", -19.0, 133.0),
    ("Australian Capital Territory", -35.5, 149.1),
    ("England", 52.5, -1.5),
    ("Scotland", 56.8, -4.2),
    ("Wales", 52.3, -3.8),
    ("Northern Ireland", 54.6, -6.7),
    ("Bavaria", 48.9, 11.4),
)

FALLBACK_PLACES: tuple[tuple[str, float, float], ...] = (
    ("Tokyo", 35.6762, 139.6503),
    ("London", 51.5074, -0.1278),
    ("New York", 40.7128, -74.0060),
    ("Paris", 48.8566, 2.3522),
    ("Sydney", -33.8688, 151.2093),
    ("São Paulo", -23.5505, -46.6333),
    ("Cairo", 30.0444, 31.2357),
    ("Lagos", 6.5244, 3.3792),
    ("Mumbai", 19.0760, 72.8777),
    ("Mexico City", 19.4326, -99.1332),
    ("Los Angeles", 34.0522, -118.2437),
    ("Berlin", 52.5200, 13.4050),
    ("Singapore", 1.3521, 103.8198),
    ("Toronto", 43.6532, -79.3832),
    ("Nairobi", -1.2921, 36.8219),
    ("San Francisco", 37.7749, -122.4194),
    ("Washington", 38.9072, -77.0369),
    ("Seoul", 37.5665, 126.9780),
    ("Dubai", 25.2048, 55.2708),
)

FALLBACK_COUNTRIES: tuple[tuple[str, float, float], ...] = (
    ("Japan", 36.2, 138.3),
    ("United Kingdom", 54.0, -2.0),
    ("United States", 39.8, -98.6),
    ("France", 46.6, 2.2),
    ("Australia", -25.0, 134.0),
    ("Brazil", -14.2, -51.9),
    ("Egypt", 26.8, 30.8),
    ("Nigeria", 9.1, 8.7),
    ("India", 20.6, 79.0),
    ("Mexico", 23.6, -102.5),
    ("Germany", 51.2, 10.4),
    ("Canada", 56.1, -106.3),
    ("Kenya", 0.0, 37.9),
    ("South Korea", 36.5, 127.8),
    ("Netherlands", 52.2, 5.3),
    ("United Arab Emirates", 24.0, 54.0),
    ("Russia", 64.0, 100.0),
    ("China", 35.9, 104.2),
    ("Italy", 42.8, 12.6),
    ("Spain", 40.2, -3.7),
)

_BODIES = frozenset({"earth", "the earth", "moon", "the moon", "sun", "the sun"})
_KIND_RANK = {"home": 0, "continent": 1, "country": 2, "state": 3, "city": 4}


@dataclass(frozen=True)
class GotoHit:
    kind: str
    name: str
    lat: float
    lon: float
    entity_id: str = ""

    def as_place(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "lat": self.lat,
            "lon": self.lon,
        }


def home_hit() -> GotoHit | None:
    """Profile lat/lon only. No IP lookup — that stays opt-in."""
    try:
        from arelis.location.providers import ManualProfileProvider
        from arelis.profile import resolve_profile_path
    except Exception:
        return None
    try:
        loc = ManualProfileProvider(resolve_profile_path()).resolve()
    except Exception:
        return None
    if loc is None or loc.latitude is None or loc.longitude is None:
        return None
    label = (loc.city or loc.region or loc.country or "home").strip() or "home"
    return GotoHit("home", label, float(loc.latitude), float(loc.longitude))


def normalize_place(raw: str) -> str:
    blob = (raw or "").strip().strip(".,!?")
    blob = _KIND_OF.sub("", blob)
    blob = _ARTICLE.sub("", blob).strip()
    return blob


def catalog() -> list[GotoHit]:
    out: list[GotoHit] = []
    seen: set[tuple[str, str]] = set()

    def take(hit: GotoHit) -> None:
        key = (hit.kind, hit.name.casefold())
        if key in seen or not hit.name:
            return
        seen.add(key)
        out.append(hit)

    home = home_hit()
    if home is not None:
        take(home)
    for name, lat, lon in CONTINENTS:
        take(GotoHit("continent", name, lat, lon))
    try:
        from arelis.earth.land import admin1_places, country_fills, fill_names, places, places_dense

        names = fill_names()
        fills = country_fills()
        if names and fills:
            for name, ring in zip(names, fills, strict=False):
                label = (name or "").strip()
                if not label or not ring:
                    continue
                lat = sum(p[0] for p in ring) / len(ring)
                lon = sum(p[1] for p in ring) / len(ring)
                take(GotoHit("country", label, lat, lon))
        else:
            for name, lat, lon in FALLBACK_COUNTRIES:
                take(GotoHit("country", name, lat, lon))
        admin = admin1_places()
        for name, lat, lon in admin or _ADMIN1_FALLBACK:
            take(GotoHit("state", name, lat, lon))
        rows = list(places_dense() or places() or []) or list(FALLBACK_PLACES)
        for name, lat, lon in rows:
            take(GotoHit("city", name, lat, lon))
    except Exception:
        for name, lat, lon in FALLBACK_COUNTRIES:
            take(GotoHit("country", name, lat, lon))
        for name, lat, lon in _ADMIN1_FALLBACK:
            take(GotoHit("state", name, lat, lon))
        for name, lat, lon in FALLBACK_PLACES:
            take(GotoHit("city", name, lat, lon))
    if not any(h.kind == "state" for h in out):
        for name, lat, lon in _ADMIN1_FALLBACK:
            take(GotoHit("state", name, lat, lon))
    return out


def resolve_place(query: str, zone: Any = None) -> GotoHit | None:
    """One confident destination, or None — never guess into the wrong country."""
    raw_fold = (query or "").strip().strip(".,!?").casefold()
    q = normalize_place(query).casefold()
    if not q or q in _BODIES:
        return None
    if q in {"home", "here"} or raw_fold in {"home", "here"}:
        return home_hit()
    alias = ALIASES.get(q) or ALIASES.get(raw_fold)
    target = (alias or normalize_place(query)).casefold()
    rows = catalog()
    if zone is not None and getattr(zone, "active", False):
        try:
            from arelis.earth.lod import entity_lla

            for ent in zone.search(query):
                pair = entity_lla(ent)
                if pair is None:
                    continue
                rows.append(
                    GotoHit(
                        "contact" if ent.layer == "people" else ent.layer,
                        ent.label,
                        pair[0],
                        pair[1],
                        ent.id,
                    )
                )
        except Exception:
            pass
    exact = [h for h in rows if h.name.casefold() == target]
    if exact:
        if q in {
            "nyc",
            "new york city",
            "new york",
            "dc",
            "d.c.",
            "washington dc",
            "washington d.c.",
            "la",
            "l.a.",
            "sf",
        }:
            city = next((h for h in exact if h.kind == "city"), None)
            if city is not None:
                return city
        exact.sort(key=lambda h: _KIND_RANK.get(h.kind, 9))
        return exact[0]
    if len(q) < 3:
        return None
    prefixed = [h for h in rows if h.name.casefold().startswith(q)]
    names = {h.name.casefold() for h in prefixed}
    if len(names) == 1:
        prefixed.sort(key=lambda h: _KIND_RANK.get(h.kind, 9))
        return prefixed[0]
    return None
