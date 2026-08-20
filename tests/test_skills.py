"""Skill-card selection and full policy export."""

from __future__ import annotations

from arelis.core.agent_loop import TOOL_POLICY
from arelis.core.skills import (
    SKILL_CARDS,
    assemble_tool_policy,
    select_skill_ids,
    select_skill_ids_detailed,
)


def test_web_fallback_reports_itself() -> None:
    """A matched web card and the unmatched fallback must be distinguishable.

    tool_subset needs the difference: the fallback means "nothing matched", and
    hiding every local tool on that basis is what sent a local file path to
    web_fetch.
    """
    tools = {"web_search", "scrape", "web_fetch", "workspace", "git_info"}
    ids, fallback = select_skill_ids_detailed(
        "what changed in the repo since yesterday?", available_tools=tools
    )
    assert ids == ["web"]
    assert fallback is True

    ids, fallback = select_skill_ids_detailed(
        "search the web for the Artemis launch date", available_tools=tools
    )
    assert "web" in ids
    assert fallback is False


def test_clock_ask_does_not_take_the_web_fallback() -> None:
    tools = {"web_search", "scrape", "web_fetch", "workspace"}
    ids, fallback = select_skill_ids_detailed(
        "what time is it", available_tools=tools
    )
    assert "web" not in ids
    assert fallback is False


def test_full_policy_keeps_legacy_assertions() -> None:
    assert "Prefer scrape" in TOOL_POLICY or "prefer scrape" in TOOL_POLICY.lower()
    assert "web_search first" in TOOL_POLICY
    assert "weather tool" in TOOL_POLICY.lower()
    assert "send_sms" in TOOL_POLICY
    assert "memory tool" in TOOL_POLICY
    assert "recall" in TOOL_POLICY
    assert "analyze" in TOOL_POLICY.lower()


def test_weather_turn_selects_weather_card() -> None:
    ids = select_skill_ids(
        "What's the weather today?",
        available_tools={"weather", "web_search", "scrape"},
    )
    assert "weather" in ids
    policy = assemble_tool_policy(
        "What's the weather today?",
        available_tools={"weather", "web_search", "scrape"},
    )
    assert "Weather" in policy or "weather tool" in policy.lower()
    assert len(policy) < len(TOOL_POLICY)


def test_sms_turn_selects_sms_card() -> None:
    ids = select_skill_ids(
        "Text Brian: I'm late",
        available_tools={"send_sms", "contacts", "weather"},
    )
    assert "sms" in ids


def test_inbound_sms_ask_selects_sms_card() -> None:
    ids = select_skill_ids(
        "Did Brian text? What did they reply?",
        available_tools={"inbound_sms", "web_search"},
    )
    assert "sms" in ids
    # send_sms missing is fine — inbound_sms fallthrough keeps the card.
    assert "sms" in select_skill_ids(
        "what did they reply",
        available_tools={"inbound_sms"},
    )


def test_recall_ask_selects_memory_card() -> None:
    ids = select_skill_ids(
        "What did I say about the optics run?",
        available_tools={"recall", "memory", "web_search"},
    )
    assert "memory" in ids
    assert "memory" in select_skill_ids(
        "Do you remember my preferred coffee?",
        available_tools={"recall"},
    )


def test_analyze_ask_selects_analyze_card() -> None:
    ids = select_skill_ids(
        "Summarize data in reports/sales.csv",
        available_tools={"analyze", "workspace", "web_search"},
    )
    assert "analyze" in ids
    for phrase in (
        "open the spreadsheet and summarize",
        "describe this excel table",
        "what's in the dataframe",
        "head of data/export.tsv",
    ):
        assert "analyze" in select_skill_ids(
            phrase, available_tools={"analyze", "workspace"}
        )


def test_analyze_skipped_without_tool() -> None:
    ids = select_skill_ids(
        "Summarize the csv spreadsheet",
        available_tools={"workspace", "web_search"},
    )
    assert "analyze" not in ids


def test_max_cards_cap() -> None:
    # Many overlapping hints must still respect max_cards.
    ids = select_skill_ids(
        "search the news, text Brian, recall what I said, analyze sales.csv table",
        available_tools={
            "web_search",
            "scrape",
            "send_sms",
            "inbound_sms",
            "recall",
            "analyze",
            "weather",
        },
        max_cards=4,
    )
    assert len(ids) <= 4
    assert len(ids) == len(set(ids))


