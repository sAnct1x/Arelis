"""Dedicated weather tool — Open-Meteo without model-invented URLs."""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import TOOL_POLICY
from arelis.location import UserLocation
from arelis.tools.weather import WeatherTool


class _FakeLocation:
    def __init__(self, loc: UserLocation) -> None:
        self._loc = loc

    def snapshot(self) -> UserLocation:
        return self._loc


@pytest.mark.asyncio
async def test_weather_tool_formats_forecast(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_forecast(lat: float, lon: float, *, days: int = 3, **_kw: Any):
        assert lat == 39.7817
        assert lon == -89.6501
        assert days == 3
        return {
            "current": {
                "temperature_2m": 69.3,
                "apparent_temperature": 74.9,
                "precipitation": 0,
                "weather_code": 0,
            },
            "daily": [
                {
                    "date": "2026-08-09",
                    "weather_code": 1,
                    "temperature_2m_max": 82.0,
                    "temperature_2m_min": 61.0,
                    "precipitation_probability_max": 10,
                },
                {
                    "date": "2026-08-10",
                    "weather_code": 61,
                    "temperature_2m_max": 78.0,
                    "temperature_2m_min": 60.0,
                    "precipitation_probability_max": 40,
                },
            ],
        }

    monkeypatch.setattr("arelis.tools.weather.fetch_forecast", _fake_forecast)
    tool = WeatherTool(
        _FakeLocation(
            UserLocation(
                city="Springfield",
                region="Illinois",
                latitude=39.7817,
                longitude=-89.6501,
            )
        )
    )
    result = await tool.run()
    assert result.ok
    assert "Springfield" in result.output
    assert "69.3" in result.output
    assert "2026-08-10" in result.output
    assert "light rain" in result.output


@pytest.mark.asyncio
async def test_weather_tool_needs_coords(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_geo(_name: str, **_kw: Any):
        return None

    monkeypatch.setattr("arelis.tools.weather.geocode_place", _no_geo)
    tool = WeatherTool(_FakeLocation(UserLocation(city="Nowhere")))
    result = await tool.run()
    assert not result.ok
    assert "coordinates" in result.output.lower()


@pytest.mark.asyncio
async def test_weather_ignores_model_invented_coords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_forecast(lat: float, lon: float, *, days: int = 3, **_kw: Any):
        assert lat == 39.7817
        assert lon == -89.6501
        return {
            "current": {
                "temperature_2m": 70.0,
                "apparent_temperature": 70.0,
                "precipitation": 0,
                "weather_code": 0,
            },
            "daily": [],
        }

    monkeypatch.setattr("arelis.tools.weather.fetch_forecast", _fake_forecast)
    tool = WeatherTool(
        _FakeLocation(
            UserLocation(
                city="Springfield",
                region="Illinois",
                latitude=39.7817,
                longitude=-89.6501,
            )
        )
    )
    # Model-invented SF coords must not override the profile.
    result = await tool.run(latitude=37.7749, longitude=-122.4194)
    assert result.ok
    assert "39.7817" in result.output


def test_weather_declares_every_argument_it_reads() -> None:
    """The schema is the whole contract, so nothing may be read behind it.

    latitude/longitude were read by run but declared nowhere, described as
    forbidden, and requested by the failure message. Now days and place are the
    declared keys; coordinates still come from the profile or from geocoding
    place, never from the model.
    """
    declared = set(WeatherTool.parameters_schema["properties"])
    assert declared == {"days", "place"}
    assert "latitude" not in WeatherTool.description.lower()
    assert "longitude" not in WeatherTool.description.lower()


@pytest.mark.asyncio
async def test_missing_coords_points_at_user_location_not_at_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old message asked for arguments the tool does not accept."""

    async def _no_geo(_name: str, **_kw: Any):
        return None

    monkeypatch.setattr("arelis.tools.weather.geocode_place", _no_geo)
    tool = WeatherTool(_FakeLocation(UserLocation(city="Nowhere")))
    result = await tool.run()
    assert not result.ok
    assert "user_location" in result.output
    assert "do not pass coordinates" in result.output.lower()


@pytest.mark.asyncio
async def test_weather_geocodes_profile_city_when_coords_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _geo(name: str, **_kw: Any):
        assert "Springfield" in name
        return (39.7817, -89.6501)

    async def _fake_forecast(lat: float, lon: float, *, days: int = 3, **_kw: Any):
        assert lat == 39.7817
        assert lon == -89.6501
        return {
            "current": {
                "temperature_2m": 70.0,
                "apparent_temperature": 70.0,
                "precipitation": 0,
                "weather_code": 0,
            },
            "daily": [],
        }

    monkeypatch.setattr("arelis.tools.weather.geocode_place", _geo)
    monkeypatch.setattr("arelis.tools.weather.fetch_forecast", _fake_forecast)
    tool = WeatherTool(
        _FakeLocation(UserLocation(city="Springfield", region="Illinois"))
    )
    result = await tool.run()
    assert result.ok
    assert "Springfield" in result.output


@pytest.mark.asyncio
async def test_weather_geocodes_named_place_not_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _geo(name: str, **_kw: Any):
        assert "Metropolis" in name
        return (39.7817, -89.6501)

    async def _fake_forecast(lat: float, lon: float, *, days: int = 3, **_kw: Any):
        assert lat == 39.7817
        assert lon == -89.6501
        assert days == 3
        return {
            "current": {
                "temperature_2m": 81.0,
                "apparent_temperature": 83.0,
                "precipitation": 0,
                "weather_code": 61,
            },
            "daily": [
                {
                    "date": "2026-08-19",
                    "weather_code": 61,
                    "temperature_2m_max": 81.0,
                    "temperature_2m_min": 65.0,
                    "precipitation_probability_max": 31,
                }
            ],
        }

    monkeypatch.setattr("arelis.tools.weather.geocode_place", _geo)
    monkeypatch.setattr("arelis.tools.weather.fetch_forecast", _fake_forecast)
    tool = WeatherTool(
        _FakeLocation(
            UserLocation(
                city="Springfield",
                region="Illinois",
                latitude=37.7749,
                longitude=-122.4194,
            )
        )
    )
    result = await tool.run(place="Metropolis, Illinois", days=3)
    assert result.ok
    assert "Metropolis" in result.output
    assert "39.7817" in result.output
    assert "37.7749" not in result.output


def test_draft_weather_args_names_another_city() -> None:
    from arelis.tools.weather import draft_weather_args, fill_weather_args

    outside = draft_weather_args("What's the weather like outside?")
    assert outside == {"days": 3}
    assert "place" not in outside

    metropolis = draft_weather_args(
        "web search Metropolis Illinois weather tomorrow"
    )
    assert metropolis["days"] == 3
    assert "metropolis" in str(metropolis.get("place") or "").lower()

    dated = draft_weather_args("August 19 2026 in Springfield")
    assert "springfield" in str(dated.get("place") or "").lower()

    filled = fill_weather_args({"days": 1}, "weather tomorrow")
    assert filled["days"] == 3
    filled_coords = fill_weather_args(
        {"days": 2, "latitude": 37.77, "longitude": -122.4},
        "What's the weather outside?",
    )
    assert "latitude" not in filled_coords
    assert "longitude" not in filled_coords
    assert filled_coords["days"] == 2


def test_extract_weather_places_splits_two_cities() -> None:
    from arelis.tools.weather import extract_weather_place, extract_weather_places

    two = extract_weather_places(
        "weather in Springfield, Illinois and Metropolis, Illinois"
    )
    joined = " ".join(two).lower()
    assert any("springfield" in p.lower() for p in two)
    assert any("metropolis" in p.lower() for p in two)
    assert "and" not in joined
    assert extract_weather_place("What's the weather like outside?") == ""
    home_and = extract_weather_places("weather here and in Metropolis")
    assert any("metropolis" in p.lower() for p in home_and)
    inbox = extract_weather_places(
        "What's the weather today, and anything new in my inbox?"
    )
    assert all(not p or "inbox" not in p.lower() for p in inbox)
    assert extract_weather_place(
        "What's the weather today, and anything new in my inbox?"
    ) == ""


def test_the_weather_skill_card_geocodes_a_named_place() -> None:
    from arelis.core.skills import SKILL_CARDS

    body = SKILL_CARDS["weather"].body.lower()
    assert "place" in body
    assert "geocod" in body
    assert "latitude" not in body
    assert "cannot" not in body or "another city" not in body


def test_weather_is_registered(tmp_path) -> None:
    from arelis.tools import build_tool_registry
    from arelis.workspace import WorkspaceRoots

    workspace = WorkspaceRoots.from_config({"workspace": {"roots": [str(tmp_path)]}})
    registry = build_tool_registry(
        {"tools": {}, "agent": {}, "location": {"enabled": True}},
        workspace,
    )
    assert "weather" in registry.names()


def test_policy_routes_weather_through_weather_tool() -> None:
    text = TOOL_POLICY.lower()
    assert "call the weather tool" in text
    assert "would you like me to proceed" in text
    assert "url: value" in text or "url: line" in text
