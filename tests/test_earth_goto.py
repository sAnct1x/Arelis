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


@pytest.mark.asyncio
async def test_geocoder_accepts_only_an_extracted_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain string never geocodes. Chat geocodes a pinned or qualified place."""
    from arelis.earth import gazetteer
    from arelis.earth.geocode import NOMINATIM_HOST, clear_cache, search_address
    from arelis.spatial.verbs import classify_physics_act
    from arelis.ui.earth_find import apply_goto
    from arelis.ui.world_host import apply_physics_act

    clear_cache()
    calls: list[str] = []
    passed: list[object] = []
    real_resolve = gazetteer.resolve_place

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

    def spy(query: object, zone: object = None):
        passed.append(query)
        return real_resolve(query, zone)

    monkeypatch.setattr("arelis.earth.geocode.httpx.get", fake_get)
    monkeypatch.setattr("arelis.earth.geocode._block_network", lambda: False)
    monkeypatch.setattr(gazetteer, "resolve_place", spy)

    class _Find:
        def __init__(self, query: str) -> None:
            self._earth_find_q = query
            self._earth_find_hits: list[object] = []
            self._earth_find_ix = 0
            self._earth_find_on = True
            self.place: dict[str, object] | None = None

        def update(self) -> None:
            return None

        def _select_earth_place(self, place: dict[str, object]) -> None:
            self.place = place

    try:
        assert search_address("my notes about physics", force=True) == []
        assert search_address("what is 3 body problem", force=True) == []
        assert resolve_place("remind me about Main Street") is None
        short = "show me my notes about the 3 body problem"
        captured = "my notes about the 3 body problem"
        assert resolve_place(short) is None
        assert classify_physics_act(short) is None
        assert classify_physics_act("show me pictures") is None
        assert classify_physics_act("show me the weather") is None
        assert calls == []
        assert short not in calls
        assert captured not in calls

        london = resolve_place("London")
        assert london is not None and london.name == "London"
        california = resolve_place("California")
        assert california is not None and california.kind == "state"
        paris = resolve_place("Paris")
        assert paris is not None and paris.name == "Paris"
        ohio = resolve_place("Ohio")
        assert ohio is not None and ohio.kind == "state"
        assert calls == []

        monkeypatch.setattr("arelis.ui.world_host.world_available", lambda: True)
        monkeypatch.setattr("arelis.ui.world_host.toggle_world", lambda *a, **k: None)
        monkeypatch.setattr("arelis.physics.runtime.get_system", lambda: None)
        earth = EarthRuntime()
        set_earth(earth)

        class _Window:
            def __init__(self) -> None:
                self.thinking = self

            def append(self, *_args: object, **_kwargs: object) -> None:
                return None

        window = _Window()
        act = classify_physics_act("show me Columbus, Ohio")
        assert act is not None and act.verb == "goto_earth"
        assert act.name == "Columbus, Ohio"
        assert calls == []
        apply_physics_act(window, act)
        assert calls == ["Columbus, Ohio"]
        assert "show me Columbus, Ohio" not in calls
        dest = earth.take_goto()
        assert dest is not None
        assert dest["name"] == "Columbus, Ohio"
        assert dest["lat"] == 40.0
        assert dest["lon"] == -83.0

        assert resolve_place("Reykjavik") is None
        rey = classify_physics_act("show me Reykjavik")
        assert rey is not None and rey.verb == "goto_earth"
        assert rey.name == "Reykjavik"
        assert calls == ["Columbus, Ohio"]
        apply_physics_act(window, rey)
        assert calls == ["Columbus, Ohio", "Reykjavik"]
        assert "show me Reykjavik" not in calls
        flown = earth.take_goto()
        assert flown is not None
        assert flown["name"] == "Reykjavik"
        assert flown["lat"] == 40.0
        assert flown["lon"] == -83.0
        apply_physics_act(window, classify_physics_act("show me reykjavik"))
        assert earth.take_goto() is not None

        monkeypatch.setattr("arelis.tools.earth_tool.stage_ok", lambda: True)
        got = await EarthTool().run(action="goto", query="Columbus, Ohio")
        assert got.ok, got.output
        assert calls == ["Columbus, Ohio", "Reykjavik"]
        assert short not in calls
        again = earth.take_goto()
        assert again is not None
        assert again["lat"] == 40.0
        assert again["lon"] == -83.0

        columbus = _Find("Columbus, Ohio")
        assert apply_goto(columbus) is True
        assert columbus.place is not None
        assert columbus.place["name"] == "Columbus, Ohio"
        street = _Find("10 Downing Street, London")
        assert apply_goto(street) is True
        assert street.place is not None
        assert street.place["name"] == "10 Downing Street, London"
        assert calls == ["Columbus, Ohio", "Reykjavik", "10 Downing Street, London"]
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




def test_failed_spoken_goto_says_the_miss_in_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A place lookup that fails must not reply "Done: goto_earth X." (issue 430)."""
    from arelis.earth.geocode import clear_cache
    from arelis.ui.world_host import _PLATE_ONLY, try_physics_verb

    clear_cache()
    set_earth(EarthRuntime())
    replies: list[str] = []

    class _Chat:
        def begin_assistant(self) -> None:
            return None

        def finish_assistant(self, text: str) -> None:
            replies.append(text)

    class _Window:
        world_window = None
        chat = _Chat()

        def __init__(self) -> None:
            self.thinking = self

        def append(self, *_args: object, **_kwargs: object) -> None:
            return None

    assert resolve_place("Reykjavik") is None
    assert try_physics_verb(_Window(), "show me Reykjavik") is True
    assert try_physics_verb(_Window(), "take me home") is True
    monkeypatch.setattr("arelis.ui.world_host.world_available", lambda: False)
    assert try_physics_verb(_Window(), "show me Paris") is True
    assert replies == [
        "I don't know a place named 'Reykjavik'.",
        "Set a home city in your profile first.",
        _PLATE_ONLY,
    ]
