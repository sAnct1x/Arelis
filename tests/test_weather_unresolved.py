"""An address the gazetteer cannot resolve ends the turn.

The digits in '123 Fakeplace Street 99999' used to look like arithmetic, so
after the lookup missed the model guessed Springfield and the verify gate
refused the turn as if it needed a calculator.
"""

from __future__ import annotations

import asyncio

import pytest

from arelis.core.claims import detect_exactness_need
from arelis.core.evidence import EvidenceLedger
from arelis.core.loop_helpers import _exactness_finish_refuse
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.weather import WeatherTool
from tests.test_named_tools_owed_native import (
    _FLAG_OFF,
    _call,
    _run_agent_with_script,
)
from tests.test_weather_tool import _PARIS_FR

_ASK = "what's the weather at 123 Fakeplace Street 99999"
_PARIS_ASK = "what's the weather in Paris"
_NOT_FOUND = "I couldn't find that place."
_PARIS = "Paris, France: 61\u00b0F and overcast, high 66\u00b0F, low 48\u00b0F."
_SPRINGFIELD = {
    "name": "Springfield",
    "latitude": 39.7817,
    "longitude": -89.6501,
    "admin1": "Illinois",
    "country": "United States",
    "country_code": "US",
    "population": 116250,
}


def _reading() -> dict:
    return {
        "current": {"temperature_2m": 61.2, "weather_code": 3},
        "daily": [{"temperature_2m_max": 66.4, "temperature_2m_min": 48.2}],
    }


class _Lookup:
    def __init__(self, rows_for) -> None:
        self.queries: list[str] = []
        self.forecasts: list[tuple[float, float]] = []
        self._rows_for = rows_for

    async def geocode(self, query: str) -> list[dict]:
        self.queries.append(query)
        return list(self._rows_for(query) or [])

    async def forecast(self, lat: float, lon: float, days: int = 1) -> dict:
        self.forecasts.append((lat, lon))
        return _reading()


class _Watch(WeatherTool):
    def __init__(self, lookup: _Lookup) -> None:
        super().__init__(
            windows_location=lambda: None,
            home_city=lambda: "",
            ip_location=lambda: None,
            geocode=lookup.geocode,
            forecast=lookup.forecast,
        )
        self.ran: list[tuple[dict, ToolResult]] = []

    async def run(self, **kwargs: object) -> ToolResult:
        result = await super().run(**kwargs)
        self.ran.append((dict(kwargs), result))
        return result


def _unresolved_rows(query: str) -> list[dict]:
    if query.casefold() == "springfield":
        return [_SPRINGFIELD]
    return []


def _paris_rows(query: str) -> list[dict]:
    if query.casefold() == "paris":
        return [_PARIS_FR]
    if query.casefold() == "springfield":
        return [_SPRINGFIELD]
    return []


def test_unresolved_address_is_not_found_and_does_not_retry_another_place() -> None:
    """Empty geocode is a not-found result. Springfield is not looked up."""
    lookup = _Lookup(_unresolved_rows)
    weather = _Watch(lookup)
    reg = ToolRegistry()
    reg.register(weather)
    script = [
        _call("weather", {"place": "123 Fakeplace Street 99999"}),
        _call("weather", {"place": "Springfield"}),
        [("token", "Springfield is 70 and sunny.")],
    ]
    final_text, tool_results, _thinking = asyncio.run(
        _run_agent_with_script(
            _ASK,
            script,
            ["weather"],
            {**_FLAG_OFF, "max_rounds": 8},
            registry=reg,
        )
    )
    assert tool_results == [("weather", False)], tool_results
    assert len(weather.ran) == 1
    result = weather.ran[0][1]
    assert result.data.get("status") == "not_found"
    assert result.output == _NOT_FOUND
    assert final_text.strip() == _NOT_FOUND
    assert not any(query.casefold() == "springfield" for query in lookup.queries)
    assert lookup.forecasts == []
    assert "calculator" not in final_text.casefold()


def test_verify_gate_does_not_mark_unresolved_weather_as_math() -> None:
    """Digits in the address are not arithmetic once the lookup is not_found."""
    ask = _ASK
    need = detect_exactness_need(ask)
    assert "math" in need.kinds
    ledger = EvidenceLedger()
    ledger.record_tool(
        "weather",
        ok=False,
        output=_NOT_FOUND,
        data={"status": "not_found"},
    )
    missing = ledger.missing_kinds(need.kinds)
    assert "math" not in missing
    refuse = _exactness_finish_refuse(
        "Springfield is 70 and sunny.",
        exact_need=need,
        ledger=ledger,
        numeric_gate=True,
        evidence_gate=True,
    )
    assert refuse is None or "calculator" not in refuse.casefold()


@pytest.mark.asyncio
async def test_paris_lookup_is_unchanged() -> None:
    """A city the gazetteer resolves is still the forecast, not a miss."""
    lookup = _Lookup(_paris_rows)
    weather = _Watch(lookup)
    result = await weather.run(place="Paris")

    assert result.ok
    assert result.output == _PARIS
    assert result.data.get("status") == "resolved"
    assert result.data.get("place") == "Paris, France"
    assert lookup.queries == ["Paris"]
    assert lookup.forecasts == [
        (_PARIS_FR["latitude"], _PARIS_FR["longitude"])
    ]

    reg = ToolRegistry()
    reg.register(weather)
    weather.ran.clear()
    lookup.queries.clear()
    lookup.forecasts.clear()
    script = [
        _call("weather", {"place": "Paris"}),
        _call("weather", {"place": "Springfield"}),
        [("token", _PARIS)],
    ]
    final_text, tool_results, _thinking = await _run_agent_with_script(
        _PARIS_ASK,
        script,
        ["weather"],
        {**_FLAG_OFF, "max_rounds": 8},
        registry=reg,
    )
    assert [name for name, ok in tool_results] == ["weather", "weather"]
    assert tool_results[0][1] is True
    assert weather.ran[0][1].output == _PARIS
    assert weather.ran[0][1].data.get("status") == "resolved"
    assert "couldn't find that place" not in final_text.casefold()
    assert "calculator" not in final_text.casefold()
    assert "Paris, France" in final_text
