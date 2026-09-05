"""One intent catalog drives preflight, schema subset, and exactness."""

from __future__ import annotations

from arelis.core.claims import (
    apply_research_web_need,
    detect_exactness_need,
    detect_inbox_ask,
    draft_catalog_args,
)
from arelis.core.intent_catalog import (
    COMPOSE_EMAIL,
    DIAGNOSTICS,
    EARTH_STATUS,
    INBOX,
    RUN_SCRIPT,
    SMS_SEND,
    SOLAR_BODY,
    SOLAR_STATUS,
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


_BATTERY_RESEARCH = """
Research Prompt:
As of September 2026, provide a rigorous, evidence-based assessment of
solid-state lithium batteries for electric vehicles.
Extract operating temperature range, cycle life, and energy density.
Provide a concise comparative table and a short hype vs. reality verdict.
"""


def test_battery_research_is_not_weather() -> None:
    from arelis.core.intent_catalog import weather_intent_matches
    from arelis.core.preflight import detect_intents
    from arelis.core.tool_subset import is_deep_dive_ask

    assert "temperature" in _BATTERY_RESEARCH.lower()
    assert not weather_intent_matches(_BATTERY_RESEARCH)
    assert not exactness_match("weather", _BATTERY_RESEARCH)
    assert is_deep_dive_ask(_BATTERY_RESEARCH)
    kinds = [h.kind for h in detect_intents(_BATTERY_RESEARCH)]
    assert "research" in kinds
    assert "weather" not in kinds
    assert not detect_exactness_need(_BATTERY_RESEARCH).needs_weather


def test_lab_temperature_in_a_derivation_is_not_weather() -> None:
    from arelis.core.intent_catalog import weather_intent_matches

    ask = (
        "Coating Brownian thermal noise on fused silica at temperature $T$. "
        "T = 293 K, lambda = 1064 nm. Derive the SQL."
    )
    assert "temperature" in ask.lower()
    assert not weather_intent_matches(ask)
    assert "weather" not in [h.kind for h in detect_intents(ask)]


def test_how_hot_is_still_weather() -> None:
    from arelis.core.intent_catalog import weather_intent_matches

    ask = "What's the temperature today?"
    assert weather_intent_matches(ask)
    assert exactness_match("weather", ask)
    assert any(h.kind == "weather" for h in detect_intents(ask))


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


def test_solar_body_is_one_source_among_others() -> None:
    assert SOLAR_BODY.matches("how big is Mars, like the radius")
    assert SOLAR_BODY.matches("what's the gravity on Jupiter")
    assert SOLAR_BODY.matches("where is Saturn")
    assert not SOLAR_BODY.matches("what's the weather")
    assert "solar" in SOLAR_BODY.schema_tools
    assert "catalog" in SOLAR_BODY.schema_tools


def test_solar_and_earth_status_are_not_browser() -> None:
    assert SOLAR_STATUS.matches("what's the solar system status")
    assert SOLAR_STATUS.matches("dump the solar system state")
    assert not SOLAR_STATUS.matches("directions to the Empire State Building")
    assert EARTH_STATUS.matches("what's the earth status")
    assert EARTH_STATUS.matches("dump the earth state")
    assert not EARTH_STATUS.matches("how big is Earth")
    args = draft_catalog_args("ask Horizons where Mars is today")
    assert args["action"] == "horizons"
    assert args["target"] == "Mars"


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
    assert inspect_read_path(
        "look at the files for an accurate assessment of the solar system simulation"
    ) == "arelis/physics/engine.py"
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
    assert "arelis/physics/engine.py" in guide
    assert "arelis/physics/horizons.py" in guide
    assert "docs/architecture.md" in guide
    nudge = inspect_preflight_nudge("what's in policy.py?")
    assert "arelis/tools/policy.py" in nudge
    assert "workspace(action=read)" in nudge


def test_inbox_latest_is_not_a_page_warrant() -> None:
    ask = "What's in my inbox? Summarize the latest few messages."
    need = detect_exactness_need(ask)
    assert need.needs_inbox
    assert not need.needs_web_evidence
    sticky = apply_research_web_need(need, research_mode=True, text=ask)
    assert sticky.needs_inbox
    assert not sticky.needs_web_evidence


def test_unread_email_subjects_is_inbox_not_web() -> None:
    ask = "Do I have any unread email? List only the subjects."
    need = detect_exactness_need(ask)
    assert need.needs_inbox
    assert not need.needs_calculator
    assert not need.needs_web_evidence
    sticky = apply_research_web_need(need, research_mode=True, text=ask)
    assert sticky.needs_inbox
    assert not sticky.needs_web_evidence


def test_iso_calendar_create_is_not_math() -> None:
    from arelis.core.claims import detect_math_ask

    ask = (
        "Create a calendar event titled Arelis stay BRD-014135. "
        "Use agenda action=create with start=2026-09-06T15:00:00 and "
        "end=2026-09-06T15:30:00 (tomorrow 3:00–3:30 PM)."
    )
    assert not detect_math_ask(ask)
    need = detect_exactness_need(ask)
    assert not need.needs_calculator
    assert detect_math_ask("What is 12.5% of 640?")
    assert detect_math_ask("what is 17-3")
