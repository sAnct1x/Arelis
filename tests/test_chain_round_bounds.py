"""The chain fixes keep tools on longer; neither may turn into a runaway loop."""

from __future__ import annotations

import asyncio

import pytest

from arelis.core.loop_helpers import round_limit_notice
from arelis.eval import harness
from arelis.eval.harness import run_scripted_scenario
from arelis.eval.scenarios import Scenario, _tool_call


@pytest.fixture
def model_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    seen: list[int] = []
    original = harness._ScriptedRouter.stream

    async def counting(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(self.i)
        async for item in original(self, *args, **kwargs):
            yield item

    monkeypatch.setattr(harness._ScriptedRouter, "stream", counting)
    return seen


def test_a_named_tool_the_model_never_calls_is_bounded_by_max_rounds(
    model_calls: list[int],
) -> None:
    """The ask names memory; the model keeps calling units. max_rounds ends it."""
    call = _tool_call("units", {"action": "convert", "quantity": "5 miles", "to": "km"})
    scenario = Scenario(
        id="t_owed_tool_never_called",
        user="Convert 5 miles to kilometers with units, then remember that result as my distance.",
        expect_tools=("units",),
        expect_tools_any=True,
        script=[[("tool_calls", [call])] for _ in range(20)],
    )
    asyncio.run(run_scripted_scenario(scenario))
    assert len(model_calls) <= 7, f"model asked {len(model_calls)} times"


def test_an_open_then_read_ask_ends_when_the_model_answers(model_calls: list[int]) -> None:
    scenario = Scenario(
        id="t_open_read_terminates",
        user="Use the browser to open https://example.com and tell me the heading on the page.",
        expect_tools=("browser",),
        script=[
            [("tool_calls", [_tool_call("browser", {"action": "open", "url": "https://example.com"})])],
            [("tool_calls", [_tool_call("browser", {"action": "read"})])],
            [("token", "The heading is Example Domain.")],
        ],
    )
    result = asyncio.run(run_scripted_scenario(scenario))
    assert result.ok, result.reasons
    assert result.tools_called == ["browser", "browser"]
    assert "example domain" in result.final_text.lower()
    assert len(model_calls) <= 4, f"model asked {len(model_calls)} times"


def test_round_limit_notice_includes_counts_and_last_fail() -> None:
    plain = round_limit_notice(8)
    assert "tool-step limit (8/8)" in plain
    assert "Last failing tool" not in plain

    with_fail = round_limit_notice(
        6,
        last_fail_tool="plot",
        last_fail_error='Missing xs. Use xs="1,2,3" (or an xs list) together with ys.',
    )
    assert "tool-step limit (6/6)" in with_fail
    assert "Last failing tool: plot:" in with_fail
    assert "Missing xs" in with_fail


def test_hitting_max_rounds_ships_counted_step_limit_with_last_fail() -> None:
    """Force-final fallback must name the budget and the last tool error."""
    call = _tool_call("plot", {"action": "line", "out": "x.png"})
    scenario = Scenario(
        id="t_round_limit_names_fail",
        user="Plot y = x^2 for x = 1..8 as a line chart.",
        expect_tools=("plot",),
        expect_tools_any=True,
        allow_no_tools=True,
        failing_tools=("plot",),
        agent_config={"max_rounds": 3, "exactness": False, "numeric_gate": False},
        script=[[("tool_calls", [call])] for _ in range(8)],
        offline_only=True,
    )
    result = asyncio.run(run_scripted_scenario(scenario))
    assert "tool-step limit (3/3)" in result.final_text
    assert "Last failing tool: plot:" in result.final_text
    assert "plot failed (eval stub)" in result.final_text
