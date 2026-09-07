"""Same successful tool+args this turn is a loop, not more work."""

from __future__ import annotations

from arelis.core.same_call import (
    already_ran_same_call,
    normalize_workspace_path,
    record_same_call,
    same_call_finish_line,
    same_call_finishes_turn,
    same_call_key,
    same_call_notice,
    same_call_strips_tools,
)


def test_root_list_aliases_are_the_same_call() -> None:
    keys = {
        same_call_key("workspace", {"action": "list"}),
        same_call_key("workspace", {"action": "list", "path": ""}),
        same_call_key("workspace", {"action": "list", "path": "."}),
        same_call_key("workspace", {"action": "list", "path": "./"}),
        same_call_key("workspace", {"action": "list", "path": "."}),
    }
    assert None not in keys
    assert len(keys) == 1
    assert normalize_workspace_path("", "list") == "."
    assert normalize_workspace_path("arelis/", "list") == "arelis"
    assert normalize_workspace_path("arelis\\physics", "list") == "arelis/physics"


def test_new_folder_or_file_is_new_work() -> None:
    root = same_call_key("workspace", {"action": "list", "path": "."})
    physics = same_call_key("workspace", {"action": "list", "path": "arelis/physics"})
    engine = same_call_key(
        "workspace", {"action": "read", "path": "arelis/physics/engine.py"}
    )
    constants = same_call_key(
        "workspace", {"action": "read", "path": "arelis/physics/constants.py"}
    )
    assert root != physics
    assert engine != constants
    assert engine != physics


def test_same_read_is_blocked_after_success() -> None:
    same_ok: set[str] = set()
    args = {"action": "read", "path": "arelis/physics/engine.py"}
    assert already_ran_same_call(same_ok, "workspace", args) is None
    record_same_call(same_ok, "workspace", args)
    notice = already_ran_same_call(same_ok, "workspace", args)
    assert notice is not None
    assert "Already read" in notice
    assert "engine.py" in notice
    assert already_ran_same_call(
        same_ok,
        "workspace",
        {"action": "read", "path": "arelis/physics/scene.py"},
    ) is None


def test_same_list_is_blocked_slash_aliases() -> None:
    same_ok: set[str] = set()
    record_same_call(same_ok, "workspace", {"action": "list", "path": "."})
    notice = already_ran_same_call(same_ok, "workspace", {"action": "list"})
    assert notice is not None
    assert "Already listed" in notice
    assert already_ran_same_call(
        same_ok, "workspace", {"action": "list", "path": "arelis/physics"}
    ) is None


def test_failed_calls_are_not_recorded_by_helpers() -> None:
    """record_same_call is only invoked on ok; an empty set means retry is free."""
    same_ok: set[str] = set()
    args = {"action": "list", "path": "arelis"}
    assert already_ran_same_call(same_ok, "workspace", args) is None


def test_write_invalidates_parent_list() -> None:
    same_ok: set[str] = set()
    listing = {"action": "list", "path": "notes"}
    record_same_call(same_ok, "workspace", listing)
    record_same_call(
        same_ok,
        "workspace",
        {"action": "write", "path": "notes/todo.md", "content": "hi"},
    )
    assert already_ran_same_call(same_ok, "workspace", listing) is None


def test_write_invalidates_read_of_that_file() -> None:
    same_ok: set[str] = set()
    read = {"action": "read", "path": "notes/todo.md"}
    record_same_call(same_ok, "workspace", read)
    assert already_ran_same_call(same_ok, "workspace", read)
    record_same_call(
        same_ok,
        "workspace",
        {"action": "write", "path": "notes/todo.md", "content": "hi"},
    )
    assert already_ran_same_call(same_ok, "workspace", read) is None


def test_different_max_chars_is_new_work() -> None:
    a = same_call_key(
        "workspace",
        {"action": "read", "path": "arelis/physics/scene.py", "max_chars": 14000},
    )
    b = same_call_key(
        "workspace",
        {"action": "read", "path": "arelis/physics/scene.py", "max_chars": 40000},
    )
    assert a != b


def test_rooms_get_repeats_and_browser_does_not() -> None:
    same_ok: set[str] = set()
    get = {"action": "get", "name": "physics"}
    record_same_call(same_ok, "rooms", get)
    notice = already_ran_same_call(same_ok, "rooms", get)
    assert notice is not None
    assert "rooms" in notice
    assert already_ran_same_call(
        same_ok, "rooms", {"action": "get", "name": "lab"}
    ) is None
    snap = {"action": "snapshot"}
    assert same_call_key("browser", snap) is None
    record_same_call(same_ok, "browser", snap)
    assert already_ran_same_call(same_ok, "browser", snap) is None


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


def test_research_report_same_query_ignores_max_sources() -> None:
    a = same_call_key(
        "research_report",
        {"query": "Grey alien abduction 1960-2026", "max_sources": 8},
    )
    b = same_call_key(
        "research_report",
        {"query": "grey alien abduction 1960-2026", "max_sources": 50},
    )
    assert a == b
    same_ok: set[str] = set()
    record_same_call(
        same_ok,
        "research_report",
        {"query": "Grey alien abduction 1960-2026", "max_sources": 8},
    )
    notice = already_ran_same_call(
        same_ok,
        "research_report",
        {"query": "Grey alien abduction 1960-2026", "max_sources": 50},
    )
    assert notice is not None
    assert "research_report" in notice


def test_same_call_notice_names_the_path() -> None:
    text = same_call_notice("workspace", {"action": "list", "path": "arelis/physics"})
    assert "arelis/physics" in text
    assert "not listing" in text


def test_same_call_finish_line_ships_the_prior_result() -> None:
    assert same_call_finish_line("calculator", "840 * 0.175 = 147") == "840 * 0.175 = 147"
    assert "already have that result" in same_call_finish_line("calculator", "").lower()
    assert "tab is open" in same_call_finish_line("browser", "").lower()


def test_same_call_cas_does_not_finish_the_turn() -> None:
    assert same_call_finishes_turn("calculator")
    assert not same_call_finishes_turn("cas")
    assert not same_call_finishes_turn("python")
    assert same_call_strips_tools("cas")
    assert same_call_strips_tools("python")
    assert not same_call_strips_tools("workspace")
