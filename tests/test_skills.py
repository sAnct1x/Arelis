"""What a turn is about, and that every governed tool is named.

``select_skill_ids`` is an intent classifier. It does not decide which rules
reach the prompt — the compact policy names every tool, every turn — but
tool_subset, plan_nudge and lessons all ask it what the turn is about, so
its answers still matter.
"""

from __future__ import annotations

from arelis.core.agent_loop import TOOL_POLICY
from arelis.core.skills import (
    SKILL_CARDS,
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


def test_who_are_you_is_not_web_fallback() -> None:
    tools = {"web_search", "scrape", "web_fetch", "workspace"}
    ids, fallback = select_skill_ids_detailed("who are you", available_tools=tools)
    assert "web" not in ids
    assert fallback is False


def test_who_is_this_is_fallback_only_not_a_web_card() -> None:
    """A fighter on TV is not 'who are you'. Floor to web, but mark it fallback."""
    tools = {"web_search", "scrape", "web_fetch", "workspace"}
    ids, fallback = select_skill_ids_detailed("Who is this", available_tools=tools)
    assert ids == ["web"]
    assert fallback is True


def test_every_tool_with_rules_has_them_shipped() -> None:
    """Cards stay authored; the prompt names each governed tool."""
    for card_id, card in SKILL_CARDS.items():
        assert card.body.strip(), f"{card_id} card is empty"
        tool = card.requires_tool
        if not tool:
            continue
        assert tool in TOOL_POLICY, f"{card_id} tool {tool} is not in the policy"


def test_a_card_names_the_tool_it_governs() -> None:
    """A card whose rules never mention its own tool cannot be followed."""
    for card_id, card in SKILL_CARDS.items():
        tool = card.requires_tool
        if not tool:
            continue
        assert tool in card.body, f"{card_id} card never mentions {tool}"


def test_weather_turn_selects_weather_card() -> None:
    ids = select_skill_ids(
        "What's the weather today?",
        available_tools={"weather", "web_search", "scrape"},
    )
    assert "weather" in ids


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


def test_keep_this_selects_workspace_not_memory() -> None:
    ids = select_skill_ids(
        "keep this: the spare key is under the planter",
        available_tools={"workspace", "memory", "recall"},
    )
    assert "workspace" in ids


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
    assert "action=dump" in SKILL_CARDS["science"].body
    assert "dump this state" in SKILL_CARDS["science"].hints


def test_diagnostics_card_in_catalog() -> None:
    assert "diagnostics" in SKILL_CARDS
    assert SKILL_CARDS["diagnostics"].requires_tool == "diagnostics"
    ids = select_skill_ids(
        "run diagnostics",
        available_tools={"diagnostics", "calculator", "send_sms"},
    )
    assert "diagnostics" in ids
    assert "sms" not in ids
    assert "diagnostics" not in select_skill_ids(
        "health check",
        available_tools={"diagnostics", "calculator", "send_sms"},
    )


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


def test_the_policy_is_built_from_every_card() -> None:
    from arelis.core.skills import full_tool_policy

    assert full_tool_policy() == TOOL_POLICY


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


def test_inspect_phrases_select_inspect_not_web_fallback() -> None:
    tools = {"workspace", "web_search", "scrape", "web_fetch"}
    for phrase in (
        "how do you confirm writes?",
        "how does my confirm gate work?",
        "how does confirm work",
        "where is the Drive strip?",
        "what's in policy.py?",
        "what does tool_subset do?",
        "show me the Drive strip",
        "how do you work",
        "read arelis/core/tool_subset.py and tell me what it does",
    ):
        ids, fallback = select_skill_ids_detailed(phrase, available_tools=tools)
        assert "inspect" in ids or "workspace" in ids, phrase
        assert fallback is False, phrase


def test_source_inspect_asks_are_not_fallback_only_web() -> None:
    tools = {"workspace", "web_search", "scrape", "web_fetch"}
    for phrase in (
        "read arelis/core/tool_subset.py and tell me what it does",
        "what's in policy.py?",
        "where is the Drive strip?",
    ):
        ids, fallback = select_skill_ids_detailed(phrase, available_tools=tools)
        assert fallback is False, phrase
        assert ids != ["web"], phrase


def test_toroids_physics_is_not_inspect() -> None:
    ids = select_skill_ids(
        "how do toroids relate to physics?",
        available_tools={"workspace", "cas", "web_search"},
    )
    assert "inspect" not in ids


def test_fix_your_confirm_gate_does_not_select_inspect() -> None:
    ids = select_skill_ids(
        "fix your confirm gate",
        available_tools={"workspace", "web_search"},
    )
    assert "inspect" not in ids


def test_source_and_confirm_mentions_without_a_read_are_not_inspect() -> None:
    tools = {"workspace", "web_search", "scrape", "web_fetch"}
    for phrase in (
        "cite your source",
        "what's your source for that weather number",
        "the confirm gate paused that write",
        "don't mention the confirm gate",
        "email me docs/architecture.md",
        "email me policy.py",
    ):
        ids = select_skill_ids(phrase, available_tools=tools)
        assert "inspect" not in ids, phrase


def test_inspect_and_workspace_cards_quote_the_catalog_path_map() -> None:
    from arelis.core.intent_catalog import inspect_path_guide

    guide = inspect_path_guide()
    assert guide in SKILL_CARDS["inspect"].body
    assert guide in SKILL_CARDS["workspace"].body
