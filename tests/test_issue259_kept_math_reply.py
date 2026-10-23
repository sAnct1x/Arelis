"""#259: worked math streamed before a tool stay in the reply.

On 0.3.2 every tool round retracted the draft and copied it into thinking.
#372 left a native draft on screen, but _finish still published only the
last-round wrap-up, so ASSISTANT_DONE replaced the steps and history
saved that wrap-up. Mutation: make _final_from_painted_draft return its
final argument unchanged (1/1).
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter

pytestmark = pytest.mark.no_ui

_STEPS = (
    "Relativistic Doppler redshift at v=0.1c: "
    "z = sqrt((1+beta)/(1-beta)) - 1 with beta=0.1. "
    "sqrt(1.1/0.9)-1 = 0.1054092553."
)
_WRAP = "So the redshift is about 0.1054."


class _Cas:
    name = "cas"
    description = "algebra"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}, "expr": {"type": "string"}},
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        expr = str(kwargs.get("expr") or "")
        return ToolResult(ok=True, output=f"latex: {expr}\n0.105409255338946")


@pytest.mark.asyncio
async def test_kept_math_draft_stays_in_the_reply() -> None:
    first = {
        "type": "function",
        "function": {
            "name": "cas",
            "arguments": {
                "action": "simplify",
                "expr": "sqrt((1+0.1)/(1-0.1))-1",
            },
        },
    }
    second = {
        "type": "function",
        "function": {
            "name": "cas",
            "arguments": {
                "action": "simplify",
                "expr": "1/sqrt(1-0.1**2)",
            },
        },
    }
    router = _ScriptedRouter(
        [
            [("thinking", _STEPS), ("tool_calls", [first])],
            [("thinking", _STEPS), ("token", _STEPS), ("tool_calls", [second])],
            [("token", _WRAP)],
        ]
    )
    tools = ToolRegistry()
    tools.register(_Cas())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 8
    bus = EventBus()
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
    events = await _collect(bus, loop.run("what is the redshift at 0.1c", "fast"))
    dones = [
        str(event.payload.get("text") or "")
        for event in events
        if event.type == EventType.ASSISTANT_DONE
    ]
    thinking = [
        str(event.payload.get("text") or "")
        for event in events
        if event.type == EventType.THINKING
    ]
    assert dones, "turn never finished"
    assert _STEPS in dones[-1]
    assert _WRAP in dones[-1]
    saved = [m for m in loop.memory.messages if m.role == "assistant"]
    assert saved, "history never stored the reply"
    assert _STEPS in saved[-1].content
    assert _WRAP in saved[-1].content
    assert not any(line.startswith("preamble  ") for line in thinking)
