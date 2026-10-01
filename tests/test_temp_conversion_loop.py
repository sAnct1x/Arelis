"""End-to-end regression test for temperature conversion with agent loop.

Tests the actual agent behavior with the scripted router to ensure that
temperature conversions work correctly even if the model calls units with
the wrong action.
"""

from __future__ import annotations

import asyncio

from arelis.config import shipped_num_ctx
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.eval.harness import _ScriptedRouter
from arelis.tools.base import ToolRegistry
from arelis.tools.calculator import CalculatorTool
from arelis.tools.units import UnitsTool


def _real_tools_registry() -> ToolRegistry:
    """Registry with real units and calculator tools (not stubs)."""
    reg = ToolRegistry()
    reg.register(UnitsTool())
    reg.register(CalculatorTool())
    return reg


async def _run_agent_with_script(script: list[list[tuple[str, any]]]) -> tuple[str, list[tuple[str, bool]]]:
    """Run agent loop with script and return final answer + tool results."""
    router = _ScriptedRouter(script)
    tools = _real_tools_registry()
    bus = EventBus()
    memory = SessionMemory()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    for et in (EventType.TOOL_START, EventType.TOOL_RESULT, EventType.ASSISTANT_DONE):
        bus.subscribe(et, capture)

    agent_cfg = {
        "max_rounds": 6,
        "exactness": True,
        "numeric_gate": True,
        "evidence_gate": True,
    }

    loop = AgentLoop(
        bus,
        router,
        tools,
        memory,
        persona="You are Arelis under eval.",
        config={
            "agent": agent_cfg,
            "ollama": {"num_ctx": shipped_num_ctx()},
        },
        request_confirm=lambda *args, **kwargs: "allow",
        is_cancelled=lambda: False,
    )

    bus_task = asyncio.create_task(bus.run())
    try:
        await loop.run("Convert 90 degrees Fahrenheit to Celsius.", "fast", source="eval")
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass

    # Extract results
    tool_results = [(e.payload.get('tool', '?'), e.payload.get('ok', False))
                    for e in events if e.type == EventType.TOOL_RESULT]
    done = next((e for e in events if e.type == EventType.ASSISTANT_DONE), None)
    final_text = str((done.payload.get("text") if done else "") or "")

    return final_text, tool_results


def test_temperature_conversion_loop_with_correct_action() -> None:
    """Temperature conversion should work when model uses correct action."""
    script = [
        [("tool_calls", [{"type": "function", "function": {"name": "units",
                                                            "arguments": {"action": "convert",
                                                                         "quantity": "90 degrees Fahrenheit",
                                                                         "to": "Celsius"}}}])],
        [("token", "That's about 32 degrees Celsius.")],
    ]

    final_text, tool_results = asyncio.run(_run_agent_with_script(script))

    # Should have one successful units call
    assert len(tool_results) == 1, f"Expected 1 tool call, got {len(tool_results)}"
    assert tool_results[0] == ("units", True), f"Expected units ok=True, got {tool_results[0]}"

    # Should not contain refusal message
    assert "couldn't convert" not in final_text.lower(), f"Got refusal: {final_text}"
    assert "codata" not in final_text.lower(), f"Got refusal: {final_text}"

    # Should contain conversion result
    assert "32" in final_text, f"Missing conversion result in: {final_text}"


def test_temperature_conversion_loop_with_wrong_action_recovers() -> None:
    """Temperature conversion should recover even if model uses wrong action.

    This tests the reported bug: model calls units with action='constant' for
    a temperature conversion. The units tool should fall back to conversion.
    """
    # Model incorrectly calls with action="constant" but provides full conversion string
    script = [
        [("tool_calls", [{"type": "function", "function": {"name": "units",
                                                            "arguments": {"action": "constant",
                                                                         "name": "90 degrees Fahrenheit to Celsius"}}}])],
        [("token", "That's about 32 degrees Celsius.")],
    ]

    final_text, tool_results = asyncio.run(_run_agent_with_script(script))

    # Should have one successful units call (fallback worked!)
    assert len(tool_results) == 1, f"Expected 1 tool call, got {len(tool_results)}"
    assert tool_results[0] == ("units", True), f"Expected units ok=True after fallback, got {tool_results[0]}"

    # Should not contain refusal message
    assert "couldn't convert" not in final_text.lower(), f"Got refusal despite fallback: {final_text}"
    assert "codata" not in final_text.lower(), f"Got refusal despite fallback: {final_text}"

    # Should contain conversion result
    assert "32" in final_text, f"Missing conversion result in: {final_text}"
