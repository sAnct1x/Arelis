"""Regression tests for loop bugs found by live matrix (2026-10-01).

Bug 1 (browser): browser_open_done_reply shortcut was ending turns too early
when the user asked to both open AND read/screenshot a page.

Bug 2 (chains): Tool stripping after first success was breaking multi-step
asks. Units/weather/calculator success stripped all tools on round 2, even
when the ask required multiple tools in sequence (chains).
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from arelis.config import shipped_num_ctx
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.eval.harness import _ScriptedRouter, foundation_registry
from arelis.tools.base import ToolRegistry


def _tools_registry(tools_list: list[str]) -> ToolRegistry:
    """The eval board's offline stubs, narrowed to the tools this ask offers.

    Real WeatherTool needs the network and MemoryTool needs a store; the bug is
    in the loop's routing, not in the tools, so stubs are the right layer.
    """
    full = foundation_registry()
    reg = ToolRegistry()
    for name in tools_list:
        tool = full.get(name)
        assert tool is not None, name
        reg.register(tool)
    return reg


async def _allow(*_args, **_kwargs) -> str:
    """request_confirm is awaited by the loop, so it must be a coroutine."""
    return "allow"


async def _run_agent_with_script(
    text: str,
    script: list[list[tuple[str, any]]],
    tools_list: list[str],
    agent_cfg: dict | None = None,
) -> tuple[str, list[tuple[str, bool]]]:
    """Run agent loop with script and return final answer + tool results."""
    router = _ScriptedRouter(script)
    tools = _tools_registry(tools_list)
    bus = EventBus()
    memory = SessionMemory()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    for et in (EventType.TOOL_START, EventType.TOOL_RESULT, EventType.ASSISTANT_DONE):
        bus.subscribe(et, capture)

    if agent_cfg is None:
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
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )

    bus_task = asyncio.create_task(bus.run())
    try:
        await loop.run(text, "fast", source="eval")
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass

    tool_results = [
        (e.payload.get("tool", "?"), e.payload.get("ok", False))
        for e in events
        if e.type == EventType.TOOL_RESULT
    ]
    done = next((e for e in events if e.type == EventType.ASSISTANT_DONE), None)
    final_text = str((done.payload.get("text") if done else "") or "")

    return final_text, tool_results


def test_weather_then_units_chain() -> None:
    """Weather then units conversion should run both tools (C22/P04 bug).

    Live matrix items C22 and P04 failed: weather ran, then units was
    stripped on round 2, and the answer was 'I don't know - this needs
    a units or constants result this turn'.
    """
    script = [
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "weather",
                            "arguments": {"place": "Springfield, Illinois", "days": 3},
                        },
                    }
                ],
            )
        ],
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "units",
                            "arguments": {
                                "action": "convert",
                                "quantity": "65 degrees Fahrenheit",
                                "to": "Celsius",
                            },
                        },
                    }
                ],
            )
        ],
        [("token", "Today's high is 65Â°F which is about 18Â°C.")],
    ]

    final_text, tool_results = asyncio.run(
        _run_agent_with_script(
            "Get today's forecast high for Springfield, Illinois with the weather tool, "
            "then convert that temperature to Celsius with the units tool.",
            script,
            ["weather", "units"],
        )
    )

    assert len(tool_results) == 2, f"Expected 2 tool calls, got {len(tool_results)}: {tool_results}"
    assert tool_results[0] == ("weather", True), f"Expected weather ok=True, got {tool_results[0]}"
    assert tool_results[1] == ("units", True), f"Expected units ok=True, got {tool_results[1]}"

    assert "don't know" not in final_text.lower(), f"Got refusal: {final_text}"
    assert "units or constants result" not in final_text.lower(), f"Got refusal: {final_text}"
    # The offline units stub's receipt is the whole answer ("units ok"), so the
    # conversion text is not assertable here; both tools running is the guarantee.
    assert final_text.strip(), "empty answer"


def test_units_calculator_memory_chain() -> None:
    """Units then calculator then memory should run all three tools (C01/P10 bug).

    Live matrix items C01 and P10 failed: units ran, other tools were
    stripped on round 2, and the answer falsely claimed 'noted/stored'
    without calling memory.
    """
    script = [
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "units",
                            "arguments": {
                                "action": "convert",
                                "quantity": "5 miles",
                                "to": "kilometers",
                            },
                        },
                    }
                ],
            )
        ],
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": {"expression": "8.05 * 3"},
                        },
                    }
                ],
            )
        ],
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "memory",
                            "arguments": {
                                "action": "remember",
                                "fact": "weekly run distance is 24.1 kilometers",
                            },
                        },
                    }
                ],
            )
        ],
        [("token", "Got it - your weekly run distance of 24.1 km is stored.")],
    ]

    final_text, tool_results = asyncio.run(
        _run_agent_with_script(
            "Convert 5 miles to kilometers with the units tool, then multiply those "
            "kilometers by 3 with the calculator, then remember that result as my "
            "weekly run distance.",
            script,
            ["units", "calculator", "memory"],
        )
    )

    assert len(tool_results) == 3, f"Expected 3 tool calls, got {len(tool_results)}: {tool_results}"
    assert tool_results[0] == ("units", True), f"Expected units ok=True, got {tool_results[0]}"
    assert tool_results[1] == ("calculator", True), (
        f"Expected calculator ok=True, got {tool_results[1]}"
    )
    assert tool_results[2] == ("memory", True), f"Expected memory ok=True, got {tool_results[2]}"

    assert "don't know" not in final_text.lower(), f"Got refusal: {final_text}"
    assert "units or constants result" not in final_text.lower(), f"Got refusal: {final_text}"
    assert "24" in final_text, f"Missing result in: {final_text}"


def test_weather_document_chain() -> None:
    """Weather then document should run both tools (C02/P09 bug).

    Live matrix items C02 and P09 failed: weather ran, document tool
    was stripped on round 2, and no file was written.
    """
    script = [
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "weather",
                            "arguments": {"place": "Springfield, Illinois", "days": 3},
                        },
                    }
                ],
            )
        ],
        [
            (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "document",
                            "arguments": {
                                "format": "md",
                                "title": "Springfield Weather Brief",
                                "body": "Springfield forecast: Sunny with high of 65F today, partly cloudy tomorrow.",
                            },
                        },
                    }
                ],
            )
        ],
        [("token", "I've saved the weather summary to Springfield Weather Brief.md")],
    ]

    final_text, tool_results = asyncio.run(
        _run_agent_with_script(
            "Get today's weather forecast for Springfield, Illinois, then save a "
            "one-paragraph summary of it as a markdown document titled Springfield "
            "Weather Brief.",
            script,
            ["weather", "document"],
        )
    )

    assert len(tool_results) == 2, f"Expected 2 tool calls, got {len(tool_results)}: {tool_results}"
    assert tool_results[0] == ("weather", True), f"Expected weather ok=True, got {tool_results[0]}"
    assert tool_results[1] == ("document", True), (
        f"Expected document ok=True, got {tool_results[1]}"
    )

    assert "don't know" not in final_text.lower(), f"Got refusal: {final_text}"
    assert "springfield" in final_text.lower(), f"Missing document mention in: {final_text}"


def test_image_edit_then_ocr_chain_does_not_finish_after_the_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live C15/P06: 'grayscale it, then OCR the new image' ended on image_edit."""
    from arelis.eval.harness import _StubTool

    reg = foundation_registry()
    reg.register(_StubTool("image_edit", risk="write"))
    monkeypatch.setattr(sys.modules[__name__], "_tools_registry", lambda names: reg)

    def call(name: str, args: dict) -> list[tuple[str, object]]:
        return [
            ("tool_calls", [{"type": "function", "function": {"name": name, "arguments": args}}])
        ]

    script = [
        call("image_edit", {"path": "work/invoice.png", "op": "grayscale"}),
        call("ocr", {"path": "outputs/images/invoice-gray.png", "action": "text"}),
        [("token", "Amount due 1250")],
    ]
    text, results = asyncio.run(
        _run_agent_with_script(
            "Convert work/invoice.png to grayscale with image_edit, then OCR the new "
            "grayscale image and tell me the amount due.",
            script,
            ["image_edit", "ocr"],
        )
    )
    assert [n for n, _ in results] == ["image_edit", "ocr"]
    assert "1250" in text
