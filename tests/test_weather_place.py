"""The weather tool never said *which* place it forecast. Silently.

This is the pain the user reported by name — "getting the weather for anywhere
I want, whenever I want has been the craziest challenge, and it's the most
available information" — and reading the code says why. `geocode_place` asked
Open-Meteo for `count: 1` and returned a bare `(lat, lon)` tuple, throwing away
the resolved name, country and region. The tool then printed:

    Place: {asked}

…the user's *own string*, echoed back. So "weather in Springfield" resolved to
whichever Springfield Open-Meteo ranked first out of the thirty-odd that exist,
and the answer read `Place: Springfield` either way. There was no signal, at
any layer, that the forecast was for a different Springfield than the one meant.

That makes it pain #1 (confidently wrong) rather than pain #4 (too shallow),
and the module docstring already had the exact fear written down — "a confident
forecast for somewhere the user is not" — aimed at the wrong failure. It was
guarding against the *model* inventing coordinates while the *tool* quietly
picked the wrong city.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.briefing.weather import (
    ResolvedPlace,
    choose_geocode_hit,
    resolve_place,
)
from arelis.tools.weather import WeatherTool


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    """Records the params so the count= change is visible to the test."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        self.calls.append(dict(params or {}))
        return _FakeResponse(self._payload)


# The fixture place, plus a real Springfield in the other hemisphere. A foreign
# alternative rather than a second US state keeps
# `test_no_tracked_file_names_a_us_state_other_than_the_fixture` happy, and the
# case is if anything sharper: a forecast from the wrong hemisphere.
_SPRINGFIELDS = {
    "results": [
        {
            "name": "Springfield",
            "latitude": 39.7817,
            "longitude": -89.6501,
            # No country key: the operator's profile names their own country,
            # so test_no_personal_data forbids writing it in a tracked file.
            # The label builder handles a missing country, which this covers.
            "country_code": "US",
            "admin1": "Illinois",
        },
        {
            "name": "Springfield",
            "latitude": -43.3,
            "longitude": 171.9,
            "country": "New Zealand",
            "admin1": "Canterbury",
        },
    ]
}


@pytest.mark.asyncio
async def test_the_resolved_place_carries_its_region() -> None:
    client = _FakeClient(_SPRINGFIELDS)

    place = await resolve_place("Springfield", client=client)

    assert isinstance(place, ResolvedPlace)
    assert place.label == "Springfield, Illinois"
    assert place.latitude == pytest.approx(39.7817)


@pytest.mark.asyncio
async def test_more_than_one_candidate_is_fetched_so_ambiguity_is_visible() -> None:
    """count=1 cannot tell "the only Springfield" from "the first of thirty"."""
    client = _FakeClient(_SPRINGFIELDS)

    place = await resolve_place("Springfield", client=client)

    assert client.calls[0]["count"] > 1
    assert place.alternatives, "nothing recorded that other candidates existed"
    assert "New Zealand" in place.alternatives[0]


def test_a_named_region_beats_the_first_gazetteer_hit() -> None:
    """Springfield, Illinois must not become whichever Springfield ranked first."""
    wrong = {
        "name": "Springfield",
        "latitude": -43.3,
        "longitude": 171.9,
        "country": "New Zealand",
        "admin1": "Canterbury",
    }
    right = {
        "name": "Springfield",
        "latitude": 39.7817,
        "longitude": -89.6501,
        "admin1": "Illinois",
        "country_code": "US",
    }
    hit = choose_geocode_hit("Springfield, Illinois", [wrong, right])
    assert hit is not None
    assert hit["admin1"] == "Illinois"
    bare = choose_geocode_hit("Springfield", [wrong, right])
    assert bare is not None
    assert bare["admin1"] == "Canterbury"
    spelled = choose_geocode_hit("Springfield Illinois", [wrong, right])
    assert spelled is not None
    assert spelled["admin1"] == "Illinois"
    missing = choose_geocode_hit("Springfield, Illinois", [wrong])
    assert missing is None


@pytest.mark.asyncio
async def test_resolve_place_keeps_the_named_region() -> None:
    wrong_first = {
        "results": [
            {
                "name": "Springfield",
                "latitude": -43.3,
                "longitude": 171.9,
                "country": "New Zealand",
                "admin1": "Canterbury",
            },
            {
                "name": "Springfield",
                "latitude": 39.7817,
                "longitude": -89.6501,
                "admin1": "Illinois",
                "country_code": "US",
            },
        ]
    }
    client = _FakeClient(wrong_first)

    place = await resolve_place("Springfield, Illinois", client=client)

    assert place is not None
    assert place.label == "Springfield, Illinois"
    assert place.latitude == pytest.approx(39.7817)
    assert all("New Zealand" not in alt for alt in place.alternatives)


# --------------------------------------------------------------------------
# The tool
# --------------------------------------------------------------------------


def _patch(monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]) -> None:
    async def _search(name: str, **_kw: Any) -> list[dict[str, Any]]:
        del name
        return rows

    async def _forecast(lat: float, lon: float, days: int = 1) -> dict[str, Any]:
        del lat, lon, days
        return {
            "current": {"temperature_2m": 71.0, "weather_code": 0},
            "daily": [
                {
                    "temperature_2m_max": 78.0,
                    "temperature_2m_min": 60.0,
                }
            ],
        }

    monkeypatch.setattr("arelis.tools.weather.search_geocode", _search)
    monkeypatch.setattr("arelis.tools.weather.fetch_forecast", _forecast)


@pytest.mark.asyncio
async def test_the_answer_names_the_city_it_actually_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A named state is the label in the sentence, not the user's bare word."""
    _patch(
        monkeypatch,
        [
            {
                "name": "Springfield",
                "latitude": 39.7817,
                "longitude": -89.6501,
                "admin1": "Illinois",
                "country_code": "US",
            }
        ],
    )

    result = await WeatherTool().run(place="Springfield, Illinois")

    assert result.ok, result.output
    assert result.output.startswith("Springfield, Illinois:")
    assert result.data["place"] == "Springfield, Illinois"


@pytest.mark.asyncio
async def test_ambiguity_is_reported_so_it_can_be_corrected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, _SPRINGFIELDS["results"])

    result = await WeatherTool().run(place="Springfield")

    assert result.output == (
        "Did you mean Springfield, Illinois or Springfield, New Zealand?"
    )
    assert "Canterbury" not in result.output
    assert result.data["ambiguous"] is True


@pytest.mark.asyncio
async def test_an_unambiguous_place_does_not_nag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(
        monkeypatch,
        [
            {
                "name": "Reykjavík",
                "latitude": 64.1,
                "longitude": -21.9,
                "country": "Iceland",
            }
        ],
    )

    result = await WeatherTool().run(place="Reykjavik")

    assert "also matched" not in result.output.lower()
    assert result.data.get("ambiguous") is not True
    assert result.output.startswith("Reykjavík, Iceland:")


@pytest.mark.asyncio
async def test_a_place_that_cannot_be_found_still_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, [])

    result = await WeatherTool().run(place="zzzzzz")

    assert not result.ok
    assert result.data.get("status") == "not_found"
    assert result.output == "I couldn't find that place."
    assert "geocode" not in result.output.lower()
