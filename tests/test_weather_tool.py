"""One forecast sentence, and a place the code picks when the model omits it.

Network stays out. Geocode and forecast are callables the test passes in.
Windows, the saved city, and the IP lookup are the same kind of stand-in.
"""

from __future__ import annotations

import asyncio
import io
import json
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
async def test_each_temperature_carries_degrees_f() -> None:
    """A bare F is a farad. Temp, high, and low each carry the degree mark."""
    stand = _Standins([_IL])
    result = await stand.tool().run(place="Springfield, Illinois")

    temp, high, low = _temperature_slots(result.output)
    for slot in (temp, high, low):
        assert slot.endswith("\u00b0F"), slot
        assert slot[: -len("\u00b0F")].isdigit(), slot


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

    result = await stand.tool(ip_enabled=True).run()

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

    result = await stand.tool(ip_enabled=True).run(place="")

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

    result = await stand.tool(ip_enabled=True).run(place="   ")

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
    assert stand.ip == 0
    assert stand.geo == []
    assert stand.forecast == []


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


@pytest.mark.asyncio
@pytest.mark.parametrize("place", ["Paris France", "Paris, France", "Paris, FR"])
async def test_paris_with_the_country_is_france(place: str) -> None:
    calls: list[str] = []
    tool = WeatherTool(
        windows_location=lambda: None,
        home_city=lambda: "",
        ip_location=lambda: None,
        geocode=_paris_geocode(calls),
        forecast=_Standins().forecast_fn,
    )
    result = await tool.run(place=place)

    assert result.ok
    assert "?" not in result.output
    assert "Paris, France" in result.output
    assert "Ile-de-France" not in result.output
    assert "Texas" not in result.output
    assert calls == ["Paris"]


@pytest.mark.asyncio
@pytest.mark.parametrize("place", ["Paris today", "Paris tomorrow"])
async def test_paris_today_keeps_the_shorter_city(place: str) -> None:
    """A trailing word that is not a region does not throw away the city."""
    calls: list[str] = []
    tool = WeatherTool(
        windows_location=lambda: None,
        home_city=lambda: "",
        ip_location=lambda: None,
        geocode=_paris_geocode(calls),
        forecast=_Standins().forecast_fn,
    )
    result = await tool.run(place=place)

    assert result.ok
    assert "Paris, France" in result.output
    assert "Texas" not in result.output
    assert calls == ["Paris", place]


@pytest.mark.asyncio
async def test_a_bare_paris_is_france() -> None:
    calls: list[str] = []
    tool = WeatherTool(
        windows_location=lambda: None,
        home_city=lambda: "",
        ip_location=lambda: None,
        geocode=_paris_geocode(calls),
        forecast=_Standins().forecast_fn,
    )
    result = await tool.run(place="Paris")

    assert result.ok
    assert "Paris, France" in result.output
    assert calls == ["Paris"]


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
async def test_a_503_says_the_service_could_not_be_reached() -> None:
    stand = _Standins([_PARIS_FR])
    stand.geo_error = _http_error(503, "place not found")
    result = await stand.tool().run(place="Paris")

    assert result.ok is False
    assert result.output == "I couldn't reach the weather service."


@pytest.mark.asyncio
async def test_empty_geocode_results_stay_not_found() -> None:
    stand = _Standins([])
    result = await stand.tool().run(place="Paris")

    assert result.ok is False
    assert result.output == "I couldn't get the forecast for Paris."


class _LookupClient:
    def __init__(self, status: int) -> None:
        self.status = status

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(self.status, json={"results": []}, request=request)

    async def aclose(self) -> None:
        return None


