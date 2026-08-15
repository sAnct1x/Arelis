"""Google Maps URLs for her window and a phone-ready share link."""

from __future__ import annotations

from urllib.parse import quote_plus, urlencode

_MODES = {
    "drive": "driving",
    "driving": "driving",
    "car": "driving",
    "walk": "walking",
    "walking": "walking",
    "transit": "transit",
    "bus": "transit",
    "bike": "bicycling",
    "bicycling": "bicycling",
}


def normalize_travel_mode(mode: str) -> str:
    key = (mode or "driving").strip().lower()
    return _MODES.get(key, "driving")


def maps_search_url(query: str) -> str:
    q = (query or "").strip()
    return "https://www.google.com/maps/search/?api=1&query=" + quote_plus(q)


def maps_directions_url(
    destination: str,
    *,
    origin: str = "",
    mode: str = "driving",
) -> str:
    """Directions URL for her Chrome. Optional origin (home / a named place)."""
    dest = (destination or "").strip()
    params: dict[str, str] = {
        "api": "1",
        "destination": dest,
        "travelmode": normalize_travel_mode(mode),
    }
    orig = (origin or "").strip()
    if orig:
        params["origin"] = orig
    return "https://www.google.com/maps/dir/?" + urlencode(
        params, quote_via=quote_plus
    )


def maps_phone_link(destination: str, *, mode: str = "driving") -> str:
    """Destination-only so the phone can start from GPS."""
    return maps_directions_url(destination, mode=mode)
