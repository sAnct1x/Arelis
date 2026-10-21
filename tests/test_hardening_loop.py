"""Pins scripted AgentLoop stubs: prose-not-executed, empty reply, server
down, json fallback, scrape/agenda empty-after-tool, role commands, stop
interrupt, stream paint/retract, and tool trace.
"""
from __future__ import annotations

import pytest

from arelis.core.events import EventType
from arelis.llm.errors import LLAMACPP_DOWN_NOTICE
from tests.hardening_helpers import (
    _BoomRouter,
    _collect,
    _long_scrape_loop,
    _loop_with_tools,
    _scrape_then_empty,
)

# --------------------------------------------------------------------------
# Orchestrator and agent loop
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_server_down_chat_is_human_not_traceback() -> None:
    """ConnectError used to dump LLM error: ConnectError(...) into chat."""
    import httpx

    router = _BoomRouter(httpx.ConnectError("connection refused"))
    loop = _loop_with_tools(router)
    events = await _collect(loop.bus, loop.run("list the workspace", "fast"))
    err = next(e for e in events if e.type == EventType.ERROR)
    assert err.payload["message"] == LLAMACPP_DOWN_NOTICE
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


