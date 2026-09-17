"""The other half of "anywhere I want, whenever I want": there was no *when*.

`weather` took one time argument — `days`, meaning "how many daily rows from
today, 1 to 7". That shape cannot answer either of the two most ordinary
weather questions a person asks:

  "will it rain at three?"   Each daily row carries
                             precipitation_probability_max, the maximum over
                             the whole day. A 60% day says nothing about
                             three o'clock, so the honest answer was a guess
                             dressed as data.

  "what was it yesterday?"   Forecast rows start today. There was no
                             parameter, no fallback, and nothing in the
                             failure text to suggest it — so the model either
                             refused or invented it.

Both are one Open-Meteo query parameter away (`hourly=`, `past_days=`), which
is what makes this the same pattern as the rest of the audit: the capability
was one line from existing and the tool advertised neither.

`days` was also capped at 7 while the API serves 16, so "in two weeks" was
unreachable for no reason.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.briefing.weather import (
    MAX_FORECAST_DAYS,
    _first_upcoming_hour,
    fetch_forecast,
)
from arelis.tools.weather import WeatherTool


class _Capture:
    """Records the URL so the query parameters are visible to the test."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.urls: list[str] = []

    async def get(self, url: str, params: Any = None) -> Any:
        self.urls.append(url)
        payload = self._payload

        class _R:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return payload

        return _R()


def _payload(*, hours: int = 0, start_hour: int = 12) -> dict[str, Any]:
    stamps = [f"2026-09-17T{h:02d}:00" for h in range(24)]
    return {
        "current": {"temperature_2m": 70.0, "time": f"2026-09-17T{start_hour:02d}:00"},
        "daily": {
            "time": ["2026-09-17"],
            "weather_code": [0],
            "temperature_2m_max": [78.0],
            "temperature_2m_min": [60.0],
            "precipitation_probability_max": [60],
        },
        "hourly": {
            "time": stamps,
            "temperature_2m": [60.0 + h for h in range(24)],
            "precipitation_probability": [h * 4 for h in range(24)],
            "weather_code": [0] * 24,
        }
        if hours
        else {},
    }


@pytest.mark.asyncio
async def test_hourly_is_only_requested_when_asked_for() -> None:
    """It roughly doubles the response; a plain "what's the weather" pays nothing."""
    client = _Capture(_payload())

    await fetch_forecast(40.0, -80.0, days=3, client=client)

    assert "hourly=" not in client.urls[0]


@pytest.mark.asyncio
async def test_hourly_starts_from_now_not_from_midnight() -> None:
    """ "The next 6 hours" must mean that, not "6 hours starting at 00:00"."""
    client = _Capture(_payload(hours=6, start_hour=12))

    data = await fetch_forecast(40.0, -80.0, days=1, hours=6, client=client)

    assert "hourly=" in client.urls[0]
    times = [row["time"] for row in data["hourly"]]
    assert times[0] == "2026-09-17T12:00"
    assert len(times) == 6


@pytest.mark.asyncio
async def test_the_hour_cursor_survives_an_unparseable_clock() -> None:
    """Degrades to "start at the beginning" rather than raising mid-turn."""
    stamps = ["2026-09-17T00:00", "2026-09-17T01:00"]
    assert _first_upcoming_hour(stamps, "") == 0
    assert _first_upcoming_hour(stamps, None) == 0
    assert _first_upcoming_hour(stamps, "2026-09-17T01:00") == 1
    # A marker past the end of the series must not return an index into nothing.
    assert _first_upcoming_hour(stamps, "2099-01-01T00:00") == 0


@pytest.mark.asyncio
async def test_yesterday_is_reachable() -> None:
    client = _Capture(_payload())

    await fetch_forecast(40.0, -80.0, days=1, past_days=1, client=client)

    assert "past_days=1" in client.urls[0]


@pytest.mark.asyncio
async def test_past_days_is_absent_by_default() -> None:
    client = _Capture(_payload())

    await fetch_forecast(40.0, -80.0, days=3, client=client)

    assert "past_days" not in client.urls[0]


@pytest.mark.asyncio
async def test_two_weeks_out_is_no_longer_capped_at_a_week() -> None:
    client = _Capture(_payload())

    await fetch_forecast(40.0, -80.0, days=14, client=client)

    assert "forecast_days=14" in client.urls[0]
    assert MAX_FORECAST_DAYS == 16


@pytest.mark.asyncio
async def test_the_caps_hold() -> None:
    client = _Capture(_payload(hours=1))

    await fetch_forecast(40.0, -80.0, days=999, hours=999, past_days=999, client=client)

    assert "forecast_days=16" in client.urls[0]
    assert "past_days=7" in client.urls[0]


# --------------------------------------------------------------------------
# Through the tool
# --------------------------------------------------------------------------


class _Snapshot:
    latitude = 40.0
    longitude = -80.0

    def has_coordinates(self) -> bool:
        return True

    def place(self) -> str:
        return "Springfield, Illinois"


