"""Native Earth inspect: east on the right, city band reachable, honest field."""

from __future__ import annotations

from arelis.earth.lod import _NEAR_ALT_M, band_from_view
from arelis.ui.panels.solar_earth import (
    CITY_LOOK_ALT_M,
    earth_goto_alt_m,
    earth_zoom_factor,
)


def test_city_goto_opens_city_band() -> None:
    """Take me to Tokyo used to park at 80 km — near band, photoreal black."""
    alt = earth_goto_alt_m("city")
    assert alt == CITY_LOOK_ALT_M
    assert alt < _NEAR_ALT_M
    assert band_from_view(alt_m=alt, px_r=800.0, locked=True) == "city"
    assert earth_goto_alt_m("home") == CITY_LOOK_ALT_M
    assert earth_goto_alt_m("address") == 350.0
    assert earth_goto_alt_m("address") < _NEAR_ALT_M
    assert band_from_view(
        alt_m=earth_goto_alt_m("address"), px_r=800.0, locked=True
    ) == "city"
    assert band_from_view(
        alt_m=earth_goto_alt_m("continent"), px_r=80.0, locked=True
    ) == "space"


def test_earth_wheel_falls_faster_than_a_solar_cruise() -> None:
    inward = earth_zoom_factor(120.0)
    assert 0.70 <= inward <= 0.82


def test_ground_detail_waits_for_altitude() -> None:
    from arelis.earth.lod import (
        BUILDING_ALT_M,
        ROAD_ALT_M,
        ground_buildings_on,
        ground_streets_on,
    )

    assert ground_streets_on(band="near", alt_m=2_000.0) is False
    assert ground_streets_on(band="city", alt_m=ROAD_ALT_M + 1.0) is False
    assert ground_streets_on(band="city", alt_m=ROAD_ALT_M) is True
    assert ground_buildings_on(band="city", alt_m=BUILDING_ALT_M + 1.0) is False
    assert ground_buildings_on(band="city", alt_m=BUILDING_ALT_M) is True


def test_streets_chip_is_osm_not_gibs() -> None:
    from arelis.earth.tiles import GIBS_BLUE, OSM_TILE
    from arelis.ui.earth_overlay import earth_chip_items

    assert "openstreetmap.org" in OSM_TILE
    assert "gibs.earthdata.nasa.gov" in GIBS_BLUE
    assert OSM_TILE != GIBS_BLUE
    assert ("tiles", "Streets") in earth_chip_items("city")
    assert ("tiles", "Streets") not in earth_chip_items("near")
    assert ("tiles", "Streets") not in earth_chip_items("approach")


