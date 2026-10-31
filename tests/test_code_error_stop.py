"""A cell that keeps failing with the same error must end the turn.

A real exception keys ``{tool}|bad_args|{Class}``. A sandbox refusal keys
its own text, with whitespace collapsed and numbers and paths removed, so
two refusals that differ only by a number still stop. The tool result
keeps the traceback. The reply is the fixed stop line plus the real
message, after the normal finish path.
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
            [("token", _NOT_THE_ANSWER)],
        ]
    )
    bus, loop = _loop(router, tool)
    events = await _collect(bus, loop.run(_ASK, "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = str(done.payload.get("text") or "")
    assert tool.last is not None
    assert tool.last.data.get("status") == "bad_args"
    assert tool.last.data.get("error_type") == "NameError"
    assert "Traceback" in str(tool.last.output)
    assert "NameError" in str(tool.last.output)
    assert tool.last.data.get("exc_message") == "name 'flux' is not defined"
    assert tool.runs == 2
    assert router.i == 2
    assert text == (
        "The code kept failing with the same error, so I stopped: "
        "name 'flux' is not defined"
    )
    assert "Traceback" not in text
    assert "File " not in text
    assert _NOT_THE_ANSWER not in text
    assert "was not run because" not in text
    assert "tool-step limit" not in text

    os_tool = _RecordingPython()
    os_router = _ScriptedRouter(
        [
            [("tool_calls", [_call("python", {"code": "import os"})])],
            [("tool_calls", [_call("python", {"code": "import os"})])],
            [("token", _NOT_THE_ANSWER)],
        ]
    )
    os_bus, os_loop = _loop(os_router, os_tool)
    os_events = await _collect(os_bus, os_loop.run(_ASK, "fast"))
    os_done = next(e for e in os_events if e.type == EventType.ASSISTANT_DONE)
    os_text = str(os_done.payload.get("text") or "")
    assert os_tool.runs == 2
    assert os_router.i == 2
    assert os_tool.last is not None
    assert os_tool.last.data.get("status") == "bad_args"
    refusal = str(os_tool.last.data.get("exc_message") or "")
    assert "numpy" in refusal and "sympy" in refusal
    assert "matplotlib" not in refusal
    assert "are preloaded" not in refusal
    assert os_text == (
        "The code kept failing with the same error, so I stopped: " + refusal
    )
    assert "Traceback" not in os_text
    assert _NOT_THE_ANSWER not in os_text

    from arelis.core.turn_execute import _bad_args_key

    def _refused(text: str, kind: str = "_CellRefusedError") -> dict[str, Any]:
        return {"status": "bad_args", "error_type": kind, "exc_message": text}

    numbered = _bad_args_key(
        "python",
        _refused("blocked write 1 at /tmp/room/results/a.csv"),
    )
    renumbered = _bad_args_key(
        "python",
        _refused("blocked   write\t2 at /tmp/room/results/b.csv", "_CellBlocked"),
    )
    windows = _bad_args_key(
        "python",
        _refused(r"blocked write 3 at C:\room\results\a.csv"),
    )
    assert numbered and numbered == renumbered == windows
    other = _bad_args_key(
        "python",
        _refused("import 'subprocess' is not allowed. os and subprocess are not."),
    )
    assert other and other != numbered
    name_key = _bad_args_key(
        "python",
        {
            "status": "bad_args",
            "error_type": "NameError",
            "exc_message": "name 'flux' is not defined",
        },
    )
    other_name = _bad_args_key(
        "python",
        {
            "status": "bad_args",
            "error_type": "NameError",
            "exc_message": "name 'mass' is not defined",
        },
    )
    assert name_key == other_name == "python|bad_args|NameError"
