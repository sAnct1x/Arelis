"""Reality field: enter, inspect, coast, ocean, city, look-from.

Chips, bands, cards, look, and which catalogs can paint where.
Pytest stays simulated.
"""

from __future__ import annotations

from arelis.earth.copy import inspect_kind_line
from arelis.earth.frames import lla_to_ecef
from arelis.earth.lod import EarthView, look_bbox, paint_layers
from arelis.earth.runtime import EarthRuntime
from arelis.earth.simulate import PORTS
from arelis.ui.earth_overlay import earth_chip_items, inspect_card_text


def _view(band: str, lat: float, lon: float, alt_m: float) -> EarthView:
    return EarthView(
        band,
        alt_m=alt_m,
        lat=lat,
        lon=lon,
        bbox=look_bbox(lat, lon, band),
    )


def _on(earth: EarthRuntime, *layers: str) -> None:
    for key in earth.layers:
        earth.layers[key] = key in layers


def test_field_enter_shows_iss_and_the_card() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth.note_view(_view("space", 0.0, 0.0, 3_000_000.0))
    iss = earth.get("norad:25544")
    assert iss is not None
    assert iss.layer == "iss"
    assert earth.layers["iss"] is True
    assert earth.layers["cameras"] is False
    vis = {e.layer for e in earth.visible()}
    assert vis <= {"iss", "satellites", "quakes", "fires"}
    assert "iss" in vis
    assert "quakes" in vis
    assert "fires" in vis
    text = inspect_card_text(iss)
    assert "ISS" in text
    assert "click to ride" in text
    assert "Esc to leave it" in text
    assert "TEME" not in text


def test_field_ocean_opens_boats_not_cameras() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    lat, lon = PORTS[1][1], PORTS[1][2]  # Singapore strait
    earth.note_view(_view("near", lat, lon, 12_000.0))
    _on(earth, "iss", "satellites", "vessels", "cameras")
    vis = list(earth.visible())
    layers = {e.layer for e in vis}
    assert "vessels" in layers
    assert "cameras" not in layers
    assert "cameras" not in paint_layers("near")
    chips = dict(earth_chip_items("near"))
    assert "vessels" in chips
    assert "cameras" not in chips
    assert any("ship" in inspect_kind_line(e.layer, e.freshness) for e in vis)


def test_field_city_opens_cameras_radio_weather() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    earth.note_view(_view("city", 51.508, -0.128, 2_500.0))
    _on(earth, "cameras", "radio", "weather", "traffic")
    vis = list(earth.visible())
    have = {e.layer for e in vis}
    assert "cameras" in have
    assert "radio" in have
    assert "weather" in have
    labels = {e.label for e in vis if e.layer == "cameras"}
    assert any("Trafalgar" in name or "London" in name for name in labels)
    radio = {e.label for e in vis if e.layer == "radio"}
    assert any("BBC" in name for name in radio)
    chips = dict(earth_chip_items("city"))
    for kind in ("cameras", "radio", "weather", "traffic", "fires", "sites"):
        assert kind in chips


def test_field_military_and_drones_have_their_own_marks() -> None:
    from arelis.earth.entity import Entity
    from arelis.ui.earth_marks import HEADING_KINDS, mark_digest

    earth = EarthRuntime()
    earth.enter(unix=1.0)
    for layer, eid, alt in (
        ("military", "field:mil", 8_000.0),
        ("drones", "field:uav", 400.0),
    ):
        pos = lla_to_ecef(40.7, -74.0, alt)
        earth.store.upsert(
            Entity(
                id=eid,
                cls="aircraft",
                layer=layer,
                label=layer,
                x=pos[0],
                y=pos[1],
                z=pos[2],
                freshness="delayed",
                source="ADS-B",
                meta={"lat": 40.7, "lon": -74.0, "track_deg": 90.0},
            )
        )
    earth.note_view(_view("near", 40.7, -74.0, 30_000.0))
    _on(earth, "flights", "military", "drones")
    have = {e.layer for e in earth.visible()}
    assert "flights" in have
    assert "military" in have
    assert "drones" in have
    assert mark_digest("military", band="city") != mark_digest("flights", band="city")
    assert mark_digest("drones", band="city") != mark_digest("flights", band="city")
    assert "military" in HEADING_KINDS
    assert "drones" in HEADING_KINDS
    chips = dict(earth_chip_items("near"))
    assert "military" in chips
    assert "drones" in chips


