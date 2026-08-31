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


def band_phrase(band: str) -> str:
    return BAND_PHRASE.get(band, "on Earth")


def live_chip_label(*, on: bool, busy: bool = False) -> str:
    if busy:
        return "Live …"
    return "Live on" if on else "Live off"


def status_sentence(zone: Any) -> str:
    """One line a person can read without the docs."""
    if zone is None or not getattr(zone, "active", False):
        return "solar"
    band = ""
    view = getattr(zone, "last_view", None)
    if view is not None:
        band = str(getattr(view, "band", "") or "")
    where = band_phrase(band)
    if zone.live:
        line = f"Watching Earth {where} — live published feeds."
    else:
        line = f"Watching Earth {where} — simulated. Click Live for published feeds."
    ride = str(getattr(zone, "ride_id", "") or "")
    track = str(getattr(zone, "track_id", "") or "")
    if ride:
        line += f" Riding {ride}."
    elif track:
        line += f" Tracking {track}."
    return line


def enter_note(*, live: bool, n: int) -> str:
    mode = "live published feeds" if live else "simulated"
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


def coach_line(zone: Any) -> str | None:
    """The one next action. Empty once they are live and the box has contacts."""
    if zone is None or not zone.active:
        return None
    if not zone.live:
        return "Click Live to see published planes, ships, and weather."
    deaf = deaf_line(zone)
    if deaf:
        return deaf
    return None


def inspect_kind_line(layer: str, freshness: str) -> str:
    kind = LAYER_PHRASE.get(layer, layer)
    fresh = FRESH_PHRASE.get(freshness, freshness)
    return f"{kind} · {fresh}"
