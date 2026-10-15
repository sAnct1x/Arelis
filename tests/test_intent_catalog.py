"""One intent catalog drives preflight, schema subset, and exactness."""

from __future__ import annotations

from arelis.core.claims import (
    detect_exactness_need,
    detect_inbox_ask,
)
from arelis.core.intent_catalog import (
    COMPOSE_EMAIL,
    INBOX,
    SMS_SEND,
    WEATHER,
    exactness_match,
    must_keep_full_surface_text,
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


def test_first_unnegated_skips_declined_hits() -> None:
    import re

    from arelis.core.intent_catalog import first_unnegated

    pat = re.compile(r"(?i)look\s+at\s+the\s+book")
    hit = first_unnegated(pat, "look at the book")
    assert hit is not None and hit.group(0) == "look at the book"
    assert first_unnegated(pat, "no need to look at the book") is None
    assert first_unnegated(pat, "why did you look at the book") is None
    assert first_unnegated(pat, "I shouldn't look at the book") is None
    assert first_unnegated(pat, "") is None
    # A negation in an earlier sentence does not carry over to a new request.
    later = first_unnegated(pat, "no need to rush. look at the book")
    assert later is not None and later.group(0) == "look at the book"
    # The second hit counts when only the first one is declined.
    both = first_unnegated(pat, "no need to look at the book. then look at the book")
    assert both is not None and both.start() > 20


