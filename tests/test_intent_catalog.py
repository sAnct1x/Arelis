"""One intent catalog drives preflight, schema subset, and exactness."""

from __future__ import annotations

from arelis.core.claims import detect_exactness_need, detect_inbox_ask
from arelis.core.intent_catalog import (
    COMPOSE_EMAIL,
    DIAGNOSTICS,
    INBOX,
    RUN_SCRIPT,
    SMS_SEND,
    WATCH,
    WEATHER,
    exactness_match,
    must_keep_full_surface_text,
    research_extras_for_text,
)
from arelis.core.preflight import detect_intents
from arelis.core.tool_subset import filter_tool_names

_EVERYDAY = {
    "weather",
    "user_location",
    "web_fetch",
    "web_search",
    "scrape",
    "calculator",
    "cas",
    "units",
    "plot",
    "catalog",
    "send_sms",
    "inbound_sms",
    "contacts",
    "inbox",
    "send_email",
    "image",
    "recall",
    "memory",
}


def test_weather_catalog_matches_preflight_and_exactness() -> None:
    ask = "What's the weather today?"
    assert WEATHER.matches(ask)
    assert exactness_match("weather", ask)
    assert any(h.kind == "weather" for h in detect_intents(ask))
    need = detect_exactness_need(ask)
    assert need.needs_weather
    assert not exactness_match("weather", "What is humidity?")
    assert not detect_exactness_need("What is humidity?").needs_weather
    job = (
        "Get the weather forecast for Springfield, IL and Metropolis, IL. "
        "Summarize the current conditions and forecast for both locations."
    )
    assert WEATHER.matches(job)
    assert exactness_match("weather", job)
    assert detect_exactness_need(job).needs_weather


def test_sms_and_email_keep_full_surface() -> None:
    assert must_keep_full_surface_text("text Brian that I am late")
    assert must_keep_full_surface_text("send an email to bob@example.com")
    assert SMS_SEND.full_surface
    assert COMPOSE_EMAIL.full_surface
    assert not must_keep_full_surface_text("What's the weather today?")
    assert not must_keep_full_surface_text("read the text in this screenshot")
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="Text Brian: Running 10 minutes late",
        enabled=True,
        skill_subset=True,
    )
    assert "send_sms" in visible
    assert "contacts" in visible
    assert "send_email" not in visible


def test_inbox_is_read_not_compose() -> None:
    ask = "check my inbox"
    assert INBOX.matches(ask)
    assert detect_inbox_ask(ask)
    hints = detect_intents(ask)
    assert any(h.kind == "inbox" for h in hints)
    assert not any(h.kind == "compose_email" for h in hints)
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text=ask,
        enabled=True,
        skill_subset=True,
    )
    assert "inbox" in visible
    assert "send_email" in visible
    assert "image" not in visible
    assert "send_sms" not in visible


def test_inbox_hears_in_box_and_emiles() -> None:
    from arelis.core.skills import select_skill_ids

    for ask in (
        "Check your in box",
        "check your inbox",
        "any new emiles today",
        "Did you get any new emile",
    ):
        assert INBOX.matches(ask), ask
        assert detect_inbox_ask(ask), ask
        assert any(h.kind == "inbox" for h in detect_intents(ask)), ask
        ids = select_skill_ids(ask, available_tools={"inbox", "send_email"})
        assert "email" in ids, ask


def test_unmatched_chat_fails_open() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="how do I tie a necktie",
        enabled=True,
        skill_subset=True,
    )
    assert "calculator" in visible
    assert "weather" in visible
    assert "send_sms" not in visible
    assert "send_email" not in visible


def test_research_extras_add_inbox_on_deep_dive() -> None:
    extra = research_extras_for_text(
        "Deep dive the budget and check my inbox"
    )
    assert "inbox" in extra
    assert "send_email" in extra


def test_diagnostics_catalog_is_phrase_only() -> None:
    assert DIAGNOSTICS.matches("run diagnostics")
    assert DIAGNOSTICS.matches("hey arelis, run diagnostics")
    assert not DIAGNOSTICS.matches("run diagnostics on my car")
    assert not DIAGNOSTICS.matches("don't run diagnostics")
    assert any(h.kind == "diagnostics" for h in detect_intents("run diagnostics"))
    assert not any(
        h.kind == "diagnostics" for h in detect_intents("run diagnostics on my car")
    )
    extra = research_extras_for_text("run diagnostics")
    assert "diagnostics" in extra
    assert "diagnostics" not in research_extras_for_text("what's the weather")


