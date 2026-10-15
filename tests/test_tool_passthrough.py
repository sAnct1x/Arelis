"""When the model goes quiet after a tool, the tool's output becomes her turn.

`_tool_followup_fallback` exists because a turn has to end with something, and
throwing away a successful tool result would be worse than showing it. That is
the right call. The defect is what happens next: `_finish` writes that text to
memory as an assistant message, so from the following turn on it is
indistinguishable from prose she composed, and the model reads its own history
as a style guide.

Thirty-six of the forty-odd registered tools reach the verbatim branch — it is
the default, and anything added to the repo joins it without anyone deciding
to. `web_fetch` is the one that proved it matters: it was written into
`_PAGE_TOOLS` when it only read pages, it answers APIs now, and an empty model
reply put a raw response body in the bubble with whatever the endpoint returned
inside it.
"""

from __future__ import annotations

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry
from tests.hardening_helpers import (
    _collect,
    _config,
    _deny,
    _loop_with_tools,
    _scrape_then_empty,
    _ScrapeStub,
    _ScriptedRouter,
)

# --- the note that stops the compounding -------------------------------------


# --- JSON is never her voice -------------------------------------------------


# --- the guard is measured, not asserted -------------------------------------


# --- the wiring, which is the part a unit test misses ------------------------
#
# Everything above passes with `_finish` not attaching the note at all. That
# mutation survived the first version of this file, which is the exact shape
# of "designed to pass rather than designed to catch flaws": the helper was
# tested, the call to it was not. These drive the real `_finish`.


@pytest.mark.asyncio
async def test_finish_attaches_the_note_to_the_memory_turn():
    loop = _loop_with_tools(_ScriptedRouter(["ignored"]))
    await loop._finish("41F and overcast", [], passthrough_tool="weather")
    last = loop.memory.messages[-1]
    assert last.role == "assistant"
    assert "not her own words" in last.note
    assert "forecast" in last.note
    assert "tool" not in last.note.lower()


@pytest.mark.asyncio
async def test_the_note_does_not_displace_the_tool_trace():
    """Both notes ride on the same field. "now edit that file" needs the
    trace, so appending must not overwrite it."""
    loop = _loop_with_tools(_ScriptedRouter(["ignored"]))
    loop._trace = ["workspace write outputs/a.md"]
    await loop._finish("wrote it", [], passthrough_tool="workspace")
    note = loop.memory.messages[-1].note
    assert "tools used this turn" in note
    assert "not her own words" in note


# --- and the layer below that --------------------------------------------
#
# The `_finish` tests above still pass with turn_round hardcoding
# passthrough_tool="", because they call `_finish` themselves. Only a real
# turn proves the three call sites hand the tool name over.


@pytest.mark.asyncio
async def test_a_real_empty_after_tool_turn_marks_its_memory():
    """A whole turn: the model calls scrape, scrape succeeds, the model
    returns nothing, and the page text ends up in the bubble. That bubble is
    what the next turn reads back, so it has to carry the note."""
    bus = EventBus()
    router = _scrape_then_empty([[("token", "")]])
    tools = ToolRegistry()
    tools.register(_ScrapeStub())
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
    await _collect(bus, loop.run("what is SPCX trading at?", "fast"))

    assistant = [m for m in loop.memory.messages if m.role == "assistant"]
    assert assistant, "the turn produced no assistant message"
    last = assistant[-1]
    assert "NASDAQ:SPCX last $143.34" in last.content
    assert "not her own words" in (last.note or "")
    assert "scrape" in (last.note or "")
