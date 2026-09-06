"""Pins scripted AgentLoop stubs: prose-not-executed, empty reply, ollama
down, json fallback, scrape/agenda empty-after-tool, role commands, stop
interrupt, stream paint/retract, and tool trace.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory, tool_trace_entry, tool_trace_note
from arelis.core.orchestrator import Orchestrator
from arelis.llm.errors import OLLAMA_DOWN_NOTICE, OLLAMA_MODEL_NOTICE
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.code_workspace import CodeWorkspaceTool
from tests.hardening_helpers import (
    _AgendaStub,
    _BoomRouter,
    _collect,
    _config,
    _deny,
    _long_scrape_loop,
    _loop_with_tools,
    _scrape_then_empty,
    _ScrapeStub,
    _ScriptedRouter,
    _ToolsRejectThenOk,
)

# --------------------------------------------------------------------------
# Orchestrator and agent loop
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prose_about_a_tool_call_is_not_executed() -> None:
    """End to end version of the strict-parsing rule: the model explains a call,
    Arelis answers with the explanation instead of running it."""
    bus = EventBus()
    prose = (
        'You could emit {"tool":"workspace","args":{"action":"list","path":"."}} '
        "to list the directory."
    )
    router = _ScriptedRouter([[("token", prose)]])
    tools = ToolRegistry()
    tools.register(CodeWorkspaceTool(["."]))
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        _config(),
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("how do tool calls work?", "fast"))
    assert EventType.TOOL_START not in [e.type for e in events]
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "workspace" in done.payload["text"]


@pytest.mark.asyncio
async def test_empty_model_reply_still_explains_itself() -> None:
    """An empty answer used to end the turn with a blank bubble and no error."""
    bus = EventBus()
    router = _ScriptedRouter([[("token", "")], [("token", "")]])
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        ToolRegistry(),
        SessionMemory(),
        "persona",
        _config(),
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("hello", "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "empty reply" in done.payload["text"].lower()


@pytest.mark.asyncio
async def test_empty_after_think_asks_for_a_write_up() -> None:
    """Qwen3.5 can spend the whole budget in thinking and leave chat empty."""
    bus = EventBus()
    router = _ScriptedRouter(
        [
            [("thinking", "17 times 19 is 323, write that next")],
            [("token", "323")],
        ]
    )
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        ToolRegistry(),
        SessionMemory(),
        "persona",
        _config(),
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("explain Gettier in two sentences", "fast"))
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "empty after think; asking for a write-up" in thinking
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert done.payload["text"].strip() == "323"


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
async def test_missing_model_does_not_json_fallback() -> None:
    router = _BoomRouter(
        RuntimeError("Ollama returned HTTP 404 for model `qwen2.5:7b`: not found")
    )
    loop = _loop_with_tools(router)
    events = await _collect(loop.bus, loop.run("list the workspace", "fast"))
    err = next(e for e in events if e.type == EventType.ERROR)
    assert err.payload["message"] == OLLAMA_MODEL_NOTICE.format(model="qwen2.5:7b")
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "native tools failed" not in thinking
    assert router.calls == 1


@pytest.mark.asyncio
async def test_http_400_on_tools_still_json_falls_back() -> None:
    router = _ToolsRejectThenOk()
    loop = _loop_with_tools(router)
    events = await _collect(loop.bus, loop.run("list the workspace", "fast"))
    assert EventType.ERROR not in [e.type for e in events]
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "JSON fallback" in thinking
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "here without native schemas" in done.payload["text"]
    assert router.calls == 2


@pytest.mark.asyncio
async def test_empty_after_successful_tool_skips_json_fallback() -> None:
    """Qwen3.5 left chat content empty after a good scrape and the loop
    started JSON fallback even though native calling had already worked."""
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
                                "arguments": {
                                    "url": "https://example.com/SPCX",
                                },
                            },
                        }
                    ],
                )
            ],
            [("token", "")],
        ]
    )
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
    events = await _collect(bus, loop.run("what is SPCX trading at?", "fast"))
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "JSON fallback" not in thinking
    assert "empty after tool; answering from result" in thinking
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "NASDAQ:SPCX last $143.34" in done.payload["text"]
    assert router.i == 2


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


@pytest.mark.asyncio
async def test_empty_after_long_scrape_twice_ships_lede_not_article() -> None:
    """Last resort after the write-up nudge still must not dump the page."""
    router = _scrape_then_empty(
        [
            [("token", "")],
            [("token", "")],
        ]
    )
    bus, loop = _long_scrape_loop(router)
    events = await _collect(
        bus, loop.run("deep dive piezo hysteresis", "fast")
    )
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "empty after page; asking for a write-up" in thinking
    assert "empty after tool; answering from result" in thinking
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = done.payload["text"]
    assert "PMN-PT" in text
    assert text.count("high d33") <= 2
    assert len(text) < 600


@pytest.mark.asyncio
async def test_empty_after_agenda_create_answers_from_result() -> None:
    """After a successful create, round 2 offers no tools so Qwen can wrap up.

    Qwen3.5 still puts that wrap-up in thinking. The empty-after-tool fallback
    used to require ollama_tools to still be on, so the turn shipped
    'model unloaded' even though Google already had the event.
    """
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
                                "name": "agenda",
                                "arguments": {
                                    "action": "create",
                                    "provider": "google",
                                    "summary": "go to the lab",
                                    "start": "2026-08-20T10:00:00-04:00",
                                },
                            },
                        }
                    ],
                )
            ],
            [("thinking", "Your event is set."), ("token", "")],
        ]
    )
    tools = ToolRegistry()
    tools.register(_AgendaStub())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["confirm_writes"] = False
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
    events = await _collect(
        bus, loop.run('create a calendar event for tomorrow at 10am', "fast")
    )
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "empty after tool; answering from result" in thinking
    assert "JSON fallback" not in thinking
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "go to the lab" in done.payload["text"]
    assert "empty reply" not in done.payload["text"].lower()
    assert router.i == 2


@pytest.mark.asyncio
async def test_empty_first_round_still_json_falls_back() -> None:
    """No tool has run yet — blank content must still enter JSON fallback."""
    bus = EventBus()
    router = _ScriptedRouter(
        [
            [("token", "")],
            [("token", '{"final":"hi from json mode"}')],
        ]
    )
    tools = ToolRegistry()
    tools.register(_ScrapeStub())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
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
    events = await _collect(bus, loop.run("search the web for hello", "fast"))
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "empty tool response; JSON fallback" in thinking
    assert "empty after tool" not in thinking
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "hi from json mode" in done.payload["text"]


@pytest.mark.asyncio
async def test_role_command_ends_the_turn() -> None:
    """/role published only STATUS, and the desktop UI only clears its busy
    state on ASSISTANT_DONE or ERROR, so a valid /role locked the composer."""
    bus = EventBus()
    router = _ScriptedRouter([[("token", "hi")]])
    orch = Orchestrator(bus, router, ToolRegistry(), _config(), SessionMemory())  # type: ignore[arg-type]
    events = await _collect(
        bus, bus.publish(Event(EventType.USER_MESSAGE, {"text": "/role research"}))
    )
    types = [e.type for e in events]
    assert EventType.ASSISTANT_DONE in types
    assert orch.router.default_role == "research"


@pytest.mark.asyncio
async def test_role_research_unloads_conversation_model() -> None:
    """7B used to stay pinned 30m after /role research; 14B then locked VRAM."""

    class SpyRouter(_ScriptedRouter):
        def __init__(self) -> None:
            super().__init__([[("token", "hi")]])
            self.prepared: list[str] = []

        def model_for(self, role=None):
            return {"fast": "qwen-fast", "research": "qwen-big"}.get(
                role or self.default_role, "mock"
            )

        async def prepare_heavy_role(self, role) -> None:
            self.prepared.append(role)

        def clear_sticky(self) -> None:
            return None

    bus = EventBus()
    router = SpyRouter()
    Orchestrator(bus, router, ToolRegistry(), _config(), SessionMemory())  # type: ignore[arg-type]
    events = await _collect(
        bus, bus.publish(Event(EventType.USER_MESSAGE, {"text": "/role research"}))
    )
    assert router.prepared == ["research"]
    status = [
        str((e.payload or {}).get("message") or "")
        for e in events
        if e.type == EventType.STATUS
    ]
    assert any("Unloading conversation model" in m for m in status)
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "Role set to `research`" in str(done.payload.get("text") or "")


@pytest.mark.asyncio
async def test_role_research_skips_unload_when_same_weights() -> None:
    class SpyRouter(_ScriptedRouter):
        def __init__(self) -> None:
            super().__init__([[("token", "hi")]])
            self.prepared: list[str] = []

        async def prepare_heavy_role(self, role) -> None:
            self.prepared.append(role)

        def clear_sticky(self) -> None:
            return None

    bus = EventBus()
    router = SpyRouter()
    Orchestrator(bus, router, ToolRegistry(), _config(), SessionMemory())  # type: ignore[arg-type]
    events = await _collect(
        bus, bus.publish(Event(EventType.USER_MESSAGE, {"text": "/role research"}))
    )
    assert router.prepared == []
    status = [
        str((e.payload or {}).get("message") or "")
        for e in events
        if e.type == EventType.STATUS
    ]
    assert not any("Unloading conversation model" in m for m in status)
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "Role set to `research`" in str(done.payload.get("text") or "")


@pytest.mark.asyncio
async def test_unknown_role_command_ends_the_turn() -> None:
    bus = EventBus()
    router = _ScriptedRouter([[("token", "hi")]])
    Orchestrator(bus, router, ToolRegistry(), _config(), SessionMemory())  # type: ignore[arg-type]
    events = await _collect(
        bus, bus.publish(Event(EventType.USER_MESSAGE, {"text": "/role wizard"}))
    )
    assert EventType.ASSISTANT_DONE in [e.type for e in events]


@pytest.mark.asyncio
async def test_stop_interrupts_a_running_tool() -> None:
    """Cancellation used to be polled only between steps, so stop did nothing
    until an in-flight fetch returned on its own."""

    class SlowTool:
        name = "slow"
        description = "sleeps"
        risk = "read"
        parameters_schema = {"type": "object", "properties": {}}

        async def run(self, **kwargs: Any) -> ToolResult:
            await asyncio.sleep(30)
            return ToolResult(ok=True, output="finished")

    bus = EventBus()
    router = _ScriptedRouter(
        [
            [("tool_calls", [{"type": "function", "function": {"name": "slow", "arguments": {}}}])],
            [("token", "done")],
        ]
    )
    tools = ToolRegistry()
    tools.register(SlowTool())
    Orchestrator(bus, router, tools, _config(), SessionMemory())  # type: ignore[arg-type]

    events: list[Event] = []
    started = asyncio.Event()
    finished = asyncio.Event()

    async def capture(event: Event) -> None:
        events.append(event)
        if event.type == EventType.TOOL_START:
            started.set()
        if event.type == EventType.ASSISTANT_DONE:
            finished.set()

    bus.subscribe(None, capture)
    bus_task = asyncio.create_task(bus.run())
    await bus.publish(Event(EventType.USER_MESSAGE, {"text": "use the slow tool"}))
    await asyncio.wait_for(started.wait(), timeout=5)
    await bus.publish(Event(EventType.TURN_CANCEL, {}))
    # Must land far sooner than the tool's own 30s sleep.
    await asyncio.wait_for(finished.wait(), timeout=5)
    bus.stop()
    bus_task.cancel()

    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert done.payload["text"] == "Stopped."


# --------------------------------------------------------------------------
# Live streaming: what reaches the bubble, and when it has to come back off
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_answer_tokens_stream_as_they_arrive() -> None:
    """The whole answer used to be buffered and published in one delta, so the
    bubble sat empty for the length of the generation."""
    bus = EventBus()
    chunks = ["Vega is ", "a white ", "star about ", "25 light years away."]
    router = _ScriptedRouter([[("token", c) for c in chunks]])
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        ToolRegistry(),
        SessionMemory(),
        "persona",
        _config(),
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("how far is Vega?", "fast"))
    deltas = [e for e in events if e.type == EventType.ASSISTANT_DELTA]
    assert len(deltas) >= 2
    assert "".join(d.payload["text"] for d in deltas) == "".join(chunks)


@pytest.mark.asyncio
async def test_chitchat_streams_while_schemas_stay_on() -> None:
    """chat_fast_path off keeps the prefix cache. Holding every bubble used
    to make hello wait for the whole round (live dump: hold_paint=1 on hi)."""
    bus = EventBus()
    chunks = ["Hello there, ", "I am doing well. ", "Happy to help."]
    router = _ScriptedRouter([[("token", c) for c in chunks]])
    tools = ToolRegistry()
    tools.register(CodeWorkspaceTool(["."]))
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["stream_answer_after_tools"] = True
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
    events = await _collect(bus, loop.run("how are you today?", "fast"))
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "hold_paint=0" in thinking
    deltas = [e for e in events if e.type == EventType.ASSISTANT_DELTA]
    assert len(deltas) >= 2
    assert "".join(d.payload["text"] for d in deltas) == "".join(chunks)


@pytest.mark.asyncio
async def test_tool_ask_still_holds_paint_when_schemas_are_always_on() -> None:
    """A folder ask must not flash tokens, even with chat_fast_path off."""
    bus = EventBus()
    chunks = ["Let me open that. ", "There are eleven files."]
    router = _ScriptedRouter([[("token", c) for c in chunks]])
    tools = ToolRegistry()
    tools.register(CodeWorkspaceTool(["."]))
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["stream_answer_after_tools"] = True
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
    events = await _collect(bus, loop.run("what is in this folder?", "fast"))
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "hold_paint=1" in thinking
    deltas = [e for e in events if e.type == EventType.ASSISTANT_DELTA]
    # Held for the round, then dumped once in _finish — not token-by-token.
    assert len(deltas) == 1


@pytest.mark.asyncio
async def test_preamble_to_a_tool_call_is_retracted_before_the_tool_runs() -> None:
    """Tool-round preambles must not stick as the reply.

    With stream_answer_after_tools (H5), deltas are held while tools are
    offered so a retract is unnecessary — the preamble never paints. Older
    path (hold off) still retracts before TOOL_START.
    """
    bus = EventBus()
    call = {
        "type": "function",
        "function": {"name": "workspace", "arguments": {"action": "list", "path": "."}},
    }
    preamble = "Let me open that folder and see what is inside it."
    router = _ScriptedRouter(
        [
            [("token", preamble), ("tool_calls", [call])],
            [("token", "The folder holds the package and its tests.")],
        ]
    )
    tools = ToolRegistry()
    tools.register(CodeWorkspaceTool(["."]))
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        _config(),
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("what is in this folder?", "fast"))
    types = [e.type for e in events]
    assert EventType.TOOL_START in types
    deltas_before_tool = []
    for event in events:
        if event.type == EventType.TOOL_START:
            break
        if event.type == EventType.ASSISTANT_DELTA:
            deltas_before_tool.append(event.payload.get("text") or "")
    assert not any("Let me open" in t for t in deltas_before_tool)
    if EventType.ASSISTANT_RETRACT in types:
        assert types.index(EventType.ASSISTANT_RETRACT) < types.index(EventType.TOOL_START)
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "Let me open" not in done.payload["text"]


@pytest.mark.asyncio
async def test_json_payload_is_never_painted_into_the_chat() -> None:
    """A fallback payload is an instruction, not an answer. Showing it and then
    deleting it a moment later is worse than never showing it."""
    bus = EventBus()
    payload = '{"tool":"workspace","args":{"action":"list","path":"."}}'
    router = _ScriptedRouter(
        [
            [("token", payload[:9]), ("token", payload[9:])],
            [("token", "There are eleven entries in that directory.")],
        ]
    )
    tools = ToolRegistry()
    tools.register(CodeWorkspaceTool(["."]))
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        _config(),
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("list this folder", "fast"))
    deltas = [e.payload.get("text", "") for e in events if e.type == EventType.ASSISTANT_DELTA]
    assert all('"tool"' not in text for text in deltas)
    assert EventType.TOOL_START in [e.type for e in events]


@pytest.mark.asyncio
async def test_a_tool_call_written_as_prose_is_corrected_not_shipped() -> None:
    """Live transcript from qwen2.5:7b. It announced the call, fenced the JSON,
    then kept writing, so the strict parser refused it. Executing it anyway is
    the hole strict mode closes; shipping it hands the user raw JSON and runs no
    tool. The turn has to ask again instead."""
    bus = EventBus()
    announced = (
        "Let's start by reading the `README.md` file:\n\n"
        '```json\n{"name": "workspace", "arguments": {"action": "read", '
        '"path": "README.md"}}\n```\n\n'
        "Once I've read the file, I'll provide a summary."
    )
    router = _ScriptedRouter(
        [
            [("token", announced)],
            [("token", "Arelis is a local-first research assistant.")],
        ]
    )
    tools = ToolRegistry()
    tools.register(CodeWorkspaceTool(["."]))
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        _config(),
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(bus, loop.run("summarize the readme", "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert '"arguments"' not in done.payload["text"]
    assert done.payload["text"] == "Arelis is a local-first research assistant."
    # The refusal still stands: the prose object must not have been executed.
    assert EventType.TOOL_START not in [e.type for e in events]
    deltas = [e.payload.get("text", "") for e in events if e.type == EventType.ASSISTANT_DELTA]
    # H5 may hold paint so there is no retract; either way the JSON must not ship.
    assert not any('"arguments"' in t for t in deltas)
    if any("Let's start by reading" in t for t in deltas):
        assert EventType.ASSISTANT_RETRACT in [e.type for e in events]


@pytest.mark.asyncio
async def test_stop_keeps_the_text_already_written() -> None:
    """Replacing a half-finished answer with the word "Stopped." throws away
    output the user pressed stop precisely because they had already seen it."""
    bus = EventBus()
    state = {"cancel": False}

    class _CancelMidStream(_ScriptedRouter):
        async def stream(self, role, messages, **kwargs):
            yield ("token", "The first part of the answer is here.")
            state["cancel"] = True
            yield ("token", " and the rest never arrives.")

    loop = AgentLoop(
        bus,
        _CancelMidStream([[]]),  # type: ignore[arg-type]
        ToolRegistry(),
        SessionMemory(),
        "persona",
        _config(),
        request_confirm=_deny,
        is_cancelled=lambda: state["cancel"],
    )
    events = await _collect(bus, loop.run("tell me something", "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "The first part of the answer is here." in done.payload["text"]
    assert "_Stopped._" in done.payload["text"]
    assert "never arrives" not in done.payload["text"]


# --------------------------------------------------------------------------
# Memory: what a later turn can still refer to
# --------------------------------------------------------------------------


def test_tool_trace_records_the_target_but_not_the_payload() -> None:
    entry = tool_trace_entry(
        "workspace", {"action": "write", "path": "data/notes.txt", "content": "x" * 5000}, True
    )
    assert entry == "workspace write data/notes.txt"
    assert "xxxx" not in entry


def test_failed_calls_are_marked_in_the_trace() -> None:
    assert tool_trace_entry("scrape", {"url": "https://a.example"}, False).endswith("(failed)")


def test_trace_note_is_capped() -> None:
    note = tool_trace_note([f"workspace read file{i}.py" for i in range(80)])
    assert len(note) < 500
    assert note.startswith("[tools used this turn:")


def test_trace_note_reaches_the_model_but_not_the_chat() -> None:
    """The point of the note: the model learns which file was written, while the
    user sees only the answer they were given."""
    memory = SessionMemory()
    memory.add("assistant", "Done.", note="[tools used this turn: workspace write data/n.txt]")
    assert memory.messages[0].content == "Done."
    assert "data/n.txt" in memory.as_ollama()[0]["content"]


def test_messages_without_a_trace_are_unchanged() -> None:
    memory = SessionMemory()
    memory.add("user", "hello")
    assert memory.as_ollama() == [{"role": "user", "content": "hello"}]
