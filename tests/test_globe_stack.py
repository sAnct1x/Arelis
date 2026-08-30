"""Earth globe stack and Cesium bridge contract. No WebEngine required."""

from __future__ import annotations

from arelis.earth.globe_stack import (
    CESIUM_JS,
    GIBS_XYZ,
    GOOGLE_3D,
    OSM_XYZ,
    choose_stack,
)
from arelis.earth.runtime import EarthRuntime, set_earth
from arelis.ui.earth_globe_host import (
    building_rows,
    entity_rows,
    place_rows,
    webengine_available,
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
    assert payload["photorealAltM"] == "80000"
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
    set_earth(None)


def test_entity_rows_vessel_cog_and_freshness() -> None:
    from arelis.earth.entity import Entity
    from arelis.earth.frames import lla_to_ecef
    from arelis.earth.lod import EarthView

    set_earth(None)
    earth = EarthRuntime()
    earth.active = True
    earth.layers["vessels"] = True
    earth.last_view = EarthView(band="near", lat=39.7817, lon=-89.6501)
    x, y, z = lla_to_ecef(39.7817, -89.6501, 0.0)
    earth.store.upsert(
        Entity(
            id="ves:1",
            cls="vessel",
            layer="vessels",
            label="TESTSHIP",
            x=x,
            y=y,
            z=z,
            freshness="live",
            meta={"lat": 39.7817, "lon": -89.6501, "cog_deg": 270.0},
        )
    )
    set_earth(earth)
    rows = entity_rows()
    hit = next(row for row in rows if row["id"] == "ves:1")
    assert hit["mark"] == "vessels"
    assert hit["heading_deg"] == 270.0
    assert hit["freshness"] == "live"
    set_earth(None)


def test_photoreal_miss_does_not_fail_the_host(qt_app, monkeypatch) -> None:
    monkeypatch.setattr(
        "arelis.ui.earth_globe_host.webengine_available", lambda: False
    )
    from arelis.ui.earth_globe_host import EarthGlobeHost

    host = EarthGlobeHost()
    host.failed = False
    host._on_failed("photoreal")
    assert host.failed is False
    host._on_failed("cesium")
    assert host.failed is True
    host.hide()


def test_building_rows_need_city_and_the_chip(tmp_path) -> None:
    from arelis.earth.buildings import _cache_dir_for_tests
    from arelis.earth.lod import EarthView

    _cache_dir_for_tests(tmp_path)
    key = "39.78_-89.65"
    (tmp_path / f"{key}.json").write_text(
        '{"unix": 1, "rings": [[[39.78, -89.65], [39.781, -89.650], [39.7817, -89.6501]]]}',
        encoding="utf-8",
    )
    earth = EarthRuntime()
    earth.active = True
    earth.buildings = True
    earth.last_view = EarthView(band="space", lat=39.7817, lon=-89.6501)
    set_earth(earth)
    assert building_rows() == []
    earth.last_view = EarthView(band="city", lat=39.7817, lon=-89.6501)
    earth.buildings = False
    assert building_rows() == []
    earth.buildings = True
    rows = building_rows()
    assert len(rows) == 1
    assert rows[0][0] == [39.78, -89.65]
    set_earth(None)
    from arelis.paths import state_dir

    _cache_dir_for_tests(state_dir() / "earth" / "buildings")


def test_place_rows_space_is_empty() -> None:
    assert place_rows("space", 0.0, 0.0) == []
    near = place_rows("approach", 0.0, 0.0)
    assert isinstance(near, list)
    assert len(near) <= 8
    assert webengine_available() in {True, False}


def test_hud_glass_does_not_forward_events() -> None:
    from arelis.ui.earth_globe_host import GLOBE_DIR

    host = (GLOBE_DIR.parent / "earth_globe_host.py").read_text(encoding="utf-8")
    js = (GLOBE_DIR / "bridge.js").read_text(encoding="utf-8")
    html = (GLOBE_DIR / "index.html").read_text(encoding="utf-8")
    assert "sendEvent" not in host
    assert "skyBox" in js
    assert "if (viewer.scene.skyBox)" in js
    assert "baseLayer: false" in js
    assert "CESIUM_BASE_URL" in js
    assert "billboard" in js
    assert "PinBuilder" not in js
    assert js.count("billboard") > js.count("point:")
    assert "marksJson" in js
    assert "marksJson" in host
    assert "push_marks" in host
    assert 'bridge.failed("photoreal")' not in js
    assert "buildingsJson" in host
    assert "setBuildings" in js
    assert "bldg:" in js
    assert "transparent" in html
    stack = (GLOBE_DIR.parent.parent / "earth" / "globe_stack.py").read_text(
        encoding="utf-8"
    )
    blob = html + js + stack
    for banned in ("NOFORN", "KH11", "Gods Eye", "TOP SECRET"):
        assert banned not in blob
