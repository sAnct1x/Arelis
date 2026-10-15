"""Earth globe stack and Cesium bridge contract. No WebEngine required."""

from __future__ import annotations

from arelis.earth.globe_stack import (
    CESIUM_JS,
    GIBS_NEAR_XYZ,
    GIBS_NIGHT_XYZ,
    GIBS_XYZ,
    GOOGLE_3D,
    OSM_XYZ,
    choose_stack,
)
from arelis.earth.runtime import EarthRuntime, set_earth
from arelis.ui.earth_globe_host import (
    entity_rows,
    globe_line,
    parse_globe_line,
)


def test_stack_picks_photoreal_then_ion_then_gibs() -> None:
    assert choose_stack(google_key="", ion_token="").kind == "gibs"
    assert choose_stack(google_key="", ion_token="token").kind == "ion"
    stack = choose_stack(google_key="maps-key", ion_token="ion")
    assert stack.kind == "photoreal"
    payload = stack.to_payload()
    assert payload["googleKey"] == "maps-key"
    assert "NASA" in payload["credits"]
    assert "Google" in payload["credits"]
    assert payload["photorealAltM"] == "8000"
    assert "enterLat" in payload
    assert "enterLon" in payload
    assert payload["enterAltM"] == "20000000"
    lat = float(payload["enterLat"])
    lon = float(payload["enterLon"])
    assert abs(lat) <= 50.0
    assert abs(lon) <= 180.0
    assert "VIIRS_Black_Marble" in payload["gibsNight"]
    assert "VIIRS_SNPP_CorrectedReflectance_TrueColor" in payload["gibsNear"]
    assert "/default/default/" not in payload["gibsNear"]
    assert "gibs.earthdata.nasa.gov" in GIBS_NIGHT_XYZ
    assert "gibs.earthdata.nasa.gov" in GIBS_NEAR_XYZ
    assert payload["cesiumBase"].startswith("https://cesium.com/")
    assert payload["cesiumBase"].endswith("/")
    assert "cesium.com" in CESIUM_JS
    assert "gibs.earthdata.nasa.gov" in GIBS_XYZ
    assert "tile.googleapis.com" in GOOGLE_3D
    assert "tile.openstreetmap.org" in OSM_XYZ


def test_entity_rows_skip_people_and_carry_lla() -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.frames import lla_to_ecef
    from arelis.earth.lod import EarthView

    set_earth(None)
    earth = EarthRuntime()
    earth.active = True
    earth.layers["flights"] = True
    earth.last_view = EarthView(band="approach", lat=39.7817, lon=-89.6501)
    x, y, z = lla_to_ecef(39.7817, -89.6501, 10_000.0)
    earth.store.upsert(
        Entity(
            id="flt:1",
            cls="aircraft",
            layer="flights",
            label="TEST1",
            x=x,
            y=y,
            z=z,
            meta={"lat": 39.7817, "lon": -89.6501, "alt": 10000.0, "track_deg": 45.0},
        )
    )
    earth.store.upsert(
        Entity(
            id="p:1",
            cls="person",
            layer="people",
            label="nope",
            x=x,
            y=y,
            z=z,
            meta={"lat": 39.7817, "lon": -89.6501},
        )
    )
    set_earth(earth)
    rows = entity_rows()
    assert all(row["id"] != "p:1" for row in rows)
    hit = next(row for row in rows if row["id"] == "flt:1")
    assert hit["lat"] == 39.7817
    assert hit["lon"] == -89.6501
    assert hit["layer"] == "flights"
    assert hit["mark"] == "flights"
    assert hit["heading_deg"] == 45.0
    assert hit["freshness"] == "simulated"
    assert "vx" in hit
    assert "when_unix" in hit
    set_earth(None)


def test_globe_line_roundtrip() -> None:
    raw = globe_line({"event": "hwnd", "hwnd": 42})
    assert raw.endswith(b"\n")
    msg = parse_globe_line(raw)
    assert msg == {"event": "hwnd", "hwnd": 42}
    assert parse_globe_line(b"") is None
    assert parse_globe_line(b"not-json") is None


