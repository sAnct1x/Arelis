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


def test_the_schema_is_one_optional_place() -> None:
    """Hours and past days are not model-facing. One sentence is the result."""
    props = WeatherTool.parameters_schema["properties"]
    assert list(props) == ["place"]
    assert WeatherTool.parameters_schema["required"] == []
    assert "hours" not in props
    assert "past_days" not in props
    lowered = WeatherTool.description.lower()
    assert "hours" not in lowered
    assert "weather tool" not in lowered


def test_fill_never_passes_days_hours_or_past_days() -> None:
    from arelis.tools.weather import fill_weather_args

    kept = fill_weather_args({"hours": 24, "days": 3, "past_days": 1}, "will it rain at 3pm")
    assert "hours" not in kept
    assert "days" not in kept
    assert "past_days" not in kept

    added = fill_weather_args({}, "will it rain at 3pm")
    assert "hours" not in added
    assert "days" not in added
    assert "past_days" not in added


def test_garbled_after_tomorrow_is_not_a_city() -> None:
    from arelis.tools.weather import (
        draft_weather_args,
        extract_weather_place,
        weather_places_missing,
        weather_places_wanted,
    )

    ask = "Oh does it what is the forecast say after to tomorrow"
    assert extract_weather_place(ask) == ""
    assert weather_places_wanted(ask) == [""]
    assert "place" not in draft_weather_args(ask)
    assert weather_places_missing(ask, {""}) == []
    assert weather_places_missing(ask, set(), {"oh does it say after to"}) == [""]


def test_to_morrow_is_tomorrow_not_a_city() -> None:
    """Live dump: 'to morrow' was geocoded, then she asked which other city."""
    from arelis.tools.weather import (
        draft_weather_args,
        extract_weather_place,
        extract_weather_places,
        fill_weather_args,
        weather_places_missing,
        weather_places_wanted,
        weather_wants_beyond_today,
    )

    ask = "What's the weather going to be like to morrow"
    assert extract_weather_place(ask) == ""
    assert extract_weather_places(ask) == []
    assert weather_places_wanted(ask) == [""]
    assert "place" not in draft_weather_args(ask)
    assert weather_wants_beyond_today(ask)
    stripped = fill_weather_args({"place": "Springfield", "days": 2}, ask)
    assert "place" not in stripped
    assert "days" not in stripped
    assert weather_places_missing(ask, {""}) == []
    # A named-city reading is not home. Profile coords still need a call.
    assert weather_places_missing(ask, {"springfield"}) == [""]


