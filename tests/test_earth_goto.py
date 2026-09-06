"""Spoken and typed Earth go-to. Gazetteer first; addresses via Nominatim."""

from __future__ import annotations

import pytest

from arelis.earth.gazetteer import resolve_place
from arelis.earth.goto import suggest
from arelis.earth.land import admin1_from_geojson
from arelis.earth.runtime import EarthRuntime, set_earth
from arelis.tools.earth_tool import EarthTool


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    set_earth(None)
    monkeypatch.setattr(
        "arelis.earth.runtime.EarthRuntime._merge_local",
        lambda self: None,
    )
    yield
    set_earth(None)


def test_resolve_place_is_confident_only() -> None:
    tokyo = resolve_place("Tokyo")
    assert tokyo is not None
    assert tokyo.name == "Tokyo"
    assert tokyo.kind == "city"
    japan = resolve_place("Japan")
    assert japan is not None
    assert japan.kind == "country"
    cal = resolve_place("California")
    assert cal is not None
    assert cal.kind == "state"
    africa = resolve_place("Africa")
    assert africa is not None
    assert africa.kind == "continent"
    uk = resolve_place("the UK")
    assert uk is not None
    assert uk.name == "United Kingdom"
    usa = resolve_place("usa")
    assert usa is not None
    assert usa.name == "United States"
    assert resolve_place("bed") is None
    assert resolve_place("earth") is None
    assert resolve_place("New") is None
    nyc = resolve_place("nyc")
    assert nyc is not None
    assert nyc.kind == "city"
    assert nyc.name == "New York"


def test_suggest_still_ranks_tokyo_first() -> None:
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    tok = suggest("tok", earth)
    assert tok and tok[0].name == "Tokyo"
    africa = suggest("africa", earth)
    assert any(h.name == "Africa" and h.kind == "continent" for h in africa)


def test_admin1_centroids_from_geojson() -> None:
    found = admin1_from_geojson(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"NAME": "California"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-120.0, 36.0],
                                [-118.0, 36.0],
                                [-118.0, 38.0],
                                [-120.0, 38.0],
                                [-120.0, 36.0],
                            ]
                        ],
                    },
                }
            ],
        }
    )
    assert found
    assert found[0][0] == "California"
    assert 36.0 < found[0][1] < 38.0
    assert -120.0 < found[0][2] < -118.0


@pytest.mark.asyncio
async def test_earth_tool_goto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: True)
    earth = EarthRuntime()
    set_earth(earth)
    tool = EarthTool()
    got = await tool.run(action="goto", query="Tokyo")
    assert got.ok, got.output
    assert got.data["name"] == "Tokyo"
    assert earth.active is True
    dest = earth.take_goto()
    assert dest is not None
    assert dest["name"] == "Tokyo"
    miss = await tool.run(action="goto", query="bed")
    assert not miss.ok


