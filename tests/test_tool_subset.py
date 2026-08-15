"""Research-mode and everyday skill-card tool schema filtering."""

from __future__ import annotations

from arelis.core.tool_subset import (
    ALWAYS_ON_TOOLS,
    RESEARCH_TOOL_ALLOWLIST,
    filter_tool_names,
    is_research_mode,
    should_apply_research_subset,
)


def test_research_role_is_research_mode() -> None:
    assert is_research_mode("research", "hello")
    assert not is_research_mode("fast", "hello")
    assert is_research_mode("fast", "please investigate the outage thoroughly")


def test_subset_shrinks_research_turn() -> None:
    available = set(RESEARCH_TOOL_ALLOWLIST) | {
        "send_sms",
        "image",
        "workspace",
        "agenda",
    }
    visible = filter_tool_names(
        available,
        role="research",
        text="Investigate the latest fusion milestones and write a report",
        enabled=True,
    )
    assert "research_report" in visible
    assert "web_search" in visible
    assert "send_sms" not in visible
    assert "image" not in visible


def test_sms_ask_keeps_full_surface() -> None:
    available = set(RESEARCH_TOOL_ALLOWLIST) | {"send_sms", "contacts"}
    assert not should_apply_research_subset(
        "research", "text Brian that I am late"
    )
    visible = filter_tool_names(
        available,
        role="research",
        text="text Brian that I am late",
        enabled=True,
    )
    assert "send_sms" in visible
    assert "contacts" in visible


def test_agenda_mention_adds_agenda() -> None:
    available = set(RESEARCH_TOOL_ALLOWLIST) | {"agenda", "send_sms"}
    visible = filter_tool_names(
        available,
        role="research",
        text="Deep dive the budget AND what's on my calendar tomorrow",
        enabled=True,
    )
    assert "agenda" in visible
    assert "send_sms" not in visible


_EVERYDAY = set(RESEARCH_TOOL_ALLOWLIST) | {
    "send_sms",
    "inbound_sms",
    "contacts",
    "inbox",
    "send_email",
    "image",
    "vision",
    "camera",
    "browser",
    "workspace",
    "git_info",
    "analyze",
    "doc_extract",
    "agenda",
    "memory",
    "tasks",
    "goals",
    "ocr",
}


def test_weather_turn_hides_sends_and_image() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="What's the weather today?",
        enabled=True,
        skill_subset=True,
    )
    assert "weather" in visible
    assert "user_location" in visible
    assert ALWAYS_ON_TOOLS <= visible
    assert "send_sms" not in visible
    assert "image" not in visible
    assert "browser" not in visible
    assert "web_search" not in visible


def test_unmatched_chat_fails_open_without_sends() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="Thanks, that's all for now.",
        enabled=True,
        skill_subset=True,
    )
    assert "weather" in visible
    assert "calculator" in visible
    assert "send_sms" not in visible
    assert "send_email" not in visible


def test_how_are_you_today_does_not_offer_sms() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="how are you today?",
        enabled=True,
        skill_subset=True,
    )
    assert "send_sms" not in visible
    assert "send_email" not in visible


def test_sms_everyday_keeps_full_surface() -> None:
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


def test_skill_subset_off_keeps_full_on_fast() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="What's the weather today?",
        enabled=True,
        skill_subset=False,
    )
    assert visible == _EVERYDAY


def test_git_status_offers_git_info_not_sms() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="What's the git status of this project?",
        enabled=True,
        skill_subset=True,
    )
    assert "git_info" in visible
    assert "workspace" in visible
    assert "send_sms" not in visible
    assert "image" not in visible


def test_inbox_ask_offers_mail_not_image() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="What's in my inbox from Alice?",
        enabled=True,
        skill_subset=True,
    )
    assert "inbox" in visible
    assert "send_email" in visible
    assert "image" not in visible
    assert "browser" not in visible


def test_contacts_lookup_offers_contacts() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="Who is my wife in my contacts?",
        enabled=True,
        skill_subset=True,
    )
    assert "contacts" in visible


def test_unmatched_wh_question_keeps_local_tools() -> None:
    """The web fallback is a floor on the prompt, not a menu.

    Measured on qwen2.5:7b before this: these three turns were offered only
    calculator/scrape/web_fetch/web_search, so "read arelis/core/tool_subset.py"
    went to web_fetch three times out of three and the other two never called a
    tool at all.
    """
    for text, wanted in (
        ("read arelis/core/tool_subset.py and tell me what it does", "workspace"),
        ("what changed in the repo since yesterday?", "git_info"),
        ("where do you think I am?", "user_location"),
    ):
        visible = filter_tool_names(
            _EVERYDAY | {"user_location"},
            role="fast",
            text=text,
            enabled=True,
            skill_subset=True,
        )
        assert wanted in visible, f"{wanted} hidden for {text!r}: {sorted(visible)}"


def test_web_fallback_still_offers_search_for_vague_currency() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="what is the latest on the Artemis program?",
        enabled=True,
        skill_subset=True,
    )
    assert "web_search" in visible
    assert "send_sms" not in visible


def test_ocr_screenshot_hides_sms() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="read the text in this screenshot",
        enabled=True,
        skill_subset=True,
    )
    assert "ocr" in visible
    assert "send_sms" not in visible
    assert "image" not in visible


def test_a_location_ask_narrows_instead_of_failing_open() -> None:
    """No card meant the whole registry, and that is not free.

    Measured on qwen2.5:7b: with no location card these asks took the web
    fallback, which fails open by design, so the turn carried 26 tool schemas,
    a ~35s cold prefill, and came back as prose. With the card the surface is
    three tools and user_location is called 3/3 at ~1.2s.
    """
    for text in (
        "where do you think I am?",
        "where am I?",
        "what city am I in?",
        "what timezone am I in?",
    ):
        visible = filter_tool_names(
            _EVERYDAY,
            role="fast",
            text=text,
            enabled=True,
            skill_subset=True,
        )
        assert "user_location" in visible, text
        assert "send_sms" not in visible, text
        assert len(visible) < 8, f"{text} offered {sorted(visible)}"


def test_the_location_card_does_not_swallow_weather_or_web() -> None:
    weather = filter_tool_names(
        _EVERYDAY, role="fast", text="weather tomorrow please", enabled=True,
        skill_subset=True,
    )
    assert "weather" in weather

    web = filter_tool_names(
        _EVERYDAY, role="fast", text="search the web for f1 results", enabled=True,
        skill_subset=True,
    )
    assert "web_search" in web
