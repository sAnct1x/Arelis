"""Context fitting: the persona must survive a full window."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from arelis.core.agent_loop import AgentLoop, _parse_summary_response
from arelis.core.bus import EventBus
from arelis.core.context import (
    DEFAULT_CHARS_PER_TOKEN,
    TokenRatios,
    allocate_history,
    context_budget,
    estimate_tokens,
    fit_messages,
    prompt_char_count,
    split_recent_history,
)
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.llm.ollama import OllamaProvider
from arelis.tools.base import ToolRegistry


def test_the_persona_survives_a_context_overflow() -> None:
    """Ollama drops from the front; without pinning, identity is the first loss."""
    persona = {
        "role": "system",
        "content": "You are Arelis. PERSONA_MARKER_KEEP_ME",
    }
    policy = {"role": "system", "content": "Use tools when needed."}
    pinned = [persona, policy]
    history = [{"role": "user", "content": ("old turn " * 80)}] * 40
    # Tight enough that history cannot all fit, loose enough that pinned can.
    budget = estimate_tokens(persona["content"] + policy["content"]) + 50
    fitted = fit_messages(pinned, history, budget, chars_per_token=DEFAULT_CHARS_PER_TOKEN)
    assert fitted[0]["content"] == persona["content"]
    assert "PERSONA_MARKER_KEEP_ME" in fitted[0]["content"]
    assert fitted[1]["content"] == policy["content"]
    assert any(m["role"] == "user" for m in fitted)


def test_allocate_history_reports_what_was_dropped() -> None:
    history = [
        {"role": "user", "content": "AAAA"},
        {"role": "assistant", "content": "BBBB"},
        {"role": "user", "content": "CCCC"},
    ]
    kept, dropped = allocate_history(history, estimate_tokens("CCCC"), chars_per_token=4.0)
    assert [m["content"] for m in kept] == ["CCCC"]
    assert [m["content"] for m in dropped] == ["AAAA", "BBBB"]


def test_split_recent_history_pins_the_tail() -> None:
    history = [
        {"role": "user", "content": f"u{i}"} for i in range(8)
    ]
    older, tail = split_recent_history(history, 6)
    assert [m["content"] for m in tail] == ["u2", "u3", "u4", "u5", "u6", "u7"]
    assert [m["content"] for m in older] == ["u0", "u1"]
    older, tail = split_recent_history(history[:3], 6)
    assert older == []
    assert [m["content"] for m in tail] == ["u0", "u1", "u2"]


def test_parse_summary_response_reads_summary_and_facts() -> None:
    summary, facts = _parse_summary_response(
        "SUMMARY: They discussed the interferometer build.\n"
        "FACTS:\n"
        "- User builds an interferometer\n"
        "- NONE\n"
    )
    assert "interferometer build" in summary
    assert facts == ["User builds an interferometer"]


def test_parse_summary_response_drops_email_draft_facts() -> None:
    _summary, facts = _parse_summary_response(
        "SUMMARY: Drafted an email.\n"
        "FACTS:\n"
        "- User email draft subject: Hello body: hi there\n"
        "- Sam prefers dark mode\n"
    )
    assert "email draft" not in " ".join(facts).lower()
    assert any("dark mode" in f.lower() for f in facts)


def test_parse_summary_response_drops_transient_transcript_facts() -> None:
    summary, facts = _parse_summary_response(
        "SUMMARY: Talked through conveyor layout steps.\n"
        "FACTS:\n"
        "- User asked about pallet scanner models\n"
        "- They discussed conveyor throughput\n"
        "- User is a backend engineer at a logistics company\n"
        "- assistant: Understood, I will help with that\n"
        "- What scanner firmware should we use?\n"
    )
    assert "conveyor layout" in summary
    assert facts == ["User is a backend engineer at a logistics company"]


def test_fit_messages_prefers_newer_history() -> None:
    pinned = [{"role": "system", "content": "sys"}]
    history = [
        {"role": "user", "content": "AAAA"},
        {"role": "assistant", "content": "BBBB"},
        {"role": "user", "content": "CCCC"},
    ]
    # Only room for pinned + one short message after it.
    budget = estimate_tokens("sys") + estimate_tokens("CCCC")
    fitted = fit_messages(pinned, history, budget)
    assert fitted[0]["content"] == "sys"
    assert fitted[-1]["content"] == "CCCC"
    assert "AAAA" not in [m["content"] for m in fitted]


def test_pinned_messages_are_kept_even_when_they_exceed_the_budget() -> None:
    pinned = [{"role": "system", "content": "x" * 400}]
    history = [
        {"role": "user", "content": "stale"},
        {"role": "user", "content": "hello"},
    ]
    fitted = fit_messages(pinned, history, budget=10, chars_per_token=4.0)
    # Pinned stays, and the newest user turn still rides along so the ask is seen.
    assert fitted[0] == pinned[0]
    assert fitted[-1]["content"] == "hello"
    assert "stale" not in [m["content"] for m in fitted]


def test_speak_mode_tool_reserve_leaves_more_history_room() -> None:
    """Conversation mode uses a smaller tool reserve so summarize fires later."""
    from arelis.core.agent_loop import _SPEAK_TOOL_OUTPUT_CHARS

    full = context_budget(8192, tool_output_chars=14000, chars_per_token=4.0)
    speak = context_budget(
        8192, tool_output_chars=_SPEAK_TOOL_OUTPUT_CHARS, chars_per_token=4.0
    )
    assert speak > full


def test_context_budget_reserves_space_for_a_tool_result_and_a_reply() -> None:
    budget = context_budget(8192, tool_output_chars=14000, chars_per_token=4.0)
    # 8192 - 1024 reply - 3500 tool ≈ 3668
    assert budget == 8192 - 1024 - estimate_tokens("x" * 14000, chars_per_token=4.0)
    assert budget < 8192


def test_session_memory_trims_by_tokens_when_count_would_still_fit() -> None:
    memory = SessionMemory(max_messages=40, max_tokens=45, chars_per_token=4.0)
    memory.add("user", "a" * 80)  # ~20 tokens
    memory.add("assistant", "b" * 80)  # ~20 tokens, total under the cap
    memory.add("user", "c" * 80)  # ~60 total; oldest goes, count still under 40
    assert len(memory.messages) == 2
    assert memory.messages[0].content.startswith("b")
    assert memory.messages[1].content.startswith("c")


def test_token_ratios_calibrate_from_prompt_eval_count(tmp_path: Path) -> None:
    store = TokenRatios(tmp_path / "token_ratios.json")
    assert store.get("qwen2.5:7b") == DEFAULT_CHARS_PER_TOKEN
    updated = store.observe("qwen2.5:7b", prompt_chars=400, prompt_eval_count=100)
    assert updated == pytest.approx(4.0)
    assert store.get("qwen2.5:7b") == pytest.approx(4.0)
    raw = json.loads((tmp_path / "token_ratios.json").read_text(encoding="utf-8"))
    assert raw["qwen2.5:7b"] == pytest.approx(4.0)


def test_token_ratios_ignore_implausible_observations(tmp_path: Path) -> None:
    store = TokenRatios(tmp_path / "token_ratios.json")
    assert store.observe("qwen2.5:7b", prompt_chars=10, prompt_eval_count=1000) is None
    assert store.get("qwen2.5:7b") == DEFAULT_CHARS_PER_TOKEN


def test_prompt_char_count_sums_message_contents() -> None:
    assert prompt_char_count([{"role": "user", "content": "abcd"}, {"role": "assistant", "content": "ef"}]) == 6


def test_prompt_char_count_includes_the_tool_array() -> None:
    """Ollama tokenizes the schemas, so the numerator has to count them."""
    messages = [{"role": "user", "content": "abcd"}]
    tools = [{"type": "function", "function": {"name": "weather"}}]
    assert prompt_char_count(messages, tools=tools) > prompt_char_count(messages)
    assert prompt_char_count(messages, tools=None) == 4


def test_a_tool_bearing_ratio_lands_in_the_prose_band() -> None:
    """The calibration bug in one number.

    A tool-bearing turn is mostly schema. Counting only the messages divided a
    fraction of the characters by all of the tokens and learned ~2.3, which made
    every later estimate about twice as expensive as reality and dropped history
    that would have fit. Counting the schemas puts it back in Qwen's prose band.
    """
    messages = [{"role": "user", "content": "x" * 400}]
    tools = [
        {
            "type": "function",
            "function": {"name": f"tool_{i}", "description": "y" * 300},
        }
        for i in range(10)
    ]
    eval_count = (400 + len(json.dumps(tools))) // 4

    messages_only = prompt_char_count(messages) / eval_count
    with_schemas = prompt_char_count(messages, tools=tools) / eval_count

    assert messages_only < 1.0
    assert 3.5 <= with_schemas <= 5.0


def test_context_budget_charges_for_the_tool_schemas() -> None:
    """Schemas are prompt. The budget used to hand their room to history twice."""
    bare = context_budget(8192, tool_output_chars=14000, chars_per_token=4.0)
    withschema = context_budget(
        8192, tool_output_chars=14000, chars_per_token=4.0, schema_chars=4000
    )
    assert withschema == bare - estimate_tokens("x" * 4000, chars_per_token=4.0)
    assert withschema < bare
    # A fast-path turn offers no schemas and must not be charged for them.
    assert context_budget(
        8192, tool_output_chars=14000, chars_per_token=4.0, schema_chars=0
    ) == bare


def test_context_budget_never_goes_negative_on_a_huge_schema() -> None:
    assert (
        context_budget(
            2048, tool_output_chars=14000, chars_per_token=4.0, schema_chars=400000
        )
        == 0
    )


@pytest.mark.asyncio
async def test_stream_chat_yields_prompt_eval_count_from_the_done_chunk() -> None:
    """The final Ollama frame carries the count; discarding it leaves fitting uncalibrated."""
    lines = [
        json.dumps({"message": {"role": "assistant", "content": "Hi"}, "done": False}),
        json.dumps(
            {
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "prompt_eval_count": 42,
                "eval_count": 3,
            }
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(200, text="\n".join(lines) + "\n")

    provider = OllamaProvider(base_url="http://test")
    await provider.close()
    provider._client = httpx.AsyncClient(
        base_url="http://test", transport=httpx.MockTransport(handler)
    )
    try:
        events: list[tuple[str, Any]] = []
        async for item in provider.stream_chat(
            "qwen2.5:7b", [{"role": "user", "content": "hi"}]
        ):
            events.append(item)
    finally:
        await provider.close()

    assert ("token", "Hi") in events
    metrics = [payload for kind, payload in events if kind == "metrics"]
    assert metrics == [{"prompt_eval_count": 42, "eval_count": 3}]


class _SummaryProvider:
    """First call is the rolling summary; later calls are the real turn."""

    def __init__(self, *, require_summary_pin: bool = True) -> None:
        self.calls: list[list[dict[str, Any]]] = []
        self.require_summary_pin = require_summary_pin

    async def stream_chat(self, model, messages, **kwargs):
        self.calls.append(list(messages))
        blob = " ".join(str(m.get("content") or "") for m in messages)
        if "New excerpt to fold in:" in blob:
            yield (
                "token",
                "SUMMARY: Earlier they planned an interferometer.\n"
                "FACTS:\n- User builds an interferometer\n",
            )
            return
        # The live turn must still see identity and the folded past.
        contents = [str(m.get("content") or "") for m in messages]
        assert any("You are Arelis." in c for c in contents)
        if self.require_summary_pin:
            assert any("[earlier in this conversation:" in c for c in contents)
        yield ("token", "We were planning the interferometer.")

    async def list_models(self):
        return []

    async def unload(self, model):
        return None

    async def close(self):
        return None


class _SummaryRouter:
    def __init__(self, provider: _SummaryProvider) -> None:
        self.provider = provider
        self.default_role = "fast"
        self.active_model = None
        self.active_role = None
        self.models = {"fast": "mock", "research": "mock", "code": "mock"}
        self.roles_used: list[str] = []

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        self.active_role = role
        self.active_model = "mock"
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    async def stream(self, role, messages, **kwargs):
        self.roles_used.append(role)
        async for item in self.provider.stream_chat("mock", messages, **kwargs):
            yield item


async def _allow(*_args: Any, **_kwargs: Any) -> str:
    return "allow"


@pytest.mark.asyncio
async def test_overflowing_history_is_summarized_rather_than_forgotten() -> None:
    """Long sessions must fold old turns into a pinned summary, not delete them."""
    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)

    memory = SessionMemory()
    for i in range(12):
        memory.add("user", f"turn-{i} " + ("x" * 2000))
        memory.add("assistant", f"reply-{i} " + ("y" * 2000))
    before = len(memory.messages)

    provider = _SummaryProvider()
    router = _SummaryRouter(provider)
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        ToolRegistry(),
        memory,
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 4,
                "tool_output_chars": 14000,
                "confirm_writes": True,
                "confirm_image": True,
                "json_fallback": True,
            },
            "ollama": {"base_url": "http://127.0.0.1:11434", "num_ctx": 8192},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )

    bus_task = asyncio.create_task(bus.run())
    await loop.run("what were we talking about?", "fast")
    await bus.drain()
    bus.stop()
    bus_task.cancel()

    assert memory.summary
    assert "interferometer" in memory.summary.lower()
    assert len(memory.messages) < before
    assert "User builds an interferometer" in memory.pending_facts
    assert EventType.ASSISTANT_DONE in [e.type for e in events]
    assert len(provider.calls) >= 2
    # Summarize with the turn's role so a non-fast turn does not force a swap.
    assert router.roles_used[0] == "fast"


@pytest.mark.asyncio
async def test_conversation_mode_drops_overflow_without_llm_summarize() -> None:
    """Spoken turns must not pay a second model pass just to shed two old turns."""
    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)

    memory = SessionMemory()
    for i in range(12):
        memory.add("user", f"turn-{i} " + ("x" * 2000))
        memory.add("assistant", f"reply-{i} " + ("y" * 2000))
    before = len(memory.messages)

    provider = _SummaryProvider(require_summary_pin=False)
    router = _SummaryRouter(provider)
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        ToolRegistry(),
        memory,
        "You are Arelis.",
        {
            "agent": {
                "max_rounds": 4,
                "tool_output_chars": 14000,
                "confirm_writes": True,
                "confirm_image": True,
                "json_fallback": True,
                "turn_telemetry": False,
            },
            "ollama": {"base_url": "http://127.0.0.1:11434", "num_ctx": 8192},
            "_speak_replies": True,
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )

    bus_task = asyncio.create_task(bus.run())
    await loop.run("hey", "fast", source="voice")
    await bus.drain()
    bus.stop()
    bus_task.cancel()

    thinking = [
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    ]
    assert any("phase=drop" in t and "mode=speak" in t for t in thinking)
    assert not any("phase=summarize" in t for t in thinking)
    assert not any("summarizing earlier turns" in t for t in thinking)
    assert memory.summary == ""
    assert len(memory.messages) < before
    # Only the answer pass - no compress pass that feeds "New excerpt to fold in".
    assert len(provider.calls) == 1
    assert EventType.ASSISTANT_DONE in [e.type for e in events]
    assert EventType.ERROR not in [e.type for e in events]
