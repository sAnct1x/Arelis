"""Human sentences for the Earth zone HUD and tool.

Status used to say ECEF and a count. That is for a dump, not a person
standing in front of the plate.
"""

from __future__ import annotations

from typing import Any

BAND_PHRASE: dict[str, str] = {
    "space": "from space",
    "approach": "approaching",
    "near": "near the ground",
    "city": "in the city",
}

FRESH_PHRASE: dict[str, str] = {
    "live": "live",
    "delayed": "delayed",
    "interpolated": "interpolated",
    "dead-reckoned": "coasting · dead-reckoned",
    "simulated": "drawn, not a live feed",
    "reconstructed": "reconstructed",
    "stale": "stale",
    "unavailable": "unavailable",
}

LAYER_PHRASE: dict[str, str] = {
    "flights": "flight",
    "drones": "drone",
    "military": "military aircraft",
    "vessels": "ship",
    "radar": "radar pass",
    "satellites": "satellite",
    "iss": "station",
    "quakes": "earthquake",
    "fires": "fire",
    "weather": "weather",
    "radio": "radio",
    "cameras": "camera",
    "traffic": "traffic",
    "sites": "site",
    "people": "person",
}

GROUP_PHRASE: dict[str, str] = {
    "stations": "space station",
    "gps-ops": "GPS",
    "galileo": "Galileo",
    "glonass": "GLONASS",
    "beidou": "BeiDou",
    "weather": "weather sat",
    "noaa": "NOAA",
    "goes": "GOES",
    "visual": "bright sat",
    "geo": "geostationary",
    "science": "science",
    "resource": "earth resource",
    "sarsat": "SARSAT",
    "dmc": "DMC",
    "tdrss": "TDRSS",
    "amateur": "amateur radio",
    "cubesat": "CubeSat",
    "oneweb": "OneWeb",
    "iridium-NEXT": "Iridium NEXT",
    "planet": "Planet",
    "spire": "Spire",
    "last-30-days": "new launch",
    "starlink": "Starlink",
    "education": "education",
    "engineering": "engineering",
    "military": "public military",
    "intelsat": "Intelsat",
    "ses": "SES",
    "orbcomm": "Orbcomm",
    "globalstar": "Globalstar",
    "iridium": "Iridium",
    "other-comm": "communications",
}


def group_phrase(group: str) -> str:
    key = str(group or "").strip()
    if not key:
        return ""
    return GROUP_PHRASE.get(key, key.replace("-", " "))


def band_phrase(band: str) -> str:
    return BAND_PHRASE.get(band, "on Earth")


_PUBLISHED = frozenset(
    {"live", "delayed", "interpolated", "dead-reckoned", "stale"}
)


# ISS rides on a click. Double-click rides the rest. Ground pins fly-to.
RIDE_LAYERS = frozenset(
    {"cameras", "flights", "drones", "military", "vessels", "iss"}
)


def can_ride(layer: str) -> bool:
    return str(layer or "") in RIDE_LAYERS


def ride_hint(layer: str, *, riding: bool = False) -> str:
    if not can_ride(layer):
        return ""
    if riding:
        return "Esc or click empty sky to hop off"
    if str(layer or "") == "iss":
        return "click to ride · Esc to leave it"
    return "double-click to ride · Esc to leave it"


def live_chip_label(*, on: bool, busy: bool = False) -> str:
    if busy:
        return "Live …"
    return "Live on" if on else "Live off"


def loading_line(
    zone: Any,
    *,
    globe_ready: bool = True,
    globe_failed: bool = False,
    busy: bool = False,
) -> str | None:
    """Quiet status while the plate is still coming up. Empty once it is."""
    if globe_failed:
        return "fancy map failed — NASA ball"
    if not globe_ready:
        return "falling in"
    if not busy:
        return None
    band = ""
    view = getattr(zone, "last_view", None) if zone is not None else None
    if view is not None:
        band = str(getattr(view, "band", "") or "")
    if band in {"", "space"}:
        return "fetching satellites"
    if band == "approach":
        return "fetching flights"
    if band == "near":
        return "fetching ships"
    return "refreshing live"


def has_published(zone: Any) -> bool:
    """A feed replaced at least one layer. Those tracks coast, they are not sim."""
    store = getattr(zone, "store", None)
    if store is None or not hasattr(store, "all"):
        return False
    try:
        for entity in store.all():
            if getattr(entity, "freshness", "") in _PUBLISHED:
                return True
    except Exception:
        return False
    return False