class _Location:
    def snapshot(self) -> _Snapshot:
        return _Snapshot()


def _patch_tool(monkeypatch: pytest.MonkeyPatch, seen: dict[str, Any]) -> None:
    async def _forecast(lat: float, lon: float, **kw: Any) -> dict[str, Any]:
        seen.update(kw)
        return {
            "current": {
                "temperature_2m": 70.0,
                "apparent_temperature": 69.0,
                "precipitation": 0.0,
                "weather_code": 0,
            },
            "daily": [
                {
                    "date": "2026-09-17",
                    "weather_code": 0,
                    "temperature_2m_max": 78.0,
                    "temperature_2m_min": 60.0,
                    "precipitation_probability_max": 60,
                }
            ],
            "hourly": [
                {
                    "time": "2026-09-17T15:00",
                    "temperature_2m": 74.0,
                    "precipitation_probability": 80,
                    "weather_code": 61,
                }
            ]
            if kw.get("hours")
            else [],
        }

    monkeypatch.setattr("arelis.tools.weather.fetch_forecast", _forecast)


@pytest.mark.asyncio
async def test_the_tool_reports_the_hour_and_its_own_chance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 60% day and an 80% 3pm are different answers; the hour has to win."""
    seen: dict[str, Any] = {}
    _patch_tool(monkeypatch, seen)

    result = await WeatherTool(_Location()).run(place="", hours=6)

    assert seen["hours"] == 6
    assert "15:00" in result.output
    assert "80%" in result.output
    assert result.data["hourly"], "hourly never reached the caller"


@pytest.mark.asyncio
async def test_a_worded_hour_count_does_not_fail_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 9B writes hours="this afternoon". That must not raise."""
    seen: dict[str, Any] = {}
    _patch_tool(monkeypatch, seen)

    result = await WeatherTool(_Location()).run(place="", hours="this afternoon")

    assert result.ok, result.output
    assert seen["hours"] == 0


@pytest.mark.asyncio
async def test_past_days_reaches_the_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    _patch_tool(monkeypatch, seen)

    await WeatherTool(_Location()).run(place="", past_days=1)

    assert seen["past_days"] == 1


@pytest.mark.asyncio
async def test_a_plain_ask_requests_no_extras(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}
    _patch_tool(monkeypatch, seen)

    await WeatherTool(_Location()).run(place="")

    assert seen["hours"] == 0
    assert seen["past_days"] == 0


@pytest.mark.parametrize(
    "ask,expected",
    [
        ("will it rain at 3pm", 12),
        ("what's it doing at 3:30pm", 12),
        ("is it going to rain this afternoon", 12),
        ("will it be cold tonight", 12),
        ("rain later today?", 12),
        ("weather in the next few hours", 12),
        ("will it rain in 2 hours", 12),
        ("what's it like tomorrow morning", 36),
        # Plain daily asks must not pay for hourly.
        ("what's the weather", 0),
        ("weather tomorrow", 0),
        ("forecast for the week", 0),
        ("will it rain on saturday", 0),
    ],
)
def test_a_time_of_day_ask_requests_hours(ask: str, expected: int) -> None:
    """Adding the parameter was only half the fix: the injected call is built
    by draft_weather_args, not by the model, so the guard path needed to know."""
    from arelis.tools.weather import weather_wants_hourly

    assert weather_wants_hourly(ask) == expected


@pytest.mark.parametrize(
    "ask,expected",
    [
        ("what was the weather yesterday", 1),
        ("how cold was it last night", 1),
        ("did it rain overnight", 1),
        ("was it raining this morning", 1),
        ("what's the weather", 0),
        ("will it rain tomorrow", 0),
    ],
)
def test_a_backward_looking_ask_requests_past_days(ask: str, expected: int) -> None:
    from arelis.tools.weather import weather_wants_past

    assert weather_wants_past(ask) == expected


def test_the_injected_call_carries_the_hours() -> None:
    from arelis.tools.weather import draft_weather_args

    args = draft_weather_args("will it rain at 3pm in Metropolis")

    assert args["hours"] == 12
    assert args["place"] == "Metropolis"


def test_filling_only_widens_what_the_model_chose() -> None:
    """A model that asked for 24 hours knows more than the regex does."""
    from arelis.tools.weather import fill_weather_args

    kept = fill_weather_args({"hours": 24}, "will it rain at 3pm")
    assert kept["hours"] == 24

    added = fill_weather_args({}, "will it rain at 3pm")
    assert added["hours"] == 12

    untouched = fill_weather_args({}, "what's the weather")
    assert "hours" not in untouched


def test_the_schema_offers_the_new_shape() -> None:
    props = WeatherTool.parameters_schema["properties"]
    assert "hours" in props
    assert "past_days" in props
    assert "hours" in WeatherTool.description
