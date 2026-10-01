"""The chain fixes keep tools on longer; neither may turn into a runaway loop."""

from __future__ import annotations

import asyncio

import pytest

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
