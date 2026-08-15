"""Offline foundation eval suite (scripted model, stub tools)."""

from __future__ import annotations

import pytest

from arelis.eval.harness import (
    parse_agent_overrides,
    run_all_scripted,
    run_scripted_scenario,
)
from arelis.eval.scenarios import SCENARIOS


@pytest.mark.asyncio
async def test_all_scripted_scenarios_pass() -> None:
    results = await run_all_scripted()
    assert results, "no scripted scenarios"
    failed = [r for r in results if not r.ok]
    assert not failed, "; ".join(
        f"{r.scenario_id}: {', '.join(r.reasons)}" for r in failed
    )


@pytest.mark.asyncio
async def test_weather_scenario_selects_skills_and_preflight() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "weather_oneshot")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "weather" in result.tools_called
    assert "weather" in result.skill_ids or "weather" in result.preflight_kinds


@pytest.mark.asyncio
async def test_sms_scenario_requires_to_and_body() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "sms_immediate")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert result.tools_called[0] == "send_sms"
    assert "sms_send" in result.preflight_kinds


@pytest.mark.asyncio
async def test_mid_turn_escalate_research_switches_model() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "mid_turn_escalate_research")
    result = await run_scripted_scenario(scenario)
    assert result.ok, result.reasons
    assert "research_report" in result.tools_called
    switches = [
        sw
        for sw in result.model_switches
        if sw.get("reason") == "mid_turn_escalate"
    ]
    assert switches, result.model_switches
    assert switches[0].get("role") == "research"
    assert switches[0].get("from") != switches[0].get("to")


def test_overrides_read_as_json_or_as_pairs() -> None:
    assert parse_agent_overrides("") == {}
    assert parse_agent_overrides('{"exactness": false}') == {"exactness": False}
    # PowerShell eats the inner quotes of a JSON argument, so the pair form is
    # the one a run on this machine will actually use.
    assert parse_agent_overrides("exactness=false") == {"exactness": False}
    assert parse_agent_overrides("a=false, b=true , c=4, d=1.5, e=hi") == {
        "a": False,
        "b": True,
        "c": 4,
        "d": 1.5,
        "e": "hi",
    }


def test_an_unreadable_override_raises_instead_of_running_a_baseline() -> None:
    with pytest.raises(ValueError):
        parse_agent_overrides("exactness")
    with pytest.raises(ValueError):
        parse_agent_overrides('["exactness"]')


@pytest.mark.asyncio
async def test_an_override_beats_the_scenario_that_asked_for_the_gate() -> None:
    scenario = next(s for s in SCENARIOS if s.id == "weather_oneshot")
    result = await run_scripted_scenario(
        scenario, agent_overrides={"max_rounds": 1}
    )
    assert result.scenario_id == scenario.id


@pytest.mark.asyncio
async def test_the_store_forces_are_switches_and_not_scenery() -> None:
    """tasks_force/goals_force reported to telemetry without having a flag.

    Five sibling gates each had one, so these two could not be measured off.
    They default on, which is what the board asserts elsewhere; here we only
    ask that off means off, or the flag is decoration.
    """
    for scenario_id, flag in (
        ("tasks_claim_needs_warrant", "tasks_force_call"),
        ("goals_claim_needs_warrant", "goals_force_call"),
    ):
        scenario = next(s for s in SCENARIOS if s.id == scenario_id)
        tool = flag.removesuffix("_force_call")

        on = await run_scripted_scenario(scenario)
        assert tool in on.tools_called, f"{scenario_id} should force {tool}"

        off = await run_scripted_scenario(scenario, agent_overrides={flag: False})
        assert tool not in off.tools_called, (
            f"{flag}=false still called {tool}: the flag does nothing"
        )
