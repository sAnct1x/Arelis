"""The tool-trace marker must not ship as her reply.

A qwen3.5:9b session did this: weather in Springfield, then "save that as a
doc", then "add a note to it: bring an umbrella". The third bubble contained
the internal trace, including a receipt line. That string is built for the
next prompt. It was spliced onto the assistant message, so the model read it
as something she had already said and copied it.
"""

from __future__ import annotations

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory, tool_trace_entry, tool_trace_note
from arelis.core.receipts import action_receipt, format_action_receipt
from arelis.tools.base import ToolRegistry
from tests.hardening_helpers import _collect, _config, _deny

_MARKER = "tools used this turn"


def _doc_note() -> str:
    """The trace a document save actually stores, receipt line included."""
    receipt = action_receipt(
        "document",
        ok=True,
        args={"path": "springfield-weather.md"},
        data={"path": "springfield-weather.md"},
    )
    assert receipt is not None
    return tool_trace_note(
        [
            tool_trace_entry(
                "document",
                {"path": "springfield-weather.md"},
                True,
            ),
            format_action_receipt(receipt),
        ]
    )


def _after_weather_and_doc() -> SessionMemory:
    """History the third turn sees. Notes stay on the assistant rows."""
    memory = SessionMemory()
    memory.add("user", "What's the weather in Springfield, Illinois?")
    memory.add(
        "assistant",
        "Springfield, Illinois is 52F and rainy.",
        note=tool_trace_note(
            [tool_trace_entry("weather", {"query": "Springfield, Illinois"}, True)]
        ),
    )
    memory.add("user", "save that as a doc")
    memory.add(
        "assistant",
        "Saved the Springfield weather as a doc.",
        note=_doc_note(),
    )
    return memory


def test_trace_marker_is_not_assistant_speech() -> None:
    """Copying the last assistant message must not carry the marker.

    That copy is the leak. The path still has to reach the model, on a
    different role, or the next turn cannot find the file.
    """
    prompt = _after_weather_and_doc().as_chat()
    assistant = [row for row in prompt if row["role"] == "assistant"]
    assert assistant
    copied = str(assistant[-1]["content"])
    assert _MARKER not in copied
    assert "receipt  action=" not in copied
    assert copied == "Saved the Springfield weather as a doc."
    traces = [
        row
        for row in prompt
        if row["role"] != "assistant" and _MARKER in str(row.get("content") or "")
    ]
    assert traces
    assert traces[-1]["role"] == "system"
    assert "springfield-weather.md" in traces[-1]["content"]
    assert "receipt  action=" in traces[-1]["content"]


class _CopyLastAssistant:
    """qwen's failure: the next reply is the previous assistant message."""

    def __init__(self) -> None:
        self.seen: list[list[dict]] = []
        self.default_role = "fast"
        self.active_model = None
        self.active_role = None
        self.models = {"fast": "mock", "research": "mock", "code": "mock"}

    def model_for(self, role=None):
        del role
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        self.active_role = role
        self.active_model = "mock"
        return "mock"

    def mark_sticky(self, role) -> None:
        del role
        return None

    def apply_sticky(self, wanted, reason: str):
        return wanted, reason

    async def stream(self, role, messages, **kwargs):
        del role, kwargs
        self.seen.append([dict(item) for item in messages])
        copied = ""
        for message in reversed(messages):
            if message.get("role") == "assistant":
                copied = str(message.get("content") or "")
                break
        yield ("token", copied)


async def test_copied_history_does_not_reach_the_user() -> None:
    """Third turn of the reported chain. The bubble is the copied reply."""
    router = _CopyLastAssistant()
    bus = EventBus()
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 4
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        ToolRegistry(),
        _after_weather_and_doc(),
        "persona",
        cfg,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(
        bus,
        loop.run("add a note to it: bring an umbrella", "fast"),
    )
    done = next(event for event in events if event.type == EventType.ASSISTANT_DONE)
    reply = str(done.payload.get("text") or "")
    assert _MARKER not in reply
    assert "receipt  action=" not in reply
    assert router.seen, "the turn never asked the model"
    first = router.seen[0]
    assert any(
        row.get("role") == "system" and _MARKER in str(row.get("content") or "")
        for row in first
    )
    assert all(
        _MARKER not in str(row.get("content") or "")
        for row in first
        if row.get("role") == "assistant"
    )


def _three_turns() -> SessionMemory:
    memory = SessionMemory(max_messages=10_000)
    memory.add("user", "q1")
    memory.add("assistant", "a1", note="[tools used this turn: weather]")
    memory.add("user", "q2")
    memory.add("assistant", "a2", note="[tools used this turn: document weather.md]")
    memory.add("user", "q3")
    memory.add("assistant", "a3", note="[tools used this turn: notes]")
    return memory


async def test_conversation_trim_starts_on_a_user_row() -> None:
    """Spoken turns omit trace notes when they count a drop.

    Three turns are six rows without notes. Dropping four of those must
    leave q3 and a3, and the next history must open on the user. Counting
    the note rows stops one message early and leaves a2 in front.
    """
    cfg = _config()
    cfg["_speak_replies"] = True
    cfg["agent"]["history_max_messages"] = 4
    cfg["agent"]["history_min_recent"] = 1
    cfg["agent"]["summarize_skip_slash"] = True
    cfg["agent"]["chat_fast_path"] = False
    loop = AgentLoop(
        EventBus(),
        _CopyLastAssistant(),  # type: ignore[arg-type]
        ToolRegistry(),
        _three_turns(),
        "persona",
        cfg,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    messages = await loop._messages_for_turn(
        [{"role": "system", "content": "PERSONA"}],
        1_000_000,
        4.0,
        "fast",
    )
    history = [row for row in messages if row.get("content") != "PERSONA"]
    assert history
    assert history[0]["role"] == "user"
    assert [row["content"] for row in history] == ["q3", "a3"]


