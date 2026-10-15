"""Same successful tool+args this turn is a loop, not more work."""

from __future__ import annotations

from arelis.core.same_call import (
    already_ran_same_call,
    record_same_call,
    same_call_finishes_turn,
    same_call_key,
    same_call_strips_tools,
)


def test_same_browser_open_url_is_a_loop() -> None:
    same_ok: set[str] = set()
    args = {
        "action": "open",
        "url": "https://www.quantumscape.com/technology/solid-state-batteries/",
    }
    record_same_call(same_ok, "browser", args)
    notice = already_ran_same_call(same_ok, "browser", args)
    assert notice is not None
    assert "Already opened" in notice
    assert "Stop" in notice
    assert "research_report" not in notice
    assert already_ran_same_call(
        same_ok,
        "browser",
        {"action": "open", "url": "https://www.bloomberg.com/news/articles/x"},
    ) is None
    assert same_call_key("browser", {"action": "click", "text": "Sign in"}) is None
    assert same_call_key(
        "browser",
        {"action": "navigate", "url": args["url"]},
    ) == same_call_key("browser", args)
    wait = {"action": "wait", "url": "https://x.com/home"}
    record_same_call(same_ok, "browser", wait)
    notice = already_ran_same_call(same_ok, "browser", wait)
    assert notice is not None
    assert "waited" in notice.lower()
    assert already_ran_same_call(
        same_ok, "browser", {"action": "wait", "text": "Home"}
    ) is None
    assert same_call_key("browser", {"action": "wait", "seconds": 1}) is None


def test_weather_and_search_stay_on_their_own_gates() -> None:
    assert same_call_key("weather", {"place": "Boston"}) is None
    assert same_call_key("web_search", {"query": "fusion"}) is None
    assert same_call_key("run_script", {"path": "demo.py"}) is None
    assert same_call_key("run_task", {"action": "run", "name": "pytest"}) is None


def test_same_call_cas_does_not_finish_the_turn() -> None:
    assert same_call_finishes_turn("calculator")
    assert not same_call_finishes_turn("cas")
    assert not same_call_finishes_turn("python")
    assert same_call_strips_tools("cas")
    assert same_call_strips_tools("python")
    assert not same_call_strips_tools("calculator")
    assert not same_call_strips_tools("workspace")
