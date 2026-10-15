"""What a turn is about, and that every governed tool is named.

``select_skill_ids`` is an intent classifier. It does not decide which rules
reach the prompt — the compact policy names every tool, every turn — but
tool_subset, plan_nudge and lessons all ask it what the turn is about, so
its answers still matter.
"""

from __future__ import annotations

from arelis.core.skills import (
    SKILL_CARDS,
    select_skill_ids,
)


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


