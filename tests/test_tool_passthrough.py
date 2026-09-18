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

import json

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.failure_copy import _is_json_body, chat_followup_from_tool
from arelis.core.memory import SessionMemory, tool_passthrough_note
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


def test_the_note_says_it_was_not_her():
    note = tool_passthrough_note("weather")
    assert "not her own words" in note
    assert "weather" in note


def test_the_note_survives_an_unnamed_tool():
    """last_ok_tool_name can be empty. The note must still say what it is."""
    note = tool_passthrough_note("")
    assert "raw tool output" in note
    assert " from " not in note


def test_the_note_reaches_the_next_prompt():
    """A note that memory keeps but never sends is decoration. as_ollama is
    the path into the next turn's context."""
    memory = SessionMemory()
    memory.add("assistant", '{"temp":41}', note=tool_passthrough_note("web_fetch"))
    sent = memory.as_ollama()[-1]["content"]
    assert '{"temp":41}' in sent
    assert "not her own words" in sent


def test_the_bubble_text_itself_is_untouched():
    """The result still has to be readable. The note explains it; it does not
    replace it."""
    memory = SessionMemory()
    memory.add("assistant", "41F and overcast", note=tool_passthrough_note("weather"))
    assert memory.messages[-1].content == "41F and overcast"


# --- JSON is never her voice -------------------------------------------------


def test_an_api_body_does_not_become_her_answer():
    body = '{"ok":true,"data":{"items":[1,2,3]}}'
    line = chat_followup_from_tool("web_fetch", body, ask="hit the api")
    assert body not in line
    assert "came back with data" in line


def test_a_json_array_counts_too():
    body = '[{"id":1},{"id":2}]'
    line = chat_followup_from_tool("web_fetch", body, ask="list them")
    assert body not in line
    assert "came back with data" in line


def test_the_api_body_is_caught_before_the_page_branch():
    """web_fetch is in _PAGE_TOOLS from when it only read pages. _page_talk
    has no idea what to do with a response object and handed it straight back,
    so the JSON check has to come first or it never runs."""
    from arelis.core.failure_copy import _PAGE_TOOLS

    assert "web_fetch" in _PAGE_TOOLS
    line = chat_followup_from_tool("web_fetch", '{"secret":"value"}', ask="x")
    assert "secret" not in line


def test_prose_from_a_tool_still_passes_through():
    """The fix must not swallow the tools that answer in words. weather and
    inbound_sms write person-facing copy on purpose."""
    weather = "Springfield, Illinois\nNow: 41F, overcast"
    assert chat_followup_from_tool("weather", weather, ask="weather") == weather


def test_a_sentence_that_starts_with_a_brace_is_still_a_sentence():
    """Parsed, not pattern-matched. Refusing anything that opens with `{`
    would swallow real output."""
    text = "{this is not json} and it is a sentence about braces."
    assert chat_followup_from_tool("analyze", text, ask="x") == text


def test_a_truncated_body_is_not_treated_as_json():
    """A cut-off object does not parse, so it is shown rather than swallowed.
    Showing something broken beats showing nothing."""
    assert _is_json_body('{"ok":true,"data":{"item') is False


def test_a_bare_number_is_json_but_is_not_swallowed():
    """`json.loads("7")` succeeds. A calculator answering 7 must survive."""
    assert _is_json_body("7") is False
    assert chat_followup_from_tool("calculator", "7", ask="what is 3+4") == "7"


def test_a_quoted_string_is_json_but_is_not_swallowed():
    assert _is_json_body('"done"') is False


def test_empty_output_is_not_json():
    assert _is_json_body("") is False
    assert _is_json_body("   ") is False


# --- the guard is measured, not asserted -------------------------------------


def test_the_verbatim_branch_is_the_default_not_the_exception():
    """The reason this file exists. If someone special-cases every tool one
    day this number drops and the test says so, instead of quietly passing."""
    from arelis.core.failure_copy import _PAGE_TOOLS, _SEARCH_TOOLS

    handled = _PAGE_TOOLS | _SEARCH_TOOLS | {"workspace", "agenda", "doc_extract"}
    assert len(handled) < 10, (
        "Most tools still fall through to the verbatim paste. That is the "
        "default, so the note in memory is what has to carry the attribution."
    )


def test_round_tripping_a_real_api_shape():
    """The shape that started this: an endpoint that answers with a token."""
    body = json.dumps({"access_token": "sk-live-abc123", "expires_in": 3600})
    line = chat_followup_from_tool("web_fetch", body, ask="authenticate")
    assert "sk-live-abc123" not in line


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
    assert "weather" in last.note


@pytest.mark.asyncio
async def test_a_normal_answer_carries_no_such_note():
    """The note must mean something. If every turn got one it would be noise
    and the model would learn to ignore it."""
    loop = _loop_with_tools(_ScriptedRouter(["ignored"]))
    await loop._finish("It is 41 and overcast out.", [])
    assert "not her own words" not in (loop.memory.messages[-1].note or "")


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


@pytest.mark.asyncio
async def test_the_bubble_is_unchanged_by_the_note():
    loop = _loop_with_tools(_ScriptedRouter(["ignored"]))
    await loop._finish("41F and overcast", [], passthrough_tool="weather")
    assert loop.memory.messages[-1].content == "41F and overcast"


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