def test_default_log_level_hides_the_place() -> None:
    """A typed place stays out of the log unless debug logging is on."""
    log = logging.getLogger("arelis.weather.lookup")
    previous = log.level
    log.setLevel(logging.NOTSET)
    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    root_captured = io.StringIO()
    root_handler = logging.StreamHandler(root_captured)
    root_handler.setLevel(logging.INFO)
    log.addHandler(handler)
    root.addHandler(root_handler)
    try:
        asyncio.run(search_geocode("Lookupville", client=_LookupClient(200)))
    finally:
        log.removeHandler(handler)
        root.removeHandler(root_handler)
        log.setLevel(previous)
    assert "Lookupville" not in captured.getvalue()
    assert "Lookupville" not in root_captured.getvalue()


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


def test_debug_log_records_status_and_hides_contacts() -> None:
    log = logging.getLogger("arelis.weather.lookup")
    previous = log.level
    log.setLevel(logging.DEBUG)
    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    handler.setLevel(logging.DEBUG)
    log.addHandler(handler)
    try:
        asyncio.run(
            search_geocode(
                "Lookupville",
                client=_CityLookupClient(200, [{"name": "Lookupville"}]),
            )
        )
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(search_geocode("you@example.com", client=_LookupClient(503)))
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(search_geocode("555-555-0123", client=_LookupClient(429)))
    finally:
        log.removeHandler(handler)
        log.setLevel(previous)
    text = captured.getvalue()
    assert "lookup place=Lookupville status=200" in text
    assert "status=503" in text
    assert "status=429" in text
    assert "you@example.com" not in text
    assert "555-555-0123" not in text
    for line in text.splitlines():
        if "status=503" in line or "status=429" in line:
            assert "place=" not in line


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


def test_timeout_logs_no_typed_place() -> None:
    """A timeout logs the error class and none of the typed address."""
    address = "123 Main Street, Springfield, Illinois 62701"
    text = _captured_lookup(address, _TimeoutClient())
    assert "status=timeout" in text
    _assert_no_typed_place(text, "123 Main Street", "62701", address)


def test_http_500_logs_no_typed_place() -> None:
    """An HTTP error logs the status and none of the typed address."""
    address = "123 Main Street, Springfield, Illinois 62701"
    text = _captured_lookup(address, _LookupClient(500))
    assert "status=500" in text
    _assert_no_typed_place(text, "123 Main Street", "62701", address)


def test_no_results_logs_no_typed_place() -> None:
    """An empty gazetteer result is not a resolved city."""
    address = "123 Main Street, Springfield, Illinois 62701"
    text = _captured_lookup(address, _LookupClient(200))
    assert "status=200" in text
    _assert_no_typed_place(text, "123 Main Street", "62701", address)


def test_unresolved_address_without_commas_logs_no_typed_place() -> None:
    """No comma means the whole typed line is not a city to log."""
    address = "123 Main Street Springfield Illinois 62701"
    text = _captured_lookup(address, _LookupClient(200))
    assert "status=200" in text
    _assert_no_typed_place(text, "123 Main Street", "62701", address)


def test_unresolved_coordinates_log_no_typed_place() -> None:
    """Coordinates are typed input. An unresolved lookup does not log them."""
    typed = "40.7128,-74.0060"
    text = _captured_lookup(typed, _LookupClient(200))
    assert "status=200" in text
    _assert_no_typed_place(text, "40.7128", "74.0060", "7128", "0060", typed)


def test_http_500_for_elm_st_logs_no_typed_place() -> None:
    """A short street on an HTTP error is still typed input."""
    typed = "1 Elm St"
    text = _captured_lookup(typed, _LookupClient(500))
    assert "status=500" in text
    _assert_no_typed_place(text, typed, "Elm")


class _ConnectionClient:
    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        raise httpx.ConnectError("down")

    async def aclose(self) -> None:
        return None


def test_connection_error_logs_no_typed_place() -> None:
    """A connection error logs the error class and none of the typed place."""
    typed = "1 Elm St"
    text = _captured_lookup(typed, _ConnectionClient())
    assert "status=connection" in text
    _assert_no_typed_place(text, typed, "Elm")


