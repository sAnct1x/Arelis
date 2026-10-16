"""Spoken and typed Earth go-to. Gazetteer first; addresses via Nominatim."""

from __future__ import annotations

import pytest

from arelis.earth.gazetteer import resolve_place
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


def test_sentence_prompt_never_reaches_the_geocoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A chat sentence is not a place. A city, region line still resolves."""
    from arelis.earth.geocode import NOMINATIM_HOST, clear_cache, search_address
    from arelis.spatial.verbs import classify_physics_act

    clear_cache()
    calls: list[str] = []

    class _Resp:
        def __init__(self, query: str) -> None:
            self._query = query

        def raise_for_status(self) -> None:
            return None

        def json(self) -> list[dict[str, str]]:
            return [
                {
                    "lat": "40.00",
                    "lon": "-83.00",
                    "display_name": self._query,
                    "addresstype": "city",
                }
            ]

    def fake_get(url: str, **kwargs: object) -> _Resp:
        assert NOMINATIM_HOST in str(url)
        params = kwargs.get("params")
        query = ""
        if isinstance(params, dict):
            query = str(params.get("q") or "")
        calls.append(query)
        return _Resp(query)

    monkeypatch.setattr("arelis.earth.geocode.httpx.get", fake_get)
    monkeypatch.setattr("arelis.earth.geocode._block_network", lambda: False)

    prompt = "show me my notes from 2024 about the 3 body problem"
    remainder = "my notes from 2024 about the 3 body problem"
    try:
        assert classify_physics_act(prompt) is None
        assert resolve_place(prompt) is None
        assert resolve_place(remainder) is None
        assert search_address(prompt, force=True) == []
        assert search_address(remainder, force=True) == []
        assert calls == []

        london = resolve_place("London")
        assert london is not None and london.name == "London"
        california = resolve_place("California")
        assert california is not None and california.kind == "state"
        paris = resolve_place("Paris")
        assert paris is not None and paris.name == "Paris"
        assert resolve_place("Paris France") is None
        assert calls == []

        columbus = resolve_place("Columbus, Ohio")
        assert columbus is not None
        assert columbus.name == "Columbus, Ohio"
        assert calls == ["Columbus, Ohio"]

        france = search_address("Paris France", force=True)
        assert france and france[0].name == "Paris France"
        assert calls == ["Columbus, Ohio", "Paris France"]
    finally:
        clear_cache()


def test_scale_bar_reads_like_a_map() -> None:
    from arelis.earth.scale import EARTH_FOV_Y, format_agl, format_distance, scale_bar

    assert EARTH_FOV_Y == 0.70
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


