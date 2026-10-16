"""A rewritten cell that keeps raising the same type must end the turn.

fail_counts keys the whole argument blob, so each edit looks like a new
call. The stop is the tool result: status=error and the exception type.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry
from arelis.tools.python_exec import PythonTool
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter

_ASK = "Run the cell."
_NOT_THE_ANSWER = "STILL GOING"


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "arguments": arguments}}


class _RecordingPython(PythonTool):
    def __init__(self) -> None:
        self.runs = 0
        self.last = None

    async def run(self, **kwargs: Any):
        self.runs += 1
        result = await super().run(**kwargs)
        self.last = result
        return result


def _loop(router: _ScriptedRouter, tool: _RecordingPython) -> tuple[EventBus, AgentLoop]:
    bus = EventBus()
    tools = ToolRegistry()
    tools.register(tool)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 6
    cfg["agent"]["intent_preflight"] = False
    cfg["agent"]["same_error_limit"] = 3
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
    return bus, loop


@pytest.mark.asyncio
async def test_same_exception_type_ends_on_the_tool_error() -> None:
    tool = _RecordingPython()
    router = _ScriptedRouter(
        [
            [("tool_calls", [_call("python", {"code": "flux"})])],
            [("tool_calls", [_call("python", {"code": "1 + flux"})])],
            [("tool_calls", [_call("python", {"code": "print(flux)"})])],
            [("token", _NOT_THE_ANSWER)],
        ]
    )
    bus, loop = _loop(router, tool)
    events = await _collect(bus, loop.run(_ASK, "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = str(done.payload.get("text") or "")
    assert tool.last is not None
    assert tool.last.data.get("status") == "error"
    assert tool.last.data.get("exception_type") == "NameError"
    assert tool.runs == 3
    assert router.i == 3
    assert text == str(tool.last.output)
    assert _NOT_THE_ANSWER not in text
    assert "was not run because" not in text
    assert "tool-step limit" not in text
