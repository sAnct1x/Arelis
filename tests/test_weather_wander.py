"""The weather turn must not send her looking for a location she never needs.

Measured 2026-09-17 with scripts/measure_tool_choice.py against qwen3.5:9b:
"what's the weather going to be like tomorrow?" calls `user_location`, not
`weather`, on every unguarded run and with the preflight nudge on as well.

That pick is always wasted work. `WeatherTool` resolves the user's location
itself, and it deliberately refuses coordinates — see the class docstring in
arelis/tools/weather.py, which pins that small models invent the lat/lon of
whichever big city they have seen most often. So there is nothing
`user_location` can return that `weather` can accept.

Two sibling mechanisms should have caught it and neither does:

  `_hide_daily_wander` drops `_WEATHER_WANDER` when weather is expected, but
  that set is only {web_search, scrape, web_fetch}. Hiding those three is what
  pushes the model onto `user_location`, which stays visible.

  `redirect_weather` in call_redirects.py fires on `name in _WEATHER_WANDER`,
  so it inherits the same hole and never sees the call.

`_SMS_WANDER` already lists `user_location` for exactly this reason. The two
paths disagree, and the weather one is the one that is wrong.
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


def test_redirect_weather_covers_the_tool_the_model_actually_picks() -> None:
    """redirect_weather triggers on membership here, so the hole is in the set."""
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
