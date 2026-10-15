"""One forecast sentence, and a place the code picks when the model omits it.

Network stays out. Geocode and forecast are callables the test passes in.
Windows, the saved city, and the IP lookup are the same kind of stand-in.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from arelis.core.claims import weather_force_notice
from arelis.core.compact_prompt import COMPACT_TOOL_POLICY
from arelis.core.intent_catalog import WEATHER
from arelis.core.lessons import _SEED
from arelis.core.plan_nudge import _PLAN_WEATHER
from arelis.core.skills import SKILL_CARDS
from arelis.core.turn_goal import _LINES
from arelis.tools.scrape import ScrapeTool
from arelis.tools.weather import WeatherTool
from arelis.tools.web import WebFetchTool

_IL = {
    "name": "Springfield",
    "latitude": 39.7817,
    "longitude": -89.6501,
    "admin1": "Illinois",
    "country_code": "US",
}
_MO = {
    "name": "Springfield",
    "latitude": 37.2089,
    "longitude": -93.2923,
    "admin1": "Missouri",
    "country_code": "US",
}
_WHERE = "I couldn't tell where you are. Which city should I check?"
_FORBIDDEN = (
    "weather tool",
    "open-meteo",
    "accuweather",
    "weather.com",
    "geocode",
    "geocoding",
)


def _reading() -> dict:
    return {
        "current": {"temperature_2m": 61.2, "weather_code": 3},
        "daily": [{"temperature_2m_max": 66.4, "temperature_2m_min": 48.2}],
    }


class _Standins:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = list(rows or [])
        self.windows = 0
        self.home = 0
        self.ip = 0
        self.geo: list[str] = []
        self.forecast: list[tuple[float, float]] = []
        self.windows_value: object = None
        self.home_value = ""
        self.ip_value: object = None
        self.boom_geo = False
        self.boom_forecast = False

    def windows_fn(self) -> object:
        self.windows += 1
        return self.windows_value

    def home_fn(self) -> str:
        self.home += 1
        return self.home_value

    def ip_fn(self) -> object:
        self.ip += 1
        return self.ip_value

    async def geocode(self, query: str) -> list[dict]:
        self.geo.append(query)
        if self.boom_geo:
            raise RuntimeError("down")
        return list(self.rows)

    async def forecast_fn(self, lat: float, lon: float) -> dict:
        self.forecast.append((lat, lon))
        if self.boom_forecast:
            raise RuntimeError("down")
        return _reading()

    def tool(self) -> WeatherTool:
        return WeatherTool(
            windows_location=self.windows_fn,
            home_city=self.home_fn,
            ip_location=self.ip_fn,
            geocode=self.geocode,
            forecast=self.forecast_fn,
        )


def _facing() -> list[str]:
    lesson = next(item["text"] for item in _SEED if item["id"] == "weather-not-scrape")
    weather_line = next(
        line for line in COMPACT_TOOL_POLICY.splitlines() if line.startswith("weather:")
    )
    return [
        WeatherTool.description,
        str(WeatherTool.parameters_schema["properties"]["place"]["description"]),
        weather_line,
        SKILL_CARDS["weather"].body,
        lesson,
        _PLAN_WEATHER.message,
        WEATHER.nudge,
        weather_force_notice(),
        _LINES["weather"],
        WebFetchTool.description,
        ScrapeTool.description,
    ]


@pytest.mark.asyncio
async def test_springfield_illinois_beats_the_first_hit() -> None:
    """The state in the place string wins, even when another Springfield is first."""
    stand = _Standins([_MO, _IL])
    result = await stand.tool().run(place="Springfield, Illinois")

    assert stand.geo == ["Springfield"]
    assert stand.forecast == [(39.7817, -89.6501)]
    assert stand.windows == 0
    assert stand.home == 0
    assert stand.ip == 0
    assert result.ok
    assert result.output == (
        "Springfield, Illinois: 61F and overcast, high 66, low 48."
    )
    assert "?" not in result.output
    assert "Did you mean" not in result.output
    assert "say which" not in result.output.lower()


@pytest.mark.asyncio
async def test_a_state_abbreviation_is_the_same_filter() -> None:
    stand = _Standins([_MO, _IL])
    result = await stand.tool().run(place="Springfield, IL")

    assert stand.forecast == [(39.7817, -89.6501)]
    assert result.output.startswith("Springfield, Illinois:")
    assert "?" not in result.output


@pytest.mark.asyncio
async def test_a_bare_name_asks_once_and_does_not_forecast() -> None:
    stand = _Standins([_MO, _IL])
    result = await stand.tool().run(place="Springfield")

    assert stand.geo == ["Springfield"]
    assert stand.forecast == []
    assert result.ok
    assert result.data["ambiguous"] is True
    assert result.output == (
        "Did you mean Springfield, Missouri or Springfield, Illinois?"
    )


@pytest.mark.asyncio
async def test_a_named_state_with_no_hit_does_not_ask() -> None:
    stand = _Standins([_MO])
    result = await stand.tool().run(place="Springfield, Illinois")

    assert not result.ok
    assert result.output == "I couldn't get the forecast for Springfield, Illinois."
    assert "?" not in result.output
    assert stand.forecast == []


@pytest.mark.asyncio
async def test_a_miss_is_the_plain_failure_line() -> None:
    stand = _Standins([])
    result = await stand.tool().run(place="Springfield, Illinois")

    assert not result.ok
    assert result.output == "I couldn't get the forecast for Springfield, Illinois."
    lowered = result.output.lower()
    for banned in _FORBIDDEN:
        assert banned not in lowered


@pytest.mark.asyncio
async def test_a_lookup_error_is_the_same_failure_line() -> None:
    stand = _Standins([_IL])
    stand.boom_geo = True
    result = await stand.tool().run(place="Springfield, Illinois")

    assert result.output == "I couldn't get the forecast for Springfield, Illinois."
    assert stand.forecast == []


@pytest.mark.asyncio
async def test_no_place_uses_windows_when_it_is_present() -> None:
    stand = _Standins([_MO])
    stand.windows_value = SimpleNamespace(
        city="Springfield",
        region="Illinois",
        latitude=39.7817,
        longitude=-89.6501,
    )
    stand.home_value = "Lyon"
    stand.ip_value = SimpleNamespace(city="Paris", region="", latitude=1.0, longitude=2.0)

    result = await stand.tool().run()

    assert stand.windows == 1
    assert stand.home == 0
    assert stand.ip == 0
    assert stand.geo == []
    assert stand.forecast == [(39.7817, -89.6501)]
    assert result.output.startswith("Springfield, Illinois:")


@pytest.mark.asyncio
async def test_no_place_falls_back_to_the_home_city() -> None:
    stand = _Standins([_MO, _IL])
    stand.home_value = "Springfield, Illinois"
    stand.ip_value = SimpleNamespace(city="Lyon", region="", latitude=45.0, longitude=4.0)

    result = await stand.tool().run(place="")

    assert stand.windows == 1
    assert stand.home == 1
    assert stand.ip == 0
    assert stand.geo == ["Springfield"]
    assert stand.forecast == [(39.7817, -89.6501)]
    assert result.output.startswith("Springfield, Illinois:")


@pytest.mark.asyncio
async def test_no_place_falls_back_to_ip_after_home() -> None:
    stand = _Standins([_MO, _IL])
    stand.ip_value = SimpleNamespace(
        city="Lyon",
        region="",
        latitude=45.76,
        longitude=4.84,
    )

    result = await stand.tool().run(place="   ")

    assert stand.windows == 1
    assert stand.home == 1
    assert stand.ip == 1
    assert stand.geo == []
    assert stand.forecast == [(45.76, 4.84)]
    assert result.output.startswith("Lyon:")


@pytest.mark.asyncio
async def test_a_named_place_overrides_every_fallback() -> None:
    stand = _Standins([_MO, _IL])
    stand.windows_value = SimpleNamespace(
        city="Lyon", region="", latitude=45.0, longitude=4.0
    )
    stand.home_value = "Lyon"
    stand.ip_value = SimpleNamespace(city="Paris", region="", latitude=1.0, longitude=2.0)

    result = await stand.tool().run(place="Springfield, Illinois")

    assert stand.windows == 0
    assert stand.home == 0
    assert stand.ip == 0
    assert stand.forecast == [(39.7817, -89.6501)]
    assert result.output.startswith("Springfield, Illinois:")


@pytest.mark.asyncio
async def test_no_place_and_no_fallback_asks_which_city() -> None:
    stand = _Standins([_IL])
    result = await stand.tool().run()

    assert result.ok
    assert result.output == _WHERE
    assert stand.windows == 1
    assert stand.home == 1
    assert stand.ip == 1
    assert stand.geo == []
    assert stand.forecast == []


def test_model_facing_weather_text_names_no_tool_or_api() -> None:
    blob = "\n".join(_facing()).lower()
    for banned in _FORBIDDEN:
        assert banned not in blob, banned
    assert "call weather" in blob
