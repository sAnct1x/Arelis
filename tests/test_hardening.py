"""Regression tests for defects found in the audit.

Each test names the behaviour that broke and why it mattered, so a future
change that reintroduces the bug fails with an explanation rather than an
assertion number.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop, _append_sources
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.json_tools import (
    ThinkingStripper,
    extract_native_tool_calls,
    parse_fallback_payload,
    strip_thinking_text,
)
from arelis.core.memory import SessionMemory, tool_trace_entry, tool_trace_note
from arelis.core.orchestrator import Orchestrator, _as_code_block, _tokenize
from arelis.llm.errors import OLLAMA_DOWN_NOTICE, OLLAMA_MODEL_NOTICE
from arelis.llm.ollama import _finalize_tool_calls, _merge_tool_calls
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.code_workspace import CodeWorkspaceTool
from arelis.tools.safety import check_url_allowed
from arelis.ui.markdown import render_markdown

# The offscreen qt_app fixture now lives in tests/conftest.py, shared with the
# voice tests rather than defined twice.

# --------------------------------------------------------------------------
# Parsing: prose must never be mistaken for an instruction
# --------------------------------------------------------------------------


def test_strict_parse_ignores_json_embedded_in_prose() -> None:
    """An answer that discusses a tool call must not execute one."""
    text = (
        "To read a file you would emit "
        '{"tool":"workspace","args":{"action":"write","path":"x","content":"y"}} '
        "and Arelis would run it."
    )
    assert parse_fallback_payload(text, strict=True) is None
    # Permissive mode is only reachable once the loop is already in JSON
    # fallback, where the model was told to emit nothing but the object.
    assert parse_fallback_payload(text, strict=False)["kind"] == "tool"


def test_strict_parse_accepts_a_bare_payload() -> None:
    payload = '{"tool":"workspace","args":{"action":"list"}}'
    assert parse_fallback_payload(payload, strict=True) == {
        "kind": "tool",
        "name": "workspace",
        "args": {"action": "list"},
    }
    fenced = f"```json\n{payload}\n```"
    assert parse_fallback_payload(fenced, strict=True)["name"] == "workspace"


def test_strict_parse_accepts_an_announced_payload() -> None:
    """Observed from qwen2.5:7b: a short preamble, then the call, then nothing.
    Rejecting this stranded the tool call and answered with raw JSON."""
    announced = (
        "To open and summarize a README.md file, I would use the `workspace` tool "
        'with the `read` action. Here is my request:\n\n'
        '{"name": "workspace", "arguments": {"action": "read", "path": "README.md"}}'
    )
    parsed = parse_fallback_payload(announced, strict=True)
    assert parsed == {
        "kind": "tool",
        "name": "workspace",
        "args": {"action": "read", "path": "README.md"},
    }


def test_strict_parse_rejects_a_payload_followed_by_prose() -> None:
    """The distinguishing signal: a model making a call stops after it, a model
    explaining one keeps writing."""
    explained = (
        'Emit {"tool":"workspace","args":{"action":"list"}} and Arelis runs it. '
        "That is the whole protocol."
    )
    assert parse_fallback_payload(explained, strict=True) is None


def test_plain_name_object_is_not_a_tool_call() -> None:
    """{"name": ...} without arguments is ordinary data, not a call."""
    assert parse_fallback_payload('{"name":"Vega","distance_ly":25}', strict=False) is None


def test_unclosed_think_block_does_not_leak_reasoning() -> None:
    """A reply cut off mid-thought must not publish the chain of thought."""
    assert strip_thinking_text("Answer.<think>secret reasoning") == "Answer."
    assert strip_thinking_text("reasoning first</think>Answer.") == "Answer."
    assert strip_thinking_text("<think>a</think>Answer.") == "Answer."


def test_duplicate_tool_calls_are_collapsed() -> None:
    """One confirm must not turn into two writes."""
    call = {
        "type": "function",
        "function": {"name": "workspace", "arguments": {"action": "write", "path": "a"}},
    }
    assert len(extract_native_tool_calls([call, dict(call)])) == 1
    other = {
        "type": "function",
        "function": {"name": "workspace", "arguments": {"action": "write", "path": "b"}},
    }
    assert len(extract_native_tool_calls([call, other])) == 2


# --------------------------------------------------------------------------
# Streaming: tool-call accumulation
# --------------------------------------------------------------------------


def test_streamed_argument_deltas_form_one_call() -> None:
    """OpenAI-style deltas arrive unnamed after the first chunk. Appending a new
    call per chunk would issue the same write several times."""
    dst: list[dict[str, Any]] = []
    _merge_tool_calls(dst, [{"function": {"name": "workspace", "arguments": '{"action":'}}])
    _merge_tool_calls(dst, [{"function": {"arguments": '"read","path":'}}])
    _merge_tool_calls(dst, [{"function": {"arguments": '"README.md"}'}}])
    finalized = _finalize_tool_calls(dst)
    assert len(finalized) == 1
    assert finalized[0]["function"]["arguments"] == {"action": "read", "path": "README.md"}


def test_two_named_calls_in_one_chunk_stay_separate() -> None:
    dst: list[dict[str, Any]] = []
    _merge_tool_calls(
        dst,
        [
            {"function": {"name": "workspace", "arguments": {"action": "list"}}},
            {"function": {"name": "scrape", "arguments": {"url": "https://example.com"}}},
        ],
    )
    assert [c["function"]["name"] for c in _finalize_tool_calls(dst)] == ["workspace", "scrape"]


# --------------------------------------------------------------------------
# Tool registry
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_name_argument_does_not_crash_the_turn() -> None:
    """A hallucinated {"name": ...} argument used to collide with the registry's
    own parameter and raise TypeError out of the agent loop, ending the turn
    with no error event and a permanently disabled composer."""
    reg = ToolRegistry()
    reg.register(CodeWorkspaceTool(["."]))
    result = await reg.call("workspace", **{"name": "oops", "action": "list", "path": "."})
    assert isinstance(result, ToolResult)


def test_confirm_summary_is_redacted() -> None:
    """The confirm card is exactly where a secret being written shows up."""
    reg = ToolRegistry()
    reg.register(CodeWorkspaceTool(["."]))
    summary = reg.summarize_call(
        "workspace", {"action": "write", "path": "c.env", "content": "api_key=sk-abcdefgh12345678"}
    )
    assert "sk-abcdefgh12345678" not in summary
    assert "[redacted]" in summary


@pytest.mark.asyncio
async def test_ambiguous_edit_is_refused(tmp_path) -> None:
    """Editing the first of several matches and reporting success is worse than
    refusing and asking for a wider anchor."""
    target = tmp_path / "f.py"
    target.write_text("x = 1\nx = 1\n", encoding="utf-8")
    tool = CodeWorkspaceTool([str(tmp_path)])
    result = await tool.run(action="edit", path=str(target), old="x = 1", new="x = 2")
    assert not result.ok
    assert "2 times" in result.output
    assert target.read_text(encoding="utf-8") == "x = 1\nx = 1\n"


@pytest.mark.asyncio
async def test_workspace_escape_is_refused(tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    tool = CodeWorkspaceTool([str(root)])
    result = await tool.run(action="read", path=str(outside))
    assert not result.ok
    assert "outside allowed workspace roots" in result.output


# --------------------------------------------------------------------------
# URL policy
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hostname_resolving_to_private_address_is_blocked(monkeypatch) -> None:
    """The textual check cannot see where a name points. A public-looking host
    with a private A record was the live SSRF path."""
    # First answer is genuinely public, second is not. Any private answer must
    # sink the whole request: a rebinding host can return both.
    monkeypatch.setattr(
        "arelis.tools.safety._resolved_ips", lambda host, port: ["93.184.216.34", "192.168.1.10"]
    )
    reason = await check_url_allowed("https://rebind.example.com/x")
    assert reason is not None
    assert "192.168.1.10" in reason


@pytest.mark.asyncio
async def test_public_hostname_is_allowed(monkeypatch) -> None:
    monkeypatch.setattr("arelis.tools.safety._resolved_ips", lambda host, port: ["93.184.216.34"])
    assert await check_url_allowed("https://example.com") is None


@pytest.mark.asyncio
async def test_unresolvable_host_is_refused(monkeypatch) -> None:
    def boom(host: str, port: int) -> list[str]:
        raise OSError("no such host")

    monkeypatch.setattr("arelis.tools.safety._resolved_ips", boom)
    assert "Could not resolve" in (await check_url_allowed("https://nope.invalid") or "")


@pytest.mark.asyncio
async def test_literal_private_addresses_need_no_dns() -> None:
    assert await check_url_allowed("http://127.0.0.1:11434/api/tags") is not None
    assert await check_url_allowed("http://10.0.0.5/") is not None
    assert await check_url_allowed("http://169.254.169.254/latest/meta-data") is not None


# --------------------------------------------------------------------------
# Slash command tokenizing
# --------------------------------------------------------------------------


def test_windows_paths_survive_tokenizing() -> None:
    """POSIX shlex ate the backslashes and produced C:Usersoriginotes.txt, so a
    file that plainly existed came back as not found."""
    assert _tokenize(r"action=read path=C:\Users\you\notes.txt") == [
        "action=read",
        r"path=C:\Users\you\notes.txt",
    ]
    assert _tokenize(r'action=read path="C:\Program Files\a b.txt"') == [
        "action=read",
        r"path=C:\Program Files\a b.txt",
    ]
    # '#' is a comment character to shlex by default, which silently truncated
    # any URL carrying a fragment.
    assert _tokenize("url=https://example.com/page#section") == [
        "url=https://example.com/page#section"
    ]


# --------------------------------------------------------------------------
# Citations
# --------------------------------------------------------------------------


def test_sources_are_appended_from_real_fetches() -> None:
    out = _append_sources("Answer.", [("Example Domain", "https://example.com")])
    assert "**Sources:**" in out
    assert "1. Example Domain (https://example.com)" in out


def test_existing_sources_section_is_left_alone() -> None:
    answer = "Answer.\n\nSources:\n1. https://example.com"
    assert _append_sources(answer, [("Example", "https://example.com")]) == answer


def test_no_sources_section_without_web_use() -> None:
    assert _append_sources("Answer.", []) == "Answer."


def test_sources_reject_non_http_and_inbound_notify() -> None:
    out = _append_sources(
        "Answer.",
        [
            ("Inbound notify ready", "Inbound notify listening — set URL"),
            ("junk", "file:///tmp/x"),
            ("Quanta", "https://www.quantamagazine.org/example"),
        ],
    )
    assert "https://www.quantamagazine.org/example" in out
    assert "Inbound notify" not in out.split("**Sources:**", 1)[-1]
    assert "file://" not in out


def test_sources_not_appended_on_refusal_text() -> None:
    refuse = (
        "I don't know — I don't have a retrieved page warrant for that "
        "claim, so I won't invent one."
    )
    assert _append_sources(refuse, [("Example", "https://example.com")]) == refuse


# --------------------------------------------------------------------------
# Event bus resilience
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_failing_handler_does_not_stop_the_others() -> None:
    """A crashing subscriber used to vanish into an unretrieved task exception,
    leaving the desktop UI busy forever with no error shown."""
    bus = EventBus()
    seen: list[str] = []

    async def broken(event: Event) -> None:
        raise RuntimeError("handler blew up")

    async def healthy(event: Event) -> None:
        seen.append(event.payload.get("message", ""))

    bus.subscribe(EventType.STATUS, broken)
    bus.subscribe(EventType.STATUS, healthy)
    task = asyncio.create_task(bus.run())
    await bus.publish(Event(EventType.STATUS, {"message": "still delivered"}))
    await bus.drain()
    bus.stop()
    task.cancel()
    assert seen == ["still delivered"]


# --------------------------------------------------------------------------
# Orchestrator and agent loop
# --------------------------------------------------------------------------


class _ScriptedRouter:
    """Minimal ModelRouter stand-in driven by a list of scripted streams."""

    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        self.script = script
        self.i = 0
        self.default_role = "fast"
        self.active_model = None
        self.active_role = None
        self.models = {"fast": "mock", "research": "mock", "code": "mock"}

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        self.active_role = role
        self.active_model = "mock"
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    def apply_sticky(self, wanted, reason: str):
        return wanted, reason

    async def stream(self, role, messages, **kwargs):
        steps = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        for item in steps:
            yield item


def _config() -> dict[str, Any]:
    return {
        "agent": {"max_rounds": 4, "tool_output_chars": 4000, "json_fallback": True},
        "ollama": {"base_url": "http://127.0.0.1:11434"},
        "voice": {"enabled": False},
        "_persona_path": "does-not-exist.md",
    }


async def _collect(bus: EventBus, coro) -> list[Event]:
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    task = asyncio.create_task(bus.run())
    await coro
    await bus.drain()
    bus.stop()
    task.cancel()
    return events


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


class _BoomRouter(_ScriptedRouter):
    """First stream() raises; used to prove Ollama-down copy."""

    def __init__(self, exc: BaseException) -> None:
        super().__init__([[]])
        self.exc = exc
        self.calls = 0

    async def stream(self, role, messages, **kwargs):
        self.calls += 1
        raise self.exc
        yield  # unreachable; keeps this an async generator like ModelRouter.stream


class _ToolsRejectThenOk(_ScriptedRouter):
    """HTTP 400 on the tools array, then a normal answer (JSON fallback)."""

    def __init__(self) -> None:
        super().__init__([[("token", "here without native schemas")]])
        self.calls = 0

    async def stream(self, role, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError(
                "Ollama returned HTTP 400 for model `mock`: invalid tools"
            )
        async for item in super().stream(role, messages, **kwargs):
            yield item


def _loop_with_tools(router) -> AgentLoop:
    tools = ToolRegistry()
    tools.register(CodeWorkspaceTool(["."]))
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    return AgentLoop(
        EventBus(),
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )


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


class _ScrapeStub:
    """Read tool that succeeds; used to prove empty-after-tool skips JSON mode."""

    name = "scrape"
    description = "fetch a page"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(
            ok=True,
            output="NASDAQ:SPCX last $143.34",
        )


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
    events = await _collect(bus, loop.run("hello", "fast"))
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert "empty tool response; JSON fallback" in thinking
    assert "empty after tool" not in thinking
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "hi from json mode" in done.payload["text"]


async def _deny(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
    return "skip"


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


def test_think_tag_split_across_chunks_is_still_stripped() -> None:
    """The stream can break a tag anywhere. Emitting the first half would put
    "<thi" in the bubble and then fail to recognize the tag at all."""
    stripper = ThinkingStripper()
    assert stripper.feed("Hello <thi") == "Hello "
    assert stripper.feed("nk>secret") == ""
    assert stripper.feed(" more</thi") == ""
    assert stripper.feed("nk> world") == " world"
    assert stripper.flush() == ""


def test_unclosed_think_block_is_dropped_from_a_stream() -> None:
    """Matches strip_thinking_text: a reply cut off mid-thought publishes
    nothing rather than its whole chain of thought."""
    stripper = ThinkingStripper()
    assert stripper.feed("<think>still reasoning") == ""
    assert stripper.flush() == ""


def test_closing_tag_without_an_opener_requests_a_retract() -> None:
    """The reasoning began before the first chunk, so everything already shown
    was part of it and has to be withdrawn."""
    stripper = ThinkingStripper()
    assert stripper.feed("weighing the options") == "weighing the options"
    assert stripper.feed("</think>The answer is 42.") == "The answer is 42."
    assert stripper.take_reset() is True
    assert stripper.take_reset() is False


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


# --------------------------------------------------------------------------
# Markdown rendering
# --------------------------------------------------------------------------


def test_markdown_renders_the_marks_models_actually_emit() -> None:
    html = render_markdown("**Sources:**\n\n1. Example (https://example.com)")
    assert "<b>Sources:</b>" in html
    assert "**" not in html
    # Renderer may emit styled <ol style="..."> — bare '<ol>' is too strict.
    assert "<ol" in html
    assert 'href="https://example.com"' in html


def test_code_fence_becomes_preformatted_text() -> None:
    html = render_markdown("Try this:\n\n```python\nx = [1, 2]\n```")
    assert "<pre" in html
    assert "x = [1, 2]" in html
    assert "```" not in html


def test_html_in_model_output_is_escaped_not_executed() -> None:
    """Answers can quote a scraped page verbatim. An <img> surviving into the
    document would turn displaying an answer into a network request."""
    html = render_markdown('Look: <img src="http://tracker.example/p.gif"> and <b>raw</b>')
    assert "<img" not in html
    assert "&lt;img" in html
    assert "<b>raw</b>" not in html


def test_identifiers_with_underscores_are_not_italicised() -> None:
    """A coding assistant writes snake_case constantly. Treating the underscores
    as emphasis mangles every one of them."""
    html = render_markdown("Call tool_output_chars before max_rounds is reached.")
    assert "<i>" not in html
    assert "tool_output_chars" in html


def test_link_schemes_other_than_web_are_not_linkified() -> None:
    html = render_markdown("[click](javascript:alert(1))")
    assert "href" not in html
    assert "click" in html


def test_nested_lists_close_in_the_right_order() -> None:
    html = render_markdown("- outer\n  - inner\n- outer again")
    assert html.count("<ul") == 2
    assert "padding-left:18px" in html
    assert html.count("</ul>") == 2
    assert html.index("<li>inner</li>") < html.index("</ul>")


def test_tables_render_with_their_columns_aligned() -> None:
    html = render_markdown("| a | b |\n| --- | ---: |\n| 1 | 2 |")
    assert "<table" in html
    assert "<th" in html and "<td" in html
    assert "text-align:right" in html


def test_ragged_table_rows_do_not_shift_columns() -> None:
    html = render_markdown("| a | b | c |\n| --- | --- | --- |\n| 1 |")
    assert html.count("<td") == 3


def test_font_stack_does_not_break_the_style_attribute() -> None:
    """The theme's mono stack quotes each family with double quotes. Dropped
    straight into style="..." it closes the attribute and the rest of the
    declaration becomes stray tag junk."""
    html = render_markdown("```\nx = 1\n```")
    opening_tag = html[: html.index(">") + 1]
    assert opening_tag.count('"') == 2
    assert "font-family" in opening_tag


def test_inline_code_is_not_reinterpreted() -> None:
    html = render_markdown("Use `**not bold**` here.")
    assert "<b>" not in html
    assert "**not bold**" in html


# --------------------------------------------------------------------------
# Chat panel: streaming draft, then the rendered answer
# --------------------------------------------------------------------------


def test_chat_replaces_the_streamed_draft_with_rendered_markdown(qt_app) -> None:
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.begin_assistant()
    panel.append_delta("**bold** and ")
    panel.append_delta("`code`")
    panel.finish_assistant("**bold** and `code`")
    text = panel.view.toPlainText()
    assert "**bold**" not in text
    assert "bold" in text and "code" in text


def test_discarded_stream_leaves_the_document_untouched(qt_app) -> None:
    """The retract path. If the anchor is off by a character the previous
    message loses its last letter, which is how this would show up."""
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.add_user("what is in this folder?")
    before = panel.view.toPlainText()
    panel.begin_assistant()
    panel.append_delta("Let me open that folder for you")
    panel.discard_stream()
    assert panel.view.toPlainText() == before


def test_inbound_notice_waits_until_the_assistant_bubble_closes(qt_app) -> None:
    """Inbound SMS must not concatenate into an unrelated streaming answer."""
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.begin_assistant()
    panel.append_delta("Let's sketch the visualization interface.")
    panel.add_system("Text from Robin Hale: Bro that man is SSG")
    assert "Bro that man is SSG" not in panel.view.toPlainText()
    panel.finish_assistant("Let's sketch the visualization interface.")
    text = panel.view.toPlainText()
    assert "visualization interface" in text
    assert "Bro that man is SSG" in text
    assert text.index("visualization") < text.index("Bro that man is SSG")


def test_answer_delivered_without_streaming_is_still_rendered(qt_app) -> None:
    """Slash commands and /help arrive as one ASSISTANT_DONE with no deltas."""
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.finish_assistant("# Heading\n\n- one\n- two")
    text = panel.view.toPlainText()
    assert "#" not in text
    assert "Heading" in text and "one" in text


def test_user_text_is_shown_exactly_as_typed(qt_app) -> None:
    """Rendering the user's own message hides what they sent, which matters most
    for slash commands where the literal characters are the point."""
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.add_user("/workspace action=read path=**notes**.md")
    assert "**notes**.md" in panel.view.toPlainText()


def test_long_transcript_load_keeps_markdown_stable(qt_app) -> None:
    """L2 soak: History reload of a long mixed thread must not leave raw marks."""
    from arelis.ui.panels.chat import ChatPanel

    messages: list[dict[str, str]] = []
    for i in range(40):
        messages.append({"role": "user", "content": f"turn {i} ask about **item {i}**"})
        messages.append(
            {
                "role": "assistant",
                "content": (
                    f"## Answer {i}\n\n"
                    f"- point one for {i}\n"
                    f"- point two\n\n"
                    f"Use `code_{i}` and a fence:\n\n"
                    f"```python\nprint({i})\n```\n\n"
                    f"**Sources:**\n\n"
                    f"1. Example (https://example.com/{i})"
                ),
            }
        )
    panel = ChatPanel()
    panel.load_messages(messages)
    text = panel.view.toPlainText()
    assert text.count("you") >= 40
    assert text.count("arelis") >= 40
    assert "Answer 0" in text and "Answer 39" in text
    assert "print(39)" in text
    # Rendered: markdown markers should not litter the surface.
    assert "**Sources:**" not in text
    assert "```" not in text
    assert "## Answer" not in text
    html = panel.view.toHtml()
    assert "https://example.com/39" in html
    # Live stream + finish on top of a long loaded thread still paints cleanly.
    panel.add_user("one more")
    panel.begin_assistant()
    panel.append_delta("partial **bold**")
    panel.finish_assistant("final **bold** and `x`\n\n- ok")
    live = panel.view.toPlainText()
    assert "one more" in live
    assert "**bold**" not in live
    assert "final" in live and "bold" in live


# --------------------------------------------------------------------------
# Slash command output and the CLI confirm gate
# --------------------------------------------------------------------------


def test_tool_output_is_fenced_past_its_own_backticks() -> None:
    """Reading a markdown file that contains a fence would otherwise close the
    block early and spill the rest of the file into the chat as prose."""
    block = _as_code_block("text\n```\ninner\n```\ndone")
    assert block.startswith("````")
    assert block.endswith("````")


def test_plain_tool_output_uses_a_normal_fence() -> None:
    assert _as_code_block("[dir] arelis").startswith("```\n")


@pytest.mark.asyncio
async def test_cli_asks_before_writing_on_a_terminal(monkeypatch) -> None:
    """The CLI used to auto-allow every write with only a printed notice."""
    from arelis.cli import CliPrinter

    printer = CliPrinter(EventBus(), interactive=True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert await printer._decide("write data/x.txt") == ("skip", False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert await printer._decide("write data/x.txt") == ("allow", False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "a")
    assert await printer._decide("write data/x.txt") == ("allow_turn", True)


@pytest.mark.asyncio
async def test_cli_lost_stdin_is_not_consent(monkeypatch) -> None:
    from arelis.cli import CliPrinter

    printer = CliPrinter(EventBus(), interactive=True)

    def closed(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    assert await printer._decide("write data/x.txt") == ("skip", False)


@pytest.mark.asyncio
async def test_cli_piped_denies_by_default() -> None:
    """Absence of a human is not consent — piped stdin skips confirms."""
    from arelis.cli import CliPrinter

    printer = CliPrinter(EventBus(), interactive=False)
    assert await printer._decide("write data/x.txt") == ("skip", False)


@pytest.mark.asyncio
async def test_cli_piped_allow_write_opt_in() -> None:
    from arelis.cli import CliPrinter

    printer = CliPrinter(EventBus(), interactive=False, allow_write=True)
    assert await printer._decide("write data/x.txt") == ("allow", False)
