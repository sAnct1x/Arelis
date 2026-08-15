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
async def test_weather_tool_needs_coords() -> None:
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
    forbidden, and requested by the failure message. Now the profile is the only
    source, and the cross-tool-args gate can trust the declared keys.
    """
    declared = set(WeatherTool.parameters_schema["properties"])
    assert declared == {"days"}
    assert "latitude" not in WeatherTool.description.lower()
    assert "longitude" not in WeatherTool.description.lower()


@pytest.mark.asyncio
async def test_missing_coords_points_at_user_location_not_at_arguments() -> None:
    """The old message asked for arguments the tool does not accept."""
    tool = WeatherTool(_FakeLocation(UserLocation(city="Nowhere")))
    result = await tool.run()
    assert not result.ok
    assert "user_location" in result.output
    assert "do not pass coordinates" in result.output.lower()


def test_the_weather_skill_card_does_not_promise_a_named_place() -> None:
    from arelis.core.skills import SKILL_CARDS

    body = SKILL_CARDS["weather"].body.lower()
    assert "geocod" not in body
    assert "latitude" not in body


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
