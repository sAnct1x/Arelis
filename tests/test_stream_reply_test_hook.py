"""ARELIS_TEST_STREAM_REPLY=1: a tool round's answer paints as it streams (harness hook), so a
test run can watch paragraphs land one at a time; held, the whole reply lands in one frame."""

from __future__ import annotations

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry
from tests.hardening_helpers import _collect, _config, _deny
from tests.test_tool_trace_leak import _CopyLastAssistant

_PARAS = ["First paragraph.\n\n", "Second paragraph.\n\n", "Third paragraph."]


class _ThreeParagraphs(_CopyLastAssistant):
    async def stream(self, role, messages, **kwargs):
        del role, messages, kwargs
        for chunk in _PARAS:
            yield ("token", chunk)


async def test_the_hook_streams_a_tool_rounds_answer(monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_TEST_STREAM_REPLY", "1")
    bus = EventBus()
    loop = AgentLoop(
        bus,
        _ThreeParagraphs(),  # type: ignore[arg-type]
        ToolRegistry(),
        SessionMemory(),
        "persona",
        _config(),
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    tool = {"type": "function", "function": {"name": "noop", "parameters": {"type": "object"}}}
    msgs = [{"role": "user", "content": "hi"}]
    events = await _collect(bus, loop._stream_round("fast", msgs, [tool], expect_tools=True))
    deltas = [e for e in events if e.type == EventType.ASSISTANT_DELTA]
    assert len(deltas) >= 2  # painted as it came, not held for the end
    assert "Third paragraph." in "".join(str(e.payload.get("text") or "") for e in deltas)
