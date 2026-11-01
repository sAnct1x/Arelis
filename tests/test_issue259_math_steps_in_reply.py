"""#259: worked steps written beside a tool call stay in the final reply."""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter

_STEPS = "z = sqrt((1+beta)/(1-beta)) - 1 with beta = 0.1, so sqrt(1.1/0.9) - 1."
_WRAP = "With beta = 0.1, 1 + beta = 1.1 and 1 - beta = 0.9, so z is about 0.1054."


class _Calc:
    name = "calculator"
    description = "arithmetic"
    risk = "read"
    parameters_schema = {"type": "object", "properties": {"expr": {"type": "string"}}}

    async def run(self, **kwargs: Any) -> ToolResult:
        return ToolResult(ok=True, output="0.105409255338946")


@pytest.mark.asyncio
async def test_steps_from_an_earlier_round_stay_in_the_reply() -> None:
    call = {
        "type": "function",
        "function": {"name": "calculator", "arguments": {"expr": "sqrt(1.1/0.9)-1"}},
    }
    router = _ScriptedRouter([[("token", _STEPS), ("tool_calls", [call])], [("token", _WRAP)]])
    tools = ToolRegistry()
    tools.register(_Calc())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
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
    done = [e.payload["text"] for e in events if e.type == EventType.ASSISTANT_DONE][-1]
    assert _STEPS in done
    assert _WRAP in done
    saved = [m for m in loop.memory.messages if m.role == "assistant"][-1].content
    assert _STEPS in saved
