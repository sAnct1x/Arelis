"""One intent catalog drives preflight, schema subset, and exactness."""

from __future__ import annotations

from arelis.core.claims import detect_exactness_need, detect_inbox_ask
from arelis.core.intent_catalog import (
    COMPOSE_EMAIL,
    INBOX,
    SMS_SEND,
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
        text="Thanks, that's all for now.",
        enabled=True,
        skill_subset=True,
    )
    assert "calculator" in visible
    assert "send_sms" not in visible
    assert "send_email" not in visible


def test_research_extras_add_inbox_on_deep_dive() -> None:
    extra = research_extras_for_text(
        "Deep dive the budget and check my inbox"
    )
    assert "inbox" in extra
    assert "send_email" in extra