def test_run_script_catalog_is_phrase_only() -> None:
    assert RUN_SCRIPT.matches("run measure_drift.py")
    assert RUN_SCRIPT.matches("execute lab/measure_drift.py")
    assert RUN_SCRIPT.matches("run the script")
    assert RUN_SCRIPT.matches("run it again")
    assert not RUN_SCRIPT.matches("run diagnostics")
    assert not RUN_SCRIPT.matches("run the tests")
    assert not RUN_SCRIPT.matches("run this job now")
    assert not RUN_SCRIPT.matches("run now")
    assert any(h.kind == "run_script" for h in detect_intents("run measure_drift.py"))
    assert not any(h.kind == "run_script" for h in detect_intents("run diagnostics"))
    available = _EVERYDAY | {"run_script", "diagnostics"}
    on = filter_tool_names(
        available,
        role="fast",
        text="run measure_drift.py and tell me the results",
        enabled=False,
        skill_subset=False,
    )
    assert "run_script" in on
    off = filter_tool_names(
        available,
        role="fast",
        text="what's the weather today?",
        enabled=False,
        skill_subset=False,
    )
    assert "run_script" not in off


def test_watch_catalog_is_phrase_only() -> None:
    assert WATCH.matches("are we safe?")
    assert WATCH.matches("are the ports open")
    assert WATCH.matches("house watch")
    assert not WATCH.matches("watch a movie")
    assert not WATCH.matches("port wine")
    assert any(h.kind == "watch" for h in detect_intents("are we safe?"))
    extra = research_extras_for_text("are we safe")
    assert "watch" in extra
    available = _EVERYDAY | {"watch", "diagnostics"}
    on = filter_tool_names(
        available,
        role="fast",
        text="are we safe?",
        enabled=False,
        skill_subset=False,
    )
    assert "watch" in on
    off = filter_tool_names(
        available,
        role="fast",
        text="what's the weather today?",
        enabled=False,
        skill_subset=False,
    )
    assert "watch" not in off


def test_identity_ask_is_tiny_and_who_is_this_is_not() -> None:
    from arelis.core.intent_catalog import (
        is_tiny_prompt_ask,
        looks_like_identity_ask,
    )

    assert looks_like_identity_ask("who are you")
    assert looks_like_identity_ask("What's your name?")
    assert is_tiny_prompt_ask("who are you")
    assert not looks_like_identity_ask("Who is this")
    assert not looks_like_identity_ask("who won the fight")
    assert not is_tiny_prompt_ask("Who is this")


def test_source_inspect_catalog_and_path_map() -> None:
    from arelis.core.intent_catalog import (
        AUTO_HINTS,
        BY_KIND,
        INSPECT,
        INSPECT_WRITE,
        inspect_read_path,
        looks_like_source_inspect,
        looks_like_source_write,
    )

    assert INSPECT.kind == "inspect"
    assert INSPECT.expected_tools == ("workspace",)
    assert INSPECT.schema_tools == frozenset({"workspace", "git_info"})
    assert INSPECT.auto_hint
    assert INSPECT.research_extra
    assert INSPECT_WRITE.kind == "inspect_write"
    assert INSPECT_WRITE.expected_tools == ("workspace",)
    assert INSPECT_WRITE.auto_hint
    assert BY_KIND["inspect"] is INSPECT
    assert BY_KIND["inspect_write"] is INSPECT_WRITE
    assert INSPECT in AUTO_HINTS
    assert INSPECT_WRITE in AUTO_HINTS
    assert inspect_read_path("how do you work") == "docs/architecture.md"
    assert inspect_read_path("show me your source") == "docs/architecture.md"
    assert inspect_read_path("what's in orchestrator.py") == (
        "arelis/core/orchestrator.py"
    )
    assert inspect_read_path("read docs/architecture.md") == "docs/architecture.md"
    assert looks_like_source_inspect("how do you work")
    assert looks_like_source_write("edit policy.py")
    assert not looks_like_source_inspect("edit policy.py")
    assert not looks_like_source_inspect("how does pytest work")
    assert not looks_like_source_inspect("cite your source")
    assert not looks_like_source_inspect("the confirm gate paused that write")
    assert not looks_like_source_inspect("email me docs/architecture.md")
    assert not looks_like_source_inspect("email me policy.py")
    extra = research_extras_for_text("what's in policy.py?")
    assert "workspace" in extra
    assert "git_info" in extra
    from arelis.core.intent_catalog import inspect_path_guide, inspect_preflight_nudge

    guide = inspect_path_guide()
    assert "arelis/tools/policy.py" in guide
    assert "arelis/core/tool_subset.py" in guide
    assert "arelis/ui/panels/drive.py" in guide
    assert "docs/architecture.md" in guide
    nudge = inspect_preflight_nudge("what's in policy.py?")
    assert "arelis/tools/policy.py" in nudge
    assert "workspace(action=read)" in nudge
