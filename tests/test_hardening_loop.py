"""Pins scripted AgentLoop stubs: prose-not-executed, empty reply, ollama
down, json fallback, scrape/agenda empty-after-tool, role commands, stop
interrupt, stream paint/retract, and tool trace.
"""
from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.llm.errors import OLLAMA_DOWN_NOTICE
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import (
    _BoomRouter,
    _collect,
    _config,
    _deny,
    _long_scrape_loop,
    _loop_with_tools,
    _scrape_then_empty,
    _ScriptedRouter,
)

# --------------------------------------------------------------------------
# Orchestrator and agent loop
# --------------------------------------------------------------------------


class _CasStub:
    name = "cas"
    description = "stub"
    risk = "read"
    parameters_schema: dict[str, Any] = {"type": "object", "properties": {}}

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(
            ok=True,
            output="solve(x^2 + 3*x - 10 = 0) =\n[-5, 2]",
            data={"result": "[-5, 2]"},
        )


class _CalcStub:
    name = "calculator"
    description = "stub"
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        expr = str(kwargs.get("expression") or "").strip() or "1+1"
        return ToolResult(
            ok=True,
            output=f"{expr} = 2",
            data={"expression": expr, "value": 2},
        )


@pytest.mark.asyncio
async def test_calculator_filler_without_the_number_ships_the_result() -> None:
    """Live dump: 1+1 ran, thinking had 2, chat was 'Easy enough. What's next?'."""
    calc_call = {
        "type": "function",
        "function": {
            "name": "calculator",
            "arguments": {"expression": "1+1"},
        },
    }
    bus = EventBus()
    router = _ScriptedRouter(
        [
            [("tool_calls", [calc_call])],
            [("token", "Easy enough. What's next?")],
        ]
    )
    tools = ToolRegistry()
    tools.register(_CalcStub())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 8
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("what is 1+1?", "fast"))
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "algebra result missing from chat" in thinking
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    # #121: plain sentence with the number, not the "1+1 = 2" receipt.
    assert "2" in done.payload["text"]
    assert "What's next?" not in done.payload["text"]
    assert "1+1 = 2" not in done.payload["text"]


@pytest.mark.asyncio
async def test_ollama_down_chat_is_human_not_traceback() -> None:
    """ConnectError used to dump LLM error: ConnectError(...) into chat."""
    import httpx

    router = _BoomRouter(httpx.ConnectError("connection refused"))
    loop = _loop_with_tools(router)
    events = await _collect(loop.bus, loop.run("list the workspace", "fast"))
    err = next(e for e in events if e.type == EventType.ERROR)
    assert err.payload["message"] == OLLAMA_DOWN_NOTICE
    assert "LLM error" not in err.payload["message"]
    assert "ConnectError" not in err.payload["message"]
    assert "ConnectError" in (err.payload.get("detail") or "")
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "ConnectError" in thinking
    assert "native tools failed" not in thinking
    assert router.calls == 1


@pytest.mark.asyncio
async def test_empty_after_long_scrape_asks_for_a_writeup() -> None:
    """Deep research left chat empty after a blog; shipping the page
    was the transcript. Ask once, then take the model's own words."""
    router = _scrape_then_empty(
        [
            [("token", "")],
            [("token", "Use PMN-PT. Invert the Preisach operator.")],
        ]
    )
    bus, loop = _long_scrape_loop(router)
    events = await _collect(
        bus,
        loop.run(
            "best piezo for a U100A mount and the hysteresis math",
            "fast",
        ),
    )
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "empty after page; asking for a write-up" in thinking
    assert "JSON fallback" not in thinking
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "Preisach" in done.payload["text"]
    assert "What is Single Crystal Piezo" not in done.payload["text"]
    assert router.i == 3


# --------------------------------------------------------------------------
# Live streaming: what reaches the bubble, and when it has to come back off
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# Memory: what a later turn can still refer to
# --------------------------------------------------------------------------


