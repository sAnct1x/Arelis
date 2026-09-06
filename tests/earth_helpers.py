"""Shared Earth-zone test helpers. Not collected (no test_ prefix)."""

from __future__ import annotations

import pytest

from arelis.earth.runtime import set_earth


def isolate_earth(monkeypatch: pytest.MonkeyPatch):
    """Clear the process-global Earth runtime and block local contacts/cameras."""
    from arelis.earth.look import forget

    set_earth(None)
    forget()
    # Enter must not read the developer's contacts.yaml / secrets cameras.
    monkeypatch.setattr(
        "arelis.earth.runtime.EarthRuntime._merge_local",
        lambda self: None,
    )
    yield
    forget()
    set_earth(None)


_LIVE_FETCHERS = (
    "fetch_usgs",
    "fetch_opensky",
    "fetch_adsb_mil",
    "fetch_ais",
    "fetch_celestrak",
    "fetch_radio",
    "fetch_cameras",
    "fetch_weather",
    "fetch_firms",
    "fetch_launches",
    "fetch_aprs",
    "fetch_shodan",
    "fetch_traffic",
    "fetch_radar",
    "fetch_gfw",
    "fetch_eonet",
    "fetch_nws",
    "fetch_airports",
    "fetch_spacetrack",
    "fetch_tip",
    "fetch_emsc",
    "fetch_swpc",
    "fetch_satnogs",
    "fetch_metar",
    "fetch_waqi",
    "fetch_geonet",
    "fetch_ndbc",
    "fetch_volcanoes",
    "fetch_gdacs",
    "fetch_tides",
    "fetch_argo",
    "fetch_openaq",
    "fetch_rwis",
    "fetch_fdsn",
)


def _mute_live(monkeypatch: pytest.MonkeyPatch, **keep: object) -> None:
    """Stub every live adapter. A new fetch in merge_live must land here."""

    def _none() -> None:
        return None

    for name in _LIVE_FETCHERS:
        monkeypatch.setattr(f"arelis.earth.live.{name}", keep.get(name, _none))


def _ais_envelope(lat: float, lon: float, mmsi: str, name: str = "TEST") -> dict:
    return {
        "MessageType": "PositionReport",
        "MetaData": {
            "MMSI": mmsi,
            "ShipName": name,
            "latitude": lat,
            "longitude": lon,
            "time_utc": "2026-08-28 12:00:00.000000000 +0000 UTC",
        },
        "Message": {
            "PositionReport": {
                "UserID": int(mmsi) if mmsi.isdigit() else 0,
                "Latitude": lat,
                "Longitude": lon,
                "Sog": 12.3,
                "Cog": 180.0,
            }
        },
    }


def _opaque_pixels(img) -> int:
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            if img.pixelColor(x, y).alpha() > 0:
                n += 1
    return n
