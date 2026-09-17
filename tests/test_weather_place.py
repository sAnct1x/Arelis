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

from arelis.briefing.weather import ResolvedPlace, geocode_place, resolve_place
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


@pytest.mark.asyncio
async def test_an_unambiguous_place_has_no_alternatives() -> None:
    client = _FakeClient(
        {
            "results": [
                {
                    "name": "Reykjavík",
                    "latitude": 64.1,
                    "longitude": -21.9,
                    "country": "Iceland",
                }
            ]
        }
    )

    place = await resolve_place("Reykjavik", client=client)

    assert place.label == "Reykjavík, Iceland"
    assert not place.alternatives


@pytest.mark.asyncio
async def test_a_same_country_duplicate_name_is_not_an_alternative() -> None:
    """The same city echoed twice by the API is noise, not ambiguity."""
    client = _FakeClient(
        {
            "results": [
                {
                    "name": "Paris",
                    "latitude": 48.9,
                    "longitude": 2.4,
                    "country": "France",
                    "admin1": "Île-de-France",
                },
                {
                    "name": "Paris",
                    "latitude": 48.9,
                    "longitude": 2.4,
                    "country": "France",
                    "admin1": "Île-de-France",
                },
            ]
        }
    )

    place = await resolve_place("Paris", client=client)

    assert not place.alternatives


@pytest.mark.asyncio
async def test_a_miss_is_none_not_a_crash() -> None:
    client = _FakeClient({"results": []})
    assert await resolve_place("zzzzzz", client=client) is None


@pytest.mark.asyncio
async def test_the_old_tuple_helper_still_works() -> None:
    """briefing/weather.py:141 and the profile path both call this."""
    client = _FakeClient(_SPRINGFIELDS)

    coords = await geocode_place("Springfield", client=client)

    assert coords == (pytest.approx(39.7817), pytest.approx(-89.6501))


# --------------------------------------------------------------------------
# The tool
# --------------------------------------------------------------------------


def _patch(monkeypatch: pytest.MonkeyPatch, place: ResolvedPlace | None) -> None:
    async def _resolve(name: str, **_kw: Any) -> ResolvedPlace | None:
        return place

    async def _forecast(lat: float, lon: float, **_kw: Any) -> dict[str, Any]:
        return {
            "current": {
                "temperature_2m": 71.0,
                "apparent_temperature": 70.0,
                "precipitation": 0.0,
                "weather_code": 0,
            },
            "daily": [
                {
                    "date": "2026-09-17",
                    "weather_code": 0,
                    "temperature_2m_max": 78.0,
                    "temperature_2m_min": 60.0,
                    "precipitation_probability_max": 5,
                }
            ],
        }

    monkeypatch.setattr("arelis.tools.weather.resolve_place", _resolve)
    monkeypatch.setattr("arelis.tools.weather.fetch_forecast", _forecast)


@pytest.mark.asyncio
async def test_the_answer_names_the_city_it_actually_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point. "Place: Springfield" for the wrong hemisphere is a wrong answer
    the user cannot see; "Springfield, Illinois" is one they can correct."""
    _patch(
        monkeypatch,
        ResolvedPlace(
            label="Springfield, Illinois",
            latitude=39.7817,
            longitude=-89.6501,
            alternatives=("Springfield, Canterbury, New Zealand",),
        ),
    )

    result = await WeatherTool().run(place="Springfield")

    assert result.ok, result.output
    assert "Springfield, Illinois" in result.output
    assert result.data["place"] == "Springfield, Illinois"


@pytest.mark.asyncio
async def test_ambiguity_is_reported_so_it_can_be_corrected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(
        monkeypatch,
        ResolvedPlace(
            label="Springfield, Illinois",
            latitude=39.7817,
            longitude=-89.6501,
            alternatives=("Springfield, Canterbury, New Zealand",),
        ),
    )

    result = await WeatherTool().run(place="Springfield")

    assert "New Zealand" in result.output
    assert result.data["ambiguous"] is True


@pytest.mark.asyncio
async def test_an_unambiguous_place_does_not_nag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(
        monkeypatch,
        ResolvedPlace(label="Reykjavík, Iceland", latitude=64.1, longitude=-21.9),
    )

    result = await WeatherTool().run(place="Reykjavik")

    assert "also matched" not in result.output.lower()
    assert result.data["ambiguous"] is False


@pytest.mark.asyncio
async def test_a_place_that_cannot_be_found_still_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch(monkeypatch, None)

    result = await WeatherTool().run(place="zzzzzz")

    assert not result.ok
    assert "geocode" in result.output.lower()
