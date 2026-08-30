"""Distance-gated Earth live. Do not slam every adapter from space.

Bands follow the inspect altitude (when the eye rides ECEF) or the
globe's pixel radius (when it is still a disc in the solar lab):

- space: satellites only
- approach: local planes
- near: boats and planes; no satellite refresh
- city: every layer that is toggled on

Look-area bbox is what OpenSky and post-filters use. Layer chips still
win: a dark chip is not fetched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from arelis.earth.entity import LAYER_IDS, Entity
from arelis.earth.frames import ecef_to_geodetic, ecef_to_lla

BANDS = ("space", "approach", "near", "city")

# Metres above the WGS84 sketch geoid. Google Earth-ish, not a survey.
_SPACE_ALT_M = 2_500_000.0
_APPROACH_ALT_M = 400_000.0
_NEAR_ALT_M = 40_000.0

# Disc size when the eye is still inertial (whole-Earth in frame).
_SPACE_PX = 72.0
_APPROACH_PX = 220.0
_NEAR_PX = 520.0

# Half-width of the look box, degrees. Wider farther out.
_BBOX_HALF: dict[str, float] = {
    "approach": 12.0,
    "near": 5.0,
    "city": 1.2,
}

# Per-adapter TTL. Catalog dumps stay warm; moving air/sea refresh.
ADAPTER_TTL_S: dict[str, float] = {
    "celestrak": 600.0,
    "spacetrack": 600.0,
    "tip": 600.0,
    "opensky": 40.0,
    "adsb": 40.0,
    "ais": 40.0,
    "usgs": 180.0,
    "emsc": 180.0,
    "geonet": 180.0,
    "firms": 180.0,
    "radar": 300.0,
    "gfw": 300.0,
    "eonet": 180.0,
    "gdacs": 180.0,
    "cameras": 900.0,
    "shodan": 900.0,
    "traffic": 900.0,
    "weather": 300.0,
    "nws": 300.0,
    "metar": 180.0,
    "waqi": 300.0,
    "openaq": 300.0,
    "ndbc": 300.0,
    "tides": 300.0,
    "rwis": 300.0,
    "swpc": 300.0,
    "radio": 600.0,
    "aprs": 120.0,
    "satnogs": 600.0,
    "launches": 600.0,
    "airports": 1800.0,
    "volcanoes": 1800.0,
    "argo": 1800.0,
    "fdsn": 1800.0,
}

ADAPTER_LAYERS: dict[str, frozenset[str]] = {
    "celestrak": frozenset({"satellites", "iss"}),
    "spacetrack": frozenset({"satellites", "iss"}),
    "tip": frozenset({"satellites"}),
    "opensky": frozenset({"flights", "drones"}),
    "adsb": frozenset({"military"}),
    "ais": frozenset({"vessels"}),
    "usgs": frozenset({"quakes"}),
    "emsc": frozenset({"quakes"}),
    "geonet": frozenset({"quakes"}),
    "firms": frozenset({"fires"}),
    "radar": frozenset({"radar"}),
    "gfw": frozenset({"radar"}),
    "cameras": frozenset({"cameras"}),
    "shodan": frozenset({"cameras"}),
    "traffic": frozenset({"traffic"}),
    "weather": frozenset({"weather"}),
    "nws": frozenset({"weather"}),
    "metar": frozenset({"weather"}),
    "waqi": frozenset({"weather"}),
    "openaq": frozenset({"weather"}),
    "ndbc": frozenset({"weather"}),
    "tides": frozenset({"weather"}),
    "rwis": frozenset({"weather"}),
    "swpc": frozenset({"weather"}),
    "radio": frozenset({"radio"}),
    "aprs": frozenset({"radio"}),
    "satnogs": frozenset({"radio"}),
    "launches": frozenset({"sites"}),
    "eonet": frozenset({"sites"}),
    "airports": frozenset({"sites"}),
    "volcanoes": frozenset({"sites"}),
    "gdacs": frozenset({"sites"}),
    "argo": frozenset({"sites"}),
    "fdsn": frozenset({"sites"}),
}

ADAPTER_BANDS: dict[str, frozenset[str]] = {
    "celestrak": frozenset({"space"}),
    "spacetrack": frozenset({"space"}),
    "tip": frozenset({"space"}),
    "opensky": frozenset({"approach", "near", "city"}),
    "adsb": frozenset({"near", "city"}),
    "ais": frozenset({"near", "city"}),
    "usgs": frozenset({"city"}),
    "emsc": frozenset({"city"}),
    "geonet": frozenset({"city"}),
    "firms": frozenset({"city"}),
    "radar": frozenset({"city"}),
    "gfw": frozenset({"city"}),
    "cameras": frozenset({"city"}),
    "shodan": frozenset({"city"}),
    "traffic": frozenset({"city"}),
    "weather": frozenset({"city"}),
    "nws": frozenset({"city"}),
    "metar": frozenset({"city"}),
    "waqi": frozenset({"city"}),
    "openaq": frozenset({"city"}),
    "ndbc": frozenset({"city"}),
    "tides": frozenset({"city"}),
    "rwis": frozenset({"city"}),
    "swpc": frozenset({"city"}),
    "radio": frozenset({"city"}),
    "aprs": frozenset({"city"}),
    "satnogs": frozenset({"city"}),
    "launches": frozenset({"city"}),
    "eonet": frozenset({"city"}),
    "airports": frozenset({"city"}),
    "volcanoes": frozenset({"city"}),
    "gdacs": frozenset({"city"}),
    "argo": frozenset({"city"}),
    "fdsn": frozenset({"city"}),
}

PAINT_LAYERS: dict[str, frozenset[str]] = {
    "space": frozenset({"iss", "satellites"}),
    "approach": frozenset({"flights", "drones"}),
    "near": frozenset({"flights", "drones", "military", "vessels"}),
    "city": frozenset(LAYER_IDS),
}

# Chips that earn a seat at this band. The rest stay off the bar.
CHIP_LAYERS: dict[str, tuple[str, ...]] = {
    "space": ("satellites", "iss"),
    "approach": ("flights", "drones"),
    "near": ("flights", "drones", "military", "vessels"),
}

# After bbox filter, keep the nearest N so the plate stays readable.
LAYER_CAP: dict[str, int] = {
    "satellites": 220,
    "iss": 4,
    "flights": 400,
    "drones": 80,
    "military": 80,
    "vessels": 300,
    "cameras": 200,
    "traffic": 200,
    "weather": 150,
    "radio": 80,
    "quakes": 200,
    "fires": 200,
    "radar": 40,
    "sites": 200,
    "people": 80,
}

def _sibs(*names: str) -> dict[str, tuple[str, ...]]:
    group = tuple(names)
    return {name: group for name in names}


# Shared replace_layer buckets. If one is due, fetch the siblings together
# so a partial poll does not wipe the rest of the layer.
SIBLINGS: dict[str, tuple[str, ...]] = {
    **_sibs("celestrak", "spacetrack", "tip"),
    **_sibs("usgs", "emsc", "geonet"),
    **_sibs("cameras", "shodan"),
    **_sibs("radar", "gfw"),
    **_sibs("radio", "aprs", "satnogs"),
    **_sibs(
        "weather",
        "nws",
        "swpc",
        "metar",
        "waqi",
        "openaq",
        "ndbc",
        "tides",
        "rwis",
    ),
}

# Orbital layers are not a look-box problem.
_NO_BBOX = frozenset({"satellites", "iss"})


@dataclass(frozen=True)
class LookBBox:
    south: float
    west: float
    north: float
    east: float

    def wraps(self) -> bool:
        return self.west > self.east

    def split(self) -> tuple[LookBBox, ...]:
        """OpenSky cannot take west > east. Two boxes across the date line."""
        if not self.wraps():
            return (self,)
        return (
            LookBBox(self.south, self.west, self.north, 180.0),
            LookBBox(self.south, -180.0, self.north, self.east),
        )


@dataclass(frozen=True)
class EarthView:
    band: str
    alt_m: float = 0.0
    px_r: float = 0.0
    lat: float = 0.0
    lon: float = 0.0
    bbox: LookBBox | None = None


def band_from_view(*, alt_m: float | None, px_r: float, locked: bool) -> str:
    """Farther band when in doubt — fewer adapters, not more."""
    if locked and alt_m is not None:
        if alt_m >= _SPACE_ALT_M:
            return "space"
        if alt_m >= _APPROACH_ALT_M:
            return "approach"
        if alt_m >= _NEAR_ALT_M:
            return "near"
        return "city"
    if px_r < _SPACE_PX:
        return "space"
    if px_r < _APPROACH_PX:
        return "approach"
    if px_r < _NEAR_PX:
        return "near"
    return "city"


def look_bbox(lat: float, lon: float, band: str) -> LookBBox | None:
    half = _BBOX_HALF.get(band)
    if half is None:
        return None
    lat = max(-90.0, min(90.0, float(lat)))
    lon = _wrap_lon(float(lon))
    south = max(-90.0, lat - half)
    north = min(90.0, lat + half)
    west = _wrap_lon(lon - half)
    east = _wrap_lon(lon + half)
    return LookBBox(south, west, north, east)


def view_from_eye(
    eye_ecef: tuple[float, float, float],
    *,
    px_r: float,
    locked: bool,
    look_ecef: tuple[float, float, float] | None = None,
) -> EarthView:
    """Nadir from the inspect eye, or the ECEF look point when we have one."""
    _lat, _lon, alt = ecef_to_geodetic(*eye_ecef)
    if look_ecef is not None:
        lat, lon, _ = ecef_to_geodetic(*look_ecef)
    else:
        lat, lon = _lat, _lon
    band = band_from_view(alt_m=alt, px_r=px_r, locked=locked)
    return EarthView(
        band=band,
        alt_m=alt,
        px_r=px_r,
        lat=lat,
        lon=lon,
        bbox=look_bbox(lat, lon, band),
    )


def paint_layers(band: str) -> frozenset[str]:
    return PAINT_LAYERS.get(band, PAINT_LAYERS["city"])


def chip_layers(band: str) -> tuple[str, ...] | None:
    """None means every catalog layer (city, or unknown)."""
    if not band or band == "city":
        return None
    return CHIP_LAYERS.get(band)


def adapter_allowed(
    key: str,
    band: str,
    layers: dict[str, bool] | None = None,
) -> bool:
    bands = ADAPTER_BANDS.get(key)
    if bands is not None and band not in bands:
        return False
    if layers is None:
        return True
    needed = ADAPTER_LAYERS.get(key)
    if not needed:
        return True
    return any(layers.get(layer, False) for layer in needed)


def adapters_due(
    band: str,
    last_fetch: dict[str, float],
    now: float,
    layers: dict[str, bool] | None = None,
    *,
    keys: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    names = keys if keys is not None else tuple(ADAPTER_BANDS)
    raw: list[str] = []
    for key in names:
        if not adapter_allowed(key, band, layers):
            continue
        ttl = ADAPTER_TTL_S.get(key, 120.0)
        if now - float(last_fetch.get(key, 0.0)) >= ttl:
            raw.append(key)
    expanded: set[str] = set()
    for key in raw:
        for sib in SIBLINGS.get(key, (key,)):
            if adapter_allowed(sib, band, layers):
                expanded.add(sib)
    return tuple(sorted(expanded))


def in_bbox(lat: float, lon: float, box: LookBBox) -> bool:
    if lat < box.south or lat > box.north:
        return False
    lon = _wrap_lon(lon)
    if not box.wraps():
        return box.west <= lon <= box.east
    return lon >= box.west or lon <= box.east


def entity_lla(entity: Entity) -> tuple[float, float] | None:
    meta = entity.meta or {}
    lat, lon = meta.get("lat"), meta.get("lon")
    try:
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    except (TypeError, ValueError):
        pass
    lat, lon, _alt = ecef_to_lla(entity.x, entity.y, entity.z)
    return lat, lon


def filter_to_view(entities: list[Entity], view: EarthView | None) -> list[Entity]:
    """Keep look-area contacts. Orbital layers pass. No view = keep all."""
    if view is None or view.bbox is None:
        return list(entities)
    out: list[Entity] = []
    for entity in entities:
        if entity.layer in _NO_BBOX:
            out.append(entity)
            continue
        pair = entity_lla(entity)
        if pair is None:
            continue
        if in_bbox(pair[0], pair[1], view.bbox):
            out.append(entity)
    return out


def organize(entities: list[Entity], view: EarthView | None) -> list[Entity]:
    """Nearest first, then cap per layer so a city dump does not bury the plate."""
    if not entities:
        return []
    lat = view.lat if view is not None else 0.0
    lon = view.lon if view is not None else 0.0

    def key(entity: Entity) -> tuple[float, str, str]:
        pair = entity_lla(entity)
        dist = _haversine_km(lat, lon, pair[0], pair[1]) if pair else 1.0e9
        return (dist, entity.layer, entity.id)

    ranked = sorted(entities, key=key)
    used: dict[str, int] = {}
    out: list[Entity] = []
    for entity in ranked:
        cap = LAYER_CAP.get(entity.layer)
        if cap is not None and used.get(entity.layer, 0) >= cap:
            continue
        used[entity.layer] = used.get(entity.layer, 0) + 1
        out.append(entity)
    return out


def look_shifted(prev: EarthView | None, cur: EarthView, *, fraction: float = 0.45) -> bool:
    """True when the look pin walked a meaningful slice of the current box."""
    if prev is None or prev.band != cur.band:
        return prev is None or prev.band != cur.band
    if cur.bbox is None:
        return False
    half = _BBOX_HALF.get(cur.band, 1.0)
    return _haversine_km(prev.lat, prev.lon, cur.lat, cur.lon) >= 111.0 * half * fraction


def _wrap_lon(lon: float) -> float:
    return ((float(lon) + 180.0) % 360.0) - 180.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * r * math.asin(min(1.0, math.sqrt(a)))
