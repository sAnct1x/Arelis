"""Spoken and typed Earth go-to. Gazetteer, not a web geocode."""

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
