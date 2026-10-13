"""A failed chart must end the turn. It must not sit until the model goes quiet."""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter

_ASK = "Make a poster with subplots: a line chart and a histogram of these counts."
_CHART = "The chart did not get drawn. I will not fake one in text."
_MATPLOTLIB = (
    "Python refused: import 'matplotlib' is not allowed in this cell. "
    "Compute xs and ys here (print comma-separated numbers), "
    "then call plot with those series and out='name.png'."
)


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "arguments": arguments}}


class _FailPlot:
    name = "plot"
    description = "draw a chart"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "panels": {"type": "string"},
            "xs": {"type": "string"},
            "ys": {"type": "string"},
            "look": {"type": "string"},
            "out": {"type": "string"},
        },
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(
            ok=False,
            output='ys must be numbers, e.g. ys="1,2,3" (or a ys list), not an expression.',
        )


class _FailPython:
    name = "python"
    description = "run python"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(ok=False, output=_MATPLOTLIB)


class _CloseAfterSecond(_ScriptedRouter):
    """Ask the turn to close once the second scripted call has been yielded."""

    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        super().__init__(script)
        self.loop: AgentLoop | None = None

    async def stream(self, role, messages, **kwargs):
        upcoming = self.i
        async for item in super().stream(role, messages, **kwargs):
            yield item
            if upcoming == 1 and self.loop is not None:
                self.loop.request_close()


def _loop(router: _ScriptedRouter) -> tuple[EventBus, AgentLoop]:
    bus = EventBus()
    tools = ToolRegistry()
    tools.register(_FailPlot())
    tools.register(_FailPython())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 6
    cfg["agent"]["intent_preflight"] = False
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


def _done_text(events) -> str:
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    return str(done.payload.get("text") or "")


def _assert_honest(text: str) -> None:
    assert text == _CHART
    assert "empty reply" not in text
    assert "did not finish every source" not in text
    assert "tool-step limit" not in text
    assert "\u2014" not in text
    assert "\u2013" not in text


@pytest.mark.asyncio
async def test_plot_then_blocked_python_stops_before_the_empty_stream() -> None:
    router = _ScriptedRouter(
        [
            [("tool_calls", [_call("plot", {"action": "subplots", "ys": "[[1,2],[3,4]]"})])],
            [("tool_calls", [_call("python", {"code": "import matplotlib.pyplot as plt"})])],
            [("token", "")],
            [("token", "")],
            [("token", "")],
            [("token", "")],
        ]
    )
    bus, loop = _loop(router)
    events = await _collect(bus, loop.run(_ASK, "fast"))
    _assert_honest(_done_text(events))
    assert router.i == 2


@pytest.mark.asyncio
async def test_close_after_plot_failures_does_not_invent_a_partial() -> None:
    router = _CloseAfterSecond(
        [
            [("tool_calls", [_call("plot", {"action": "subplots", "panels": ["line", "histogram"]})])],
            [("tool_calls", [_call("plot", {"action": "line", "ys": [[1, 2], [3, 4]]})])],
            [("token", "")],
        ]
    )
    bus, loop = _loop(router)
    router.loop = loop
    events = await _collect(bus, loop.run(_ASK, "fast"))
    _assert_honest(_done_text(events))
    assert router.i == 2
