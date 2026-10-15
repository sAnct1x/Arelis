"""One forecast sentence, and a place the code picks when the model omits it.

Network stays out. Geocode and forecast are callables the test passes in.
Windows, the saved city, and the IP lookup are the same kind of stand-in.
"""

from __future__ import annotations

import asyncio
import io
import logging
from types import SimpleNamespace

import httpx
import pytest

from arelis.briefing.weather import _lookup_place, search_geocode
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
        self.geo_error: BaseException | None = None

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
        if self.geo_error is not None:
            raise self.geo_error
        if self.boom_geo:
            raise RuntimeError("down")
        return list(self.rows)

    async def forecast_fn(self, lat: float, lon: float) -> dict:
        self.forecast.append((lat, lon))
        if self.boom_forecast:
            raise RuntimeError("down")
        return _reading()

    def tool(self, *, ip_enabled: bool | None = None) -> WeatherTool:
        return WeatherTool(
            windows_location=self.windows_fn,
            home_city=self.home_fn,
            ip_location=self.ip_fn,
            ip_enabled=ip_enabled,
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
        "Springfield, Illinois: 61\u00b0F and overcast, high 66\u00b0F, low 48\u00b0F."
    )
    assert "?" not in result.output
    assert "Did you mean" not in result.output
    assert "say which" not in result.output.lower()


def _temperature_slots(sentence: str) -> tuple[str, str, str]:
    """The current, high, and low slots in the forecast sentence."""
    head, tail = sentence.split(" and ", 1)
    temp = head.rsplit(" ", 1)[-1]
    high = tail.split(", high ", 1)[1].split(", low ", 1)[0]
    low = tail.split(", low ", 1)[1].removesuffix(".")
    return temp, high, low


@pytest.mark.asyncio
async def test_a_miss_is_the_plain_failure_line() -> None:
    stand = _Standins([])
    result = await stand.tool().run(place="Springfield, Illinois")

    assert not result.ok
    assert result.data.get("status") == "not_found"
    assert result.output == "I couldn't find that place."
    lowered = result.output.lower()
    for banned in _FORBIDDEN:
        assert banned not in lowered


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


_PARIS_FR = {
    "name": "Paris",
    "latitude": 48.8566,
    "longitude": 2.3522,
    "admin1": "Ile-de-France",
    "country": "France",
    "country_code": "FR",
    "population": 2138551,
}
_PARIS_TX = {
    "name": "Paris",
    "latitude": 33.6609,
    "longitude": -95.5555,
    "admin1": "Texas",
    "country": "United States",
    "country_code": "US",
    "population": 24782,
}
_LONDON_GB = {
    "name": "London",
    "latitude": 51.5085,
    "longitude": -0.1257,
    "admin1": "England",
    "country": "United Kingdom",
    "country_code": "GB",
    "population": 8961989,
}
_LONDON_CA = {
    "name": "London",
    "latitude": 42.9834,
    "longitude": -81.233,
    "admin1": "Ontario",
    "country": "Canada",
    "country_code": "CA",
    "population": 422324,
}


def _paris_geocode(calls: list[str]):
    async def geocode(query: str) -> list[dict]:
        calls.append(query)
        if query == "Paris":
            return [_PARIS_FR, _PARIS_TX]
        return []

    return geocode


