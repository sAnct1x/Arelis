"""Regression test for browser + vision chaining.

Ensures that a browser screenshot doesn't disable tools in subsequent rounds,
allowing vision to analyze the screenshot. This was broken in refactor-eval-fixes
when ctx.browser_ok was added to the tool-disabling condition.
"""

import asyncio

from arelis.eval.harness import run_scripted_scenario
from arelis.eval.scenarios import SCENARIOS


def test_browser_screenshot_enables_vision_followup():
    """Browser screenshot should not disable tools; vision should be called."""
    scenario = next(
        s for s in SCENARIOS if s.id == "browser_screenshot_then_vision"
    )
    result = asyncio.run(run_scripted_scenario(scenario))

    assert result.ok, f"Scenario failed: {result}"
    # Must call both browser and vision
    assert "browser" in result.tools_called, (
        f"browser not called; tools_called={result.tools_called}"
    )
    assert "vision" in result.tools_called, (
        f"vision not called after browser screenshot; "
        f"tools_called={result.tools_called}"
    )
