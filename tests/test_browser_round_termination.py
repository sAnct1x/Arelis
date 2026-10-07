"""Removing ``browser_ok`` from the tool-disabling condition must not loop.

After a successful browser call tools stay on for the next round, so a model
that answers in plain text has to end the turn there, and a model that keeps
calling the browser has to be stopped by ``max_rounds``, not run forever.
"""

from __future__ import annotations

import asyncio

import pytest

from arelis.eval import harness
from arelis.eval.harness import run_scripted_scenario
from arelis.eval.scenarios import Scenario, _tool_call


@pytest.fixture
def stream_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count how many model rounds the scripted router is asked for."""
    calls: list[int] = []
    original = harness._ScriptedRouter.stream

    async def counting(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(self.i)
        async for item in original(self, *args, **kwargs):
            yield item

    monkeypatch.setattr(harness._ScriptedRouter, "stream", counting)
    return calls


def test_open_site_then_plain_answer_ends_in_two_rounds(stream_calls: list[int]) -> None:
    scenario = Scenario(
        id="t_open_site_terminates",
        user="open x.com",
        expect_tools=("browser",),
        script=[
            [("token", "Opened x.com for you.")],
            [("token", "Opened x.com for you.")],
        ],
    )
    result = asyncio.run(run_scripted_scenario(scenario))
    assert result.ok, result.reasons
    assert result.tools_called == ["browser"]
    assert result.final_text.strip()
    assert len(stream_calls) <= 2, f"model asked {len(stream_calls)} times"


def test_a_model_that_keeps_calling_browser_is_bounded(stream_calls: list[int]) -> None:
    call = _tool_call("browser", {"action": "read"})
    scenario = Scenario(
        id="t_browser_runaway_bounded",
        user="open x.com",
        expect_tools=("browser",),
        script=[[("tool_calls", [call])] for _ in range(20)],
    )
    asyncio.run(run_scripted_scenario(scenario))
    # run_scripted_scenario pins max_rounds at 6.
    assert len(stream_calls) <= 7, f"model asked {len(stream_calls)} times"