def _http_error(status: int, message: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.invalid/search")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError(message, request=request, response=response)


@pytest.mark.asyncio
async def test_a_timeout_says_the_service_could_not_be_reached() -> None:
    stand = _Standins([_PARIS_FR])
    stand.geo_error = httpx.ReadTimeout(
        "place not found",
        request=httpx.Request("GET", "https://example.invalid/search"),
    )
    result = await stand.tool().run(place="Paris")

    assert result.ok is False
    assert result.output == "I couldn't reach the weather service."


@pytest.mark.asyncio
async def test_empty_geocode_results_stay_not_found() -> None:
    stand = _Standins([])
    result = await stand.tool().run(place="Paris")

    assert result.ok is False
    assert result.data.get("status") == "not_found"
    assert result.output == "I couldn't find that place."


class _LookupClient:
    def __init__(self, status: int) -> None:
        self.status = status

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(self.status, json={"results": []}, request=request)

    async def aclose(self) -> None:
        return None


def test_lookup_log_does_not_propagate_to_the_app_log() -> None:
    """A debug lookup stays on its own logger. The root log never sees it."""
    log = logging.getLogger("arelis.weather.lookup")
    previous = log.level
    root = logging.getLogger()
    previous_root = root.level
    log.setLevel(logging.DEBUG)
    root.setLevel(logging.DEBUG)
    own = io.StringIO()
    own_handler = logging.StreamHandler(own)
    own_handler.setLevel(logging.DEBUG)
    root_captured = io.StringIO()
    root_handler = logging.StreamHandler(root_captured)
    root_handler.setLevel(logging.DEBUG)
    log.addHandler(own_handler)
    root.addHandler(root_handler)
    try:
        asyncio.run(
            search_geocode(
                "Lookupville",
                client=_CityLookupClient(200, [{"name": "Lookupville"}]),
            )
        )
    finally:
        log.removeHandler(own_handler)
        root.removeHandler(root_handler)
        log.setLevel(previous)
        root.setLevel(previous_root)
    assert "lookup place=Lookupville status=200" in own.getvalue()
    assert "Lookupville" not in root_captured.getvalue()
    assert log.propagate is False


class _CityLookupClient:
    def __init__(self, status: int, results: list[dict]) -> None:
        self.status = status
        self.results = results

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(
            self.status, json={"results": self.results}, request=request
        )

    async def aclose(self) -> None:
        return None


def test_debug_log_records_the_city_not_the_street() -> None:
    """A street address logs the resolved city and the status only."""
    log = logging.getLogger("arelis.weather.lookup")
    previous = log.level
    log.setLevel(logging.DEBUG)
    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    handler.setLevel(logging.DEBUG)
    log.addHandler(handler)
    address = "123 Main Street, Springfield, Illinois 62701"
    try:
        asyncio.run(
            search_geocode(
                address,
                client=_CityLookupClient(
                    200,
                    [
                        {
                            "name": "Springfield",
                            "latitude": 39.7817,
                            "longitude": -89.6501,
                            "admin1": "Illinois",
                            "country": "United States",
                            "country_code": "US",
                            "population": 114394,
                        }
                    ],
                ),
            )
        )
    finally:
        log.removeHandler(handler)
        log.setLevel(previous)
    text = captured.getvalue()
    assert "lookup place=Springfield status=200" in text
    assert "123 Main Street" not in text
    assert address not in text
    assert "Illinois" not in text
    assert "62701" not in text
    assert "39.7817" not in text
    assert "-89.6501" not in text


class _TimeoutClient:
    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    async def aclose(self) -> None:
        return None


def _captured_lookup(query: str, client: object) -> str:
    log = logging.getLogger("arelis.weather.lookup")
    previous = log.level
    log.setLevel(logging.DEBUG)
    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    handler.setLevel(logging.DEBUG)
    log.addHandler(handler)
    try:
        try:
            asyncio.run(search_geocode(query, client=client))
        except httpx.HTTPError:
            pass
    finally:
        log.removeHandler(handler)
        log.setLevel(previous)
    return captured.getvalue()


def _assert_no_typed_place(text: str, *needles: str) -> None:
    assert "status=" in text
    for line in text.splitlines():
        if "status=" in line:
            assert "place=" not in line
    for needle in needles:
        assert needle not in text


class _ConnectionClient:
    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        raise httpx.ConnectError("down")

    async def aclose(self) -> None:
        return None


class _NonJsonClient:
    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(200, content=b"not-json", request=request)

    async def aclose(self) -> None:
        return None


def test_dashed_phone_is_redacted() -> None:
    text = _lookup_place("555-123-4567 and 555-555-0123")
    assert "555-123-4567" not in text
    assert "555-555-0123" not in text
    assert text.count("[redacted]") == 2