class _NonJsonClient:
    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(200, content=b"not-json", request=request)

    async def aclose(self) -> None:
        return None


def test_non_json_reply_logs_no_typed_place() -> None:
    """A body that is not JSON logs the status and none of the typed place."""
    typed = "1 Elm St"
    log = logging.getLogger("arelis.weather.lookup")
    previous = log.level
    log.setLevel(logging.DEBUG)
    captured = io.StringIO()
    handler = logging.StreamHandler(captured)
    handler.setLevel(logging.DEBUG)
    log.addHandler(handler)
    try:
        with pytest.raises(json.JSONDecodeError):
            asyncio.run(search_geocode(typed, client=_NonJsonClient()))
    finally:
        log.removeHandler(handler)
        log.setLevel(previous)
    text = captured.getvalue()
    assert "status=200" in text
    _assert_no_typed_place(text, typed, "Elm")


def test_coordinates_with_a_space_log_no_typed_place() -> None:
    """A space after the comma is still a typed coordinate, not a city."""
    typed = "40.7128, -74.0060"
    text = _captured_lookup(typed, _LookupClient(200))
    assert "status=200" in text
    _assert_no_typed_place(text, "40.7128", "74.0060", "7128", "0060", typed)


def test_dashed_phone_is_redacted() -> None:
    text = _lookup_place("555-123-4567 and 555-555-0123")
    assert "555-123-4567" not in text
    assert "555-555-0123" not in text
    assert text.count("[redacted]") == 2


def test_bare_ten_digit_phone_is_redacted() -> None:
    """Ten digits with no separator are still a phone.

    Requiring a dash, dot, or space between the groups would leave
    5551234567 in the clear.
    """
    text = _lookup_place("5551234567")
    assert "5551234567" not in text
    assert text == "[redacted]"


def test_parenthesized_phone_is_redacted() -> None:
    text = _lookup_place("call (555) 123-4567")
    assert "(555) 123-4567" not in text
    assert "123-4567" not in text
    assert "[redacted]" in text


def test_dotted_phone_is_redacted() -> None:
    text = _lookup_place("call 555.123.4567")
    assert "555.123.4567" not in text
    assert "[redacted]" in text


def test_international_phone_is_redacted() -> None:
    text = _lookup_place("call +1 555 123 4567")
    assert "+1 555 123 4567" not in text
    assert "123 4567" not in text
    assert "[redacted]" in text


def test_email_and_dashed_phone_are_redacted() -> None:
    text = _lookup_place("ping you@example.com about 555-123-4567")
    assert "you@example.com" not in text
    assert "555-123-4567" not in text
    assert text.count("[redacted]") == 2


@pytest.mark.asyncio
async def test_a_bare_london_is_the_dominant_city() -> None:
    stand = _Standins([_LONDON_CA, _LONDON_GB])
    result = await stand.tool().run(place="London")

    assert stand.forecast == [(51.5085, -0.1257)]
    assert "London, United Kingdom" in result.output
    assert "?" not in result.output


@pytest.mark.asyncio
async def test_close_populations_still_ask() -> None:
    close_mo = dict(_MO, population=170_000)
    close_il = dict(_IL, population=150_000)
    stand = _Standins([close_mo, close_il])
    result = await stand.tool().run(place="Springfield")

    assert stand.forecast == []
    assert result.output == (
        "Did you mean Springfield, Missouri or Springfield, Illinois?"
    )


@pytest.mark.asyncio
async def test_windows_coordinates_without_a_city_still_forecast() -> None:
    stand = _Standins([_IL])
    stand.windows_value = SimpleNamespace(
        city="", region="", latitude=39.7817, longitude=-89.6501
    )
    result = await stand.tool().run()

    assert stand.geo == []
    assert stand.ip == 0
    assert stand.forecast == [(39.7817, -89.6501)]
    assert result.output.startswith("Your location:")


