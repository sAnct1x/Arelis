"""Mid-turn escalate decision (Wave 2)."""

from __future__ import annotations

import pytest

from arelis.core.agent_loop import decide_mid_turn_escalate
from arelis.eval.harness import run_scripted_scenario
from arelis.eval.scenarios import SCENARIOS


def test_escalate_to_research_when_expected_tools_missing() -> None:
    target = decide_mid_turn_escalate(
        role="fast",
        text="look up the latest battery recycling news",
        round_i=3,
        expected={"web_search", "scrape"},
        tools_used=set(),
        already_escalated=False,
        escalate_after_rounds=2,
    )
    assert target == "research"


def test_no_escalate_on_file_shaped_ask() -> None:
    target = decide_mid_turn_escalate(
        role="fast",
        text="please edit the python file and fix the lint",
        round_i=3,
        expected={"workspace"},
        tools_used=set(),
        already_escalated=False,
    )
    assert target is None


def test_escalate_write_a_report_goes_research_not_code() -> None:
    target = decide_mid_turn_escalate(
        role="fast",
        text="Investigate recent lithium battery recycling and write a report",
        round_i=3,
        expected={"research_report"},
        tools_used=set(),
        already_escalated=False,
    )
    assert target == "research"


def test_no_escalate_before_threshold() -> None:
    assert (
        decide_mid_turn_escalate(
            role="fast",
            text="search for fusion news",
            round_i=2,
            expected={"web_search"},
            tools_used=set(),
            already_escalated=False,
            escalate_after_rounds=2,
        )
        is None
    )


def test_no_escalate_when_expected_tool_ran() -> None:
    assert (
        decide_mid_turn_escalate(
            role="fast",
            text="search for fusion news",
            round_i=4,
            expected={"web_search"},
            tools_used={"web_search"},
            already_escalated=False,
        )
        is None
    )


def test_no_escalate_on_agenda_calendar_ask() -> None:
    """Regression: hardcoded is_research_mode('research') made every turn escalate."""
    assert (
        decide_mid_turn_escalate(
            role="fast",
            text="update my agenda for tomorrow, add a calendar event at 4pm",
            round_i=5,
            expected=set(),
            tools_used=set(),
            already_escalated=False,
        )
        is None
    )


def test_no_escalate_on_outbound_sms() -> None:
    assert (
        decide_mid_turn_escalate(
            role="fast",
            text="text mom that I'm late",
            round_i=5,
            expected={"send_sms"},
            tools_used=set(),
            already_escalated=False,
        )
        is None
    )


def test_no_escalate_when_disabled_or_already() -> None:
    assert (
        decide_mid_turn_escalate(
            role="fast",
            text="deep dive on batteries",
            round_i=5,
            expected={"web_search"},
            tools_used=set(),
            already_escalated=True,
        )
        is None
    )
    assert (
        decide_mid_turn_escalate(
            role="fast",
            text="deep dive on batteries",
            round_i=5,
            expected={"web_search"},
            tools_used=set(),
            already_escalated=False,
            enabled=False,
        )
        is None
    )


@pytest.mark.asyncio
async def test_offline_mid_turn_escalate_emits_model_switch() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "mid_turn_escalate_research")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert any(
        sw.get("reason") == "mid_turn_escalate" and sw.get("role") == "research"
        for sw in result.model_switches
    )


def test_no_escalate_on_analyze_json_file() -> None:
    assert (
        decide_mid_turn_escalate(
            role="fast",
            text="analyze this file attached and give me a brief summary",
            round_i=5,
            expected={"analyze", "send_email"},
            tools_used={"user_location"},
            already_escalated=False,
        )
        is None
    )
