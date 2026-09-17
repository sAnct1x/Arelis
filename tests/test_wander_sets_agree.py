"""The hide set and the redirect set have to describe the same wander.

This is the bug class that already cost a fix once. `6203c8b`: `user_location`
was missing from `_WEATHER_WANDER`, so hiding the three search tools on a
weather turn pushed the model onto the one tool nothing redirected, and the
turn burned a round going nowhere. Four words in a frozenset.

The two halves are written in different files by different hands:
`_hide_daily_wander` in agent_loop decides what is *offered*, and the steps in
call_redirects decide what is *rewritten when it is called anyway*. Nothing
made them agree, so they drifted. These tests compare them directly instead of
waiting for the next live session to notice.

A tool in the redirect set but not the hide set is the mild direction: it gets
offered, the model takes it, the redirect catches it, one round is burned. A
tool in neither is the `6203c8b` failure and is silent.
"""

from __future__ import annotations

from arelis.core.agent_loop import (
    _BROWSER_WANDER,
    _LOCAL_STORE,
    _WEATHER_WANDER,
    _hide_daily_wander,
)

# Mirrors the `name in {...}` guard at the top of
# call_redirects.redirect_local_store. Kept here so a change to one side
# without the other is a failing test rather than a live misroute.
_LOCAL_STORE_REDIRECTED = {
    "weather",
    "web_search",
    "browser",
    "scrape",
    "web_fetch",
    "user_location",
}

ALL_TOOLS = {
    "weather",
    "web_search",
    "scrape",
    "web_fetch",
    "browser",
    "user_location",
    "research_report",
    "tasks",
    "goals",
    "memory",
    "contacts",
    "recall",
    "workspace",
    "send_sms",
    "send_email",
}


def _hidden_for(expected: set[str]) -> set[str]:
    return ALL_TOOLS - _hide_daily_wander(set(ALL_TOOLS), expected)


def test_a_weather_turn_hides_everything_it_redirects() -> None:
    """The 6203c8b fix, pinned so it cannot regress quietly."""
    hidden = _hidden_for({"weather"})
    assert _WEATHER_WANDER <= hidden


def test_a_browser_turn_hides_everything_it_redirects() -> None:
    hidden = _hidden_for({"browser"})
    assert _BROWSER_WANDER <= hidden


def test_a_local_store_turn_hides_everything_it_redirects() -> None:
    """Found the same way as 6203c8b, by comparing the two sets.

    redirect_local_store rewrites user_location on a tasks / goals / memory /
    contacts turn, which means it is known wander there. _hide_daily_wander
    offered it anyway, so the model could take it and cost a round that the
    redirect then had to undo.
    """
    for store in sorted(_LOCAL_STORE):
        hidden = _hidden_for({store})
        missing = _LOCAL_STORE_REDIRECTED - hidden
        assert not missing, (
            f"on a {store} turn these are redirected but still offered: "
            f"{sorted(missing)}"
        )


def test_the_place_comes_back_when_the_turn_actually_wants_it() -> None:
    """Hiding is only safe because _offer_expected runs straight after.

    "where am I, and what are my tasks" must keep user_location. This is the
    same argument the _WEATHER_WANDER comment makes, checked rather than
    asserted in a comment.
    """
    from arelis.core.agent_loop import _offer_expected

    expected = {"tasks", "user_location"}
    offered = _hide_daily_wander(set(ALL_TOOLS), expected)
    offered = _offer_expected(offered, expected, ALL_TOOLS)
    assert "user_location" in offered


def test_the_local_store_tool_itself_is_never_hidden() -> None:
    """Hiding the tool the turn is about would be the worst possible fix."""
    for store in sorted(_LOCAL_STORE):
        assert store not in _hidden_for({store})
