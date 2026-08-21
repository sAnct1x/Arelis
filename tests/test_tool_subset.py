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
    "cas",
    "units",
    "plot",
    "document",
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
    assert "plot" not in ALWAYS_ON_TOOLS
    assert "plot" not in visible
    assert "catalog" not in visible
    assert "send_sms" not in visible
    assert "image" not in visible
    assert "browser" not in visible
    assert "web_search" not in visible


def test_chart_ask_offers_plot_not_sms() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="fit a line and plot residuals",
        enabled=True,
        skill_subset=True,
    )
    assert "plot" in visible
    assert "send_sms" not in visible


def test_create_pdf_offers_document_not_extract() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="create a pdf about the dirac equation",
        enabled=True,
        skill_subset=True,
    )
    assert "document" in visible
    assert "doc_extract" not in visible
    assert "send_sms" not in visible


def test_arxiv_ask_offers_catalog_not_sms() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="search arxiv for gravitational waves",
        enabled=True,
        skill_subset=True,
    )
    assert "catalog" in visible
    assert "send_sms" not in visible


def test_research_plot_ask_adds_plot_via_extra() -> None:
    available = set(RESEARCH_TOOL_ALLOWLIST) | {"plot", "send_sms"}
    visible = filter_tool_names(
        available,
        role="research",
        text="fit a line and plot residuals",
        enabled=True,
    )
    assert "plot" in visible
    assert "send_sms" not in visible


def test_research_create_pdf_adds_document_via_extra() -> None:
    available = set(RESEARCH_TOOL_ALLOWLIST) | {"document", "doc_extract", "send_sms"}
    visible = filter_tool_names(
        available,
        role="research",
        text="create a pdf about the dirac equation",
        enabled=True,
    )
    assert "document" in visible
    assert "doc_extract" not in visible
    assert "send_sms" not in visible


def test_writing_room_lean_offers_document_in_research_mode() -> None:
    available = set(RESEARCH_TOOL_ALLOWLIST) | {
        "document",
        "workspace",
        "git_info",
        "send_sms",
    }
    visible = filter_tool_names(
        available,
        role="research",
        text="how's the draft going",
        extra_skill_ids=("workspace", "document"),
    )
    assert "document" in visible
    assert "workspace" in visible
    assert "send_sms" not in visible


def test_unmatched_chat_fails_open_without_sends() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="how do I tie a necktie",
        enabled=True,
        skill_subset=True,
    )
    assert "weather" in visible
    assert "calculator" in visible
    assert "send_sms" not in visible
    assert "send_email" not in visible


def test_room_lean_does_not_cage_unmatched_chat() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="how do I tie a necktie",
        extra_skill_ids=("workspace", "document"),
    )
    assert "weather" in visible
    assert "document" in visible


def test_clock_ask_does_not_load_the_full_surface() -> None:
    """now_line already has the time. Web fallback used to fail-open ~26 schemas."""
    for text in (
        "what time is it",
        "what's the time",
        "hello",
        "Thanks!",
    ):
        visible = filter_tool_names(
            _EVERYDAY,
            role="fast",
            text=text,
            enabled=True,
            skill_subset=True,
        )
        assert "web_search" not in visible, text
        assert "weather" not in visible, text
        assert "send_sms" not in visible, text
        assert len(visible) <= len(ALWAYS_ON_TOOLS) + 1, f"{text} offered {sorted(visible)}"


def test_clock_in_another_city_still_fail_opens() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="what time is it in Tokyo",
        enabled=True,
        skill_subset=True,
    )
    assert "web_search" in visible or "weather" in visible or "user_location" in visible


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


def test_email_followup_keeps_send_email() -> None:
    history = [
        {"role": "user", "content": "make a pdf about solitons"},
        {"role": "assistant", "content": "Wrote outputs/documents/solitons.pdf"},
        {"role": "user", "content": "email the pdf to me"},
        {"role": "assistant", "content": "I do not have a send_email tool."},
    ]
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="you have my email, it's me@example.com",
        enabled=True,
        skill_subset=True,
        history=history,
    )
    assert "send_email" in visible
    again = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="email the pdf to me@example.com",
        enabled=True,
        skill_subset=True,
        history=history,
    )
    assert "send_email" in again


def test_delete_mail_does_not_keep_send_email() -> None:
    visible = filter_tool_names(
        _EVERYDAY,
        role="fast",
        text="delete the email from Claude",
        enabled=True,
        skill_subset=True,
    )
    assert "inbox" in visible
    assert "send_email" not in visible