@pytest.mark.asyncio
async def test_ip_lookup_off_by_default_is_not_called(tmp_path, monkeypatch) -> None:
    from arelis.location import build_location
    from arelis.location.providers import IPGeolocationProvider

    calls: list[str] = []

    async def resolve(self):
        calls.append("ip")
        raise AssertionError("ip provider was called")

    monkeypatch.setattr(IPGeolocationProvider, "resolve", resolve)
    resolver = build_location(
        {
            "location": {
                "profile_path": str(tmp_path / "missing.yaml"),
                "use_system": False,
                "network": {"enabled": False},
            }
        }
    )
    assert resolver.network_enabled() is False
    stand = _Standins([])
    tool = WeatherTool(
        location=resolver,
        windows_location=lambda: None,
        geocode=stand.geocode,
        forecast=stand.forecast_fn,
    )
    result = await tool.run()

    assert calls == []
    assert result.ok
    assert result.output == _WHERE
    assert stand.forecast == []


def test_shipped_ip_lookup_defaults_off() -> None:
    from pathlib import Path

    import yaml

    data = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "arelis" / "config" / "default.yaml").read_text()
    )
    assert data["location"]["network"]["enabled"] is False


@pytest.mark.asyncio
async def test_enabled_ip_is_the_last_fallback(tmp_path, monkeypatch) -> None:
    from arelis.location import UserLocation, build_location
    from arelis.location.providers import IPGeolocationProvider

    calls: list[str] = []

    async def resolve(self):
        calls.append("ip")
        return UserLocation(city="Lyon", latitude=45.76, longitude=4.84)

    monkeypatch.setattr(IPGeolocationProvider, "resolve", resolve)
    resolver = build_location(
        {
            "location": {
                "profile_path": str(tmp_path / "missing.yaml"),
                "use_system": False,
                "network": {"enabled": True, "url": "https://ipapi.co/json/"},
            }
        }
    )
    stand = _Standins([])
    tool = WeatherTool(
        location=resolver,
        windows_location=lambda: None,
        geocode=stand.geocode,
        forecast=stand.forecast_fn,
    )
    result = await tool.run()

    assert calls == ["ip"]
    assert stand.geo == []
    assert stand.forecast == [(45.76, 4.84)]
    assert result.output.startswith("Lyon:")


@pytest.mark.asyncio
async def test_home_region_breaks_a_population_tie() -> None:
    """Close populations ask, unless the saved home region matches one of them."""
    close_mo = dict(_MO, population=170_000, country="United States")
    close_il = dict(_IL, population=150_000, country="United States")
    stand = _Standins([close_mo, close_il])
    stand.home_value = "Chicago, Illinois"
    result = await stand.tool().run(place="Springfield")

    assert stand.forecast == [(39.7817, -89.6501)]
    assert result.output.startswith("Springfield, Illinois:")
    assert "?" not in result.output


def test_place_label_uses_state_or_country() -> None:
    from arelis.tools.weather import place_label

    assert place_label(_PARIS_FR) == "Paris, France"
    assert place_label(_PARIS_TX) == "Paris, Texas"
    assert place_label(_LONDON_GB) == "London, United Kingdom"
    assert place_label(_IL) == "Springfield, Illinois"


def test_status_and_spoken_prompt_do_not_say_called_the_tool() -> None:
    from arelis.core.agent_loop import _tool_intent_label
    from arelis.talk_language import _SPOKEN_EN

    label = _tool_intent_label(
        [{"function": {"name": "weather", "arguments": {}}}]
    ).lower()
    assert "calling" not in label
    assert "called the" not in label
    assert "tool" not in label
    spoken = _SPOKEN_EN.lower()
    assert "call the tool" not in spoken
    assert "called the" not in spoken


def test_model_facing_weather_text_names_no_tool_or_api() -> None:
    blob = "\n".join(_facing()).lower()
    for banned in _FORBIDDEN:
        assert banned not in blob, banned
    assert "call weather" in blob