def status_sentence(zone: Any) -> str:
    """One line a person can read without the docs."""
    if zone is None or not getattr(zone, "active", False):
        return "solar"
    band = ""
    view = getattr(zone, "last_view", None)
    if view is not None:
        band = str(getattr(view, "band", "") or "")
    where = band_phrase(band)
    published = has_published(zone)
    busy = bool(getattr(zone, "_live_busy", False))
    if busy and not published:
        line = f"Watching Earth {where} — fetching published feeds."
    elif zone.live and published:
        line = f"Watching Earth {where} — live published feeds."
    elif zone.live:
        line = f"Watching Earth {where} — live, simulated until feeds return."
    elif published:
        line = (
            f"Watching Earth {where} — last published fix, then coasting. "
            "Live keeps pulling."
        )
    else:
        line = f"Watching Earth {where} — simulated. Click Live for published feeds."
    ride = str(getattr(zone, "ride_id", "") or "")
    track = str(getattr(zone, "track_id", "") or "")
    if ride:
        line += f" Riding {ride}."
    elif track:
        line += f" Tracking {track}."
    return line


def enter_note(*, live: bool, n: int, snapshot: bool = False) -> str:
    if live:
        mode = "live published feeds"
    elif snapshot:
        mode = "last published fix, then coast"
    else:
        mode = "simulated"
    return f"Watching Earth — {mode}. {n} contacts ready."


def leave_note() -> str:
    return "Left Earth. Back to the solar lab."


def deaf_line(zone: Any) -> str | None:
    """When Live is on and this look box has nothing public to show."""
    if zone is None or not zone.active or not zone.live:
        return None
    view = getattr(zone, "last_view", None)
    if view is None:
        return None
    band = str(getattr(view, "band", "") or "")
    if band in {"", "space"}:
        return None
    visible = list(zone.visible()) if hasattr(zone, "visible") else []
    if visible:
        return None
    if band == "approach":
        return "No published planes in this view. Quiet sky, not a miss."
    if band == "near":
        return "No published planes or ships here. Mid-ocean VHF is deaf."
    return "No public feed in this view. Sparse is a hole, not a miss."


def layer_hole_line(zone: Any) -> str | None:
    """A chip is on and this look has nothing public for it."""
    if zone is None or not zone.active or not zone.live:
        return None
    layers = getattr(zone, "layers", None) or {}
    fetched = getattr(zone, "last_fetch_unix", None) or {}
    inflight = getattr(zone, "_live_inflight", None) or set()
    visible = list(zone.visible()) if hasattr(zone, "visible") else []
    have = {getattr(ent, "layer", "") for ent in visible}
    if layers.get("cameras"):
        if "cameras" in inflight or "shodan" in inflight:
            return None
        if "cameras" not in fetched and "shodan" not in fetched:
            return None
        if "cameras" not in have:
            return (
                "No published cameras in this look. OSM webcams and keyed "
                "511 only — not every phone on Wi-Fi."
            )
    if layers.get("traffic"):
        if "traffic" in inflight or "traffic" not in fetched:
            return None
        if "traffic" not in have:
            return "No published road incidents here. Traffic is closures, not every car."
    if layers.get("sites"):
        site_keys = (
            "launches",
            "eonet",
            "airports",
            "tip",
            "volcanoes",
            "gdacs",
            "argo",
            "fdsn",
        )
        if any(key in inflight for key in site_keys):
            return None
        if not any(key in fetched for key in site_keys):
            return None
        if "sites" not in have:
            return "No published sites in this look. Airports and pads when the catalog has them."
    return None


def coach_line(zone: Any) -> str | None:
    """The one next action. Empty once they are live and the box has contacts."""
    if zone is None or not zone.active:
        return None
    if not zone.live:
        if has_published(zone):
            return None
        return "Find a city, or say take me to one. Double-click ISS to ride."
    hole = layer_hole_line(zone)
    if hole:
        return hole
    deaf = deaf_line(zone)
    if deaf:
        return deaf
    return None


def inspect_kind_line(layer: str, freshness: str) -> str:
    kind = LAYER_PHRASE.get(layer, layer)
    fresh = FRESH_PHRASE.get(freshness, freshness)
    return f"{kind} · {fresh}"