def test_analyze_card_in_catalog() -> None:
    assert "analyze" in SKILL_CARDS
    assert SKILL_CARDS["analyze"].requires_tool == "analyze"


def test_science_card_in_catalog() -> None:
    assert "science" in SKILL_CARDS
    assert SKILL_CARDS["science"].requires_tool == "cas"
    ids = select_skill_ids(
        "what is the integral of x squared sin x",
        available_tools={"cas", "units", "calculator", "send_sms"},
    )
    assert "science" in ids
    assert "sms" not in ids


def test_document_card_in_catalog() -> None:
    assert "document" in SKILL_CARDS
    assert SKILL_CARDS["document"].requires_tool == "document"
    ids = select_skill_ids(
        "create a pdf about the dirac equation",
        available_tools={"document", "doc_extract", "calculator", "send_sms"},
    )
    assert "document" in ids
    assert "docs" not in ids
    assert "sms" not in ids
    leaned = select_skill_ids(
        "how's the weather",
        available_tools={"document", "workspace", "weather"},
        extra_ids=("workspace", "document"),
    )
    assert leaned[0] in {"workspace", "document"}
    assert "document" in leaned
    assert "workspace" in leaned
    conv = select_skill_ids(
        "convert 5 ft 8 in to meters",
        available_tools={"cas", "units", "calculator", "weather"},
    )
    assert "science" in conv
    assert "weather" not in conv
    units_only = select_skill_ids(
        "convert 5 ft 8 in to meters",
        available_tools={"units", "calculator"},
    )
    assert "science" in units_only
    sms = select_skill_ids(
        "Text Brian: I'm late",
        available_tools={"send_sms", "cas", "units"},
    )
    assert "sms" in sms
    assert "science" not in sms
    weather = select_skill_ids(
        "What's the weather today?",
        available_tools={"weather", "cas", "units"},
    )
    assert "weather" in weather
    assert "science" not in weather
    plot = select_skill_ids(
        "fit a line and plot residuals",
        available_tools={"cas", "units", "plot", "calculator"},
    )
    assert "science" in plot
    arxiv = select_skill_ids(
        "search arxiv for gravitational waves",
        available_tools={"cas", "units", "catalog", "calculator"},
    )
    assert "science" in arxiv


def test_calendar_ask_selects_agenda_not_schedule_jobs() -> None:
    ids = select_skill_ids(
        "Delete that calendar event on Google",
        available_tools={"agenda", "schedule", "briefing"},
    )
    assert "agenda" in ids
    assert "schedule" not in ids or ids.index("agenda") < ids.index("schedule")


def test_calendar_reminder_to_text_selects_agenda() -> None:
    ids = select_skill_ids(
        "create a calendar event for tomorrow at 4pm as a reminder to text my wife",
        available_tools={"agenda", "schedule", "send_sms", "web_search"},
    )
    assert "agenda" in ids
    assert ids.index("agenda") == 0 or ids[0] == "agenda" or (
        "sms" in ids and ids.index("agenda") < ids.index("sms")
    )


def test_reservation_ask_selects_browser_card() -> None:
    ids = select_skill_ids(
        "Book a table at The Inn on OpenTable",
        available_tools={"browser", "web_search", "agenda"},
    )
    assert "browser" in ids


def test_sign_in_ask_selects_browser_card() -> None:
    ids = select_skill_ids(
        "go to sign in",
        available_tools={"browser", "web_search", "send_sms"},
    )
    assert "browser" in ids
    assert "sms" not in ids


def test_force_all_matches_export() -> None:
    assert assemble_tool_policy(force_all=True) == TOOL_POLICY


def test_ocr_text_does_not_select_sms() -> None:
    ids = select_skill_ids(
        "read the text in this screenshot",
        available_tools={"ocr", "send_sms", "workspace", "vision"},
    )
    assert "ocr" in ids
    assert "sms" not in ids


def test_deadline_paraphrase_she_owe() -> None:
    ids = select_skill_ids(
        "what's she owe",
        available_tools={"tasks", "agenda", "web_search"},
    )
    assert "deadline" in ids


def test_summarize_the_readme_selects_workspace() -> None:
    ids = select_skill_ids(
        "summarize the readme",
        available_tools={"workspace", "web_search", "send_sms"},
    )
    assert "workspace" in ids
