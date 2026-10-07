"""The weather turn must not send her looking for a location she never needs.

Measured 2026-09-17 with scripts/measure_tool_choice.py against qwen3.5:9b:
"what's the weather going to be like tomorrow?" calls `user_location`, not
`weather`, on every unguarded run and with the preflight nudge on as well.

That pick is always wasted work. `WeatherTool` resolves the user's location
itself, and it deliberately refuses coordinates — see the class docstring in
arelis/tools/weather.py, which pins that small models invent the lat/lon of
whichever big city they have seen most often. So there is nothing
`user_location` can return that `weather` can accept.

`_hide_daily_wander` drops `_WEATHER_WANDER` when weather is expected.
`user_location` belongs in that set: hiding only the search tools is what
pushed the model onto it. Weather is forced by the preinject now; this file
only checks the set. `_SMS_WANDER` already lists `user_location` for the
same reason.
"""

from __future__ import annotations

from arelis.core.agent_loop import (
    _SMS_WANDER,
    _WEATHER_WANDER,
    _hide_daily_wander,
    _offer_expected,
)

# What a weather turn would plausibly have on the table.
VISIBLE = {
    "weather",
    "user_location",
    "web_search",
    "scrape",
    "web_fetch",
    "browser",
    "contacts",
}


def test_the_sms_path_already_hides_user_location() -> None:
    """The precedent. This passes today and is why the weather gap is a gap."""
    assert "user_location" in _SMS_WANDER
    offered = _hide_daily_wander(VISIBLE, {"send_sms"})
    assert "user_location" not in offered


def test_user_location_is_hidden_on_a_weather_turn() -> None:
    """The bug. weather resolves its own location, so this is always a wasted round."""
    offered = _hide_daily_wander(VISIBLE, {"weather"})
    assert "weather" in offered, "the tool the turn is about must survive"
    assert "user_location" not in offered


def test_user_location_is_in_the_weather_wander_set() -> None:
    """``_hide_daily_wander`` drops this set on a weather turn, so the hole is in the set."""
    assert "user_location" in _WEATHER_WANDER


def test_a_turn_that_wants_the_place_too_still_gets_user_location() -> None:
    """Hiding is safe because _offer_expected runs straight after it.

    Both call sites (turn_round.py and turn_prepare.py) hide, then add the
    expected set back. So "where am I, and what's the weather" keeps both
    tools even once user_location is in _WEATHER_WANDER.
    """
    expected = {"weather", "user_location"}
    hidden = _hide_daily_wander(VISIBLE, expected)
    offered = _offer_expected(hidden, expected, VISIBLE)
    assert "user_location" in offered
    assert "weather" in offered


def test_hiding_weather_wander_still_drops_the_search_tools() -> None:
    """The original job of the set must not regress while widening it."""
    offered = _hide_daily_wander(VISIBLE, {"weather"})
    assert not ({"web_search", "scrape", "web_fetch"} & offered)
