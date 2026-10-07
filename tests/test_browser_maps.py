"""Google Maps URL helpers. Query keys are parsed, not compared as one string."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from arelis.browser.maps import (
    maps_directions_url,
    maps_phone_link,
    normalize_travel_mode,
)


def _query(url: str) -> dict[str, list[str]]:
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.google.com"
    assert parsed.path == "/maps/dir/"
    return parse_qs(parsed.query)


def test_normalize_travel_mode_aliases_and_fallback() -> None:
    assert normalize_travel_mode("walk") == "walking"
    assert normalize_travel_mode(" Walk ") == "walking"
    assert normalize_travel_mode("bus") == "transit"
    assert normalize_travel_mode("BUS") == "transit"
    assert normalize_travel_mode("bike") == "bicycling"
    assert normalize_travel_mode("car") == "driving"
    assert normalize_travel_mode("driving") == "driving"
    assert normalize_travel_mode("") == "driving"
    assert normalize_travel_mode("   ") == "driving"
    assert normalize_travel_mode("rocket") == "driving"


def test_maps_directions_url_puts_destination_mode_and_origin_in_the_query() -> None:
    url = maps_directions_url(
        "  Example Park  ",
        origin=" Sample Museum ",
        mode="walk",
    )
    query = _query(url)
    assert query["destination"] == ["Example Park"]
    assert query["travelmode"] == ["walking"]
    assert query["origin"] == ["Sample Museum"]
    assert query["api"] == ["1"]

    bus = _query(maps_directions_url("Example Park", origin="Sample Museum", mode="bus"))
    assert bus["travelmode"] == ["transit"]
    bike = _query(maps_directions_url("Example Park", mode="bike"))
    assert bike["travelmode"] == ["bicycling"]
    car = _query(maps_directions_url("Example Park", mode="car"))
    assert car["travelmode"] == ["driving"]


def test_maps_directions_url_omits_a_blank_origin() -> None:
    for origin in ("", "   "):
        query = _query(maps_directions_url("Example Park", origin=origin, mode="car"))
        assert "origin" not in query
        assert query["destination"] == ["Example Park"]
        assert query["travelmode"] == ["driving"]


def test_maps_phone_link_never_includes_an_origin() -> None:
    query = _query(maps_phone_link("Origin Park", mode="bus"))
    assert "origin" not in query
    assert query["destination"] == ["Origin Park"]
    assert query["travelmode"] == ["transit"]
    assert query["api"] == ["1"]

    walking = _query(maps_phone_link("Example Park", mode="walk"))
    assert "origin" not in walking
    assert walking["travelmode"] == ["walking"]
