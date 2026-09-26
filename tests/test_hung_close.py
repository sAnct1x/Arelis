"""Ceiling close: finish from tool results instead of starting another search."""

from __future__ import annotations

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter


class _ClosingScrape:
    name = "scrape"
    description = "fetch a page"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
    }

    def __init__(self) -> None:
        self.loop: AgentLoop | None = None

    async def run(self, **kwargs: object) -> ToolResult:
        del kwargs
        assert self.loop is not None
        self.loop.request_close()
        return ToolResult(ok=True, output="CH4 detected at about 5 sigma.")


@pytest.mark.asyncio
async def test_close_after_a_tool_does_not_search_again() -> None:
    scrape = _ClosingScrape()
    bus = EventBus()
    router = _ScriptedRouter(
        [
            [
                (
                    "tool_calls",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "scrape",
                                "arguments": {"url": "https://example.com/k2"},
                            },
                        }
                    ],
                )
            ],
            [
                (
                    "token",
                    "Methane is the measurement I actually have. I did not get to the rest.",
                )
            ],
        ]
    )
    tools = ToolRegistry()
    tools.register(scrape)
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
    scrape.loop = loop
    events = await _collect(
        bus,
        loop.run("what did JWST measure in this atmosphere?", "fast"),
    )
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = str(done.payload.get("text") or "")
    assert "closing with what I have" in thinking
    assert "Methane" in text
    assert router.i == 2
    assert "scrape" in loop.tools_used