def test_pending_goto_flies_on_the_plate(qt_app, monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth.gazetteer import resolve_place
    from arelis.ui.panels.solar import SolarPanel

    monkeypatch.setattr("arelis.earth.runtime.EarthRuntime._merge_live", lambda self: None)
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    hit = resolve_place("Tokyo")
    assert hit is not None
    earth.request_goto(hit)
    panel = SolarPanel()
    panel.resize(960, 720)
    panel._apply_pending_earth_goto()
    assert panel._place is not None
    assert panel._place["name"] == "Tokyo"
    assert panel._earth_fly is not None


def test_cesium_owns_the_city_fly(qt_app, monkeypatch: pytest.MonkeyPatch) -> None:
    """One Cesium flyTo — not Python mixing ECEF and setView every tick."""
    from arelis.earth.gazetteer import resolve_place
    from arelis.ui.panels.solar import SolarPanel

    monkeypatch.setattr("arelis.earth.runtime.EarthRuntime._merge_live", lambda self: None)
    earth = EarthRuntime()
    earth.enter(unix=1.0)
    set_earth(earth)
    hit = resolve_place("Tokyo")
    assert hit is not None
    flown: list[tuple[float, float, float]] = []

    class Host:
        failed = False

        def isVisible(self) -> bool:
            return True

        def fly_to(self, lat: float, lon: float, alt_m: float) -> None:
            flown.append((lat, lon, alt_m))

    panel = SolarPanel()
    panel.resize(960, 720)
    panel._globe_host = Host()
    panel._select_earth_place(hit.as_place())
    assert panel._earth_fly is None
    assert len(flown) == 1
    assert flown[0][2] < 40_000.0


def test_geocode_stays_offline_under_pytest(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth import geocode

    geocode.clear_cache()
    called: list[int] = []

    def boom(*_a, **_k):
        called.append(1)
        raise AssertionError("Nominatim must not run in pytest")

    monkeypatch.setattr(geocode.httpx, "get", boom)
    assert geocode.search_address("1600 Pennsylvania Avenue") == []
    assert called == []


def test_looks_like_address_is_not_a_city_name() -> None:
    from arelis.earth.geocode import looks_like_address

    assert looks_like_address("1600 Pennsylvania Avenue")
    assert looks_like_address("10 Downing Street, London")
    assert looks_like_address("Main Street")
    assert not looks_like_address("Tokyo")
    assert not looks_like_address("to")
    assert not looks_like_address("California")


def test_resolve_place_uses_cached_address(monkeypatch: pytest.MonkeyPatch) -> None:
    from arelis.earth import geocode
    from arelis.earth.gazetteer import GotoHit, resolve_place

    geocode.clear_cache()
    hit = GotoHit(
        "address",
        "1600 Pennsylvania Avenue NW, Washington, DC",
        38.8977,
        -77.0365,
    )
    geocode.remember_hits("1600 Pennsylvania Avenue", [hit])
    found = resolve_place("1600 Pennsylvania Avenue")
    assert found is not None
    assert found.kind == "address"
    assert found.lat == pytest.approx(38.8977)
    geocode.clear_cache()
    monkeypatch.setattr(geocode, "search_address", lambda *a, **k: [])
    assert resolve_place("1600 Pennsylvania Avenue") is None


def test_scale_bar_reads_like_a_map() -> None:
    from arelis.earth.scale import format_agl, format_distance, scale_bar

    nice, bar_px, label = scale_bar(350.0, 1200.0)
    assert nice <= 200.0
    assert 24 <= bar_px <= 400
    assert label.endswith("m")
    assert format_distance(1000.0) == "1 km"
    assert format_distance(200.0) == "200 m"
    assert format_agl(2400.0) == "2.4 km AGL"
    assert format_agl(350.0).endswith("AGL")
    from arelis.earth.scale import format_surface, scale_from_mpp, show_map_scale
    from arelis.ui.earth_marks import BAND_PX, mark_size

    nice, bar_px, mpp_label = scale_from_mpp(25.0)
    assert nice == 2000.0
    assert 36 <= bar_px <= 160
    assert mpp_label == "2 km"
    assert format_surface(46_558_000.0) == "46558 km to surface"
    assert show_map_scale(alt_m=46_558_000.0, mpp=15_000.0) is False
    assert show_map_scale(alt_m=2_400.0, mpp=25.0) is True
    assert mark_size("space") >= 36
    assert BAND_PX["space"] >= 36


def test_nav_range_waits_for_cesium() -> None:
    from types import SimpleNamespace

    from arelis.ui.earth_chrome import nav_range_m

    empty = SimpleNamespace(_earth_agl_m=None, _earth_nadir_m=None)
    assert nav_range_m(empty) is None
    assert nav_range_m(SimpleNamespace(_earth_agl_m=None, _earth_nadir_m=0)) is None
    assert nav_range_m(SimpleNamespace(_earth_agl_m=2400.0, _earth_nadir_m=None)) == 2400.0
    assert nav_range_m(SimpleNamespace(_earth_agl_m=2400.0, _earth_nadir_m=1800.0)) == 1800.0
