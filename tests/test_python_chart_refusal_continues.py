"""A python chart refusal keeps plot owed until plot is tried.

The marker is ``data["next_tool"] == "plot"`` on the python tool result.
Later python calls do not clear it. Two extra rounds is the cap. A python
call that returns no result data ends sooner. The refusal sentence and the
user text are not consulted.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.loop_helpers import CHART_FAILED_REPLY
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.python_exec import PythonTool
from tests.hardening_helpers import _collect, _config, _ScriptedRouter

_ASK = (
    "Compute the squares of 1 through 8 with python, plot a line chart, "
    "then write a markdown document."
)
_MODES = [
    pytest.param(False, id="native-off"),
    pytest.param(True, id="native-on"),
]


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "arguments": arguments}}


class _Rec:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.last: ToolResult | None = None


class _Plot:
    name = "plot"
    description = "draw a chart"
    risk = "write"
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "xs": {"type": "string"},
            "ys": {"type": "string"},
            "out": {"type": "string"},
        },
    }

    def __init__(self, rec: _Rec, *, ok: bool = True) -> None:
        self.rec = rec
        self._ok = ok

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        self.rec.calls.append("plot")
        if self._ok:
            return ToolResult(
                ok=True,
                output="Wrote squares.png",
                data={"path": "squares.png"},
            )
        return ToolResult(ok=False, output="ys must be numbers, not an expression.")


class _Document:
    name = "document"
    description = "write a document"
    risk = "write"
    parameters_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "format": {"type": "string"},
        },
    }

    def __init__(self, rec: _Rec) -> None:
        self.rec = rec

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        self.rec.calls.append("document")
        return ToolResult(
            ok=True,
            output="Wrote outputs/documents/Squares.md",
            data={"path": "outputs/documents/Squares.md"},
        )


class _Python:
    name = "python"
    description = "run python"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
    }

    def __init__(self, rec: _Rec, *, marker: bool, words: bool) -> None:
        self.rec = rec
        self.marker = marker
        self.words = words

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        self.rec.calls.append("python")
        if self.words:
            output = (
                "Python refused: import 'matplotlib' is not allowed in this cell. "
                "Call plot with the data: pass xs and ys as comma-separated numbers "
                "and out='name.png'."
            )
        else:
            output = "Python refused: blocked."
        data: dict[str, Any] = {}
        if self.marker:
            data = {"refusal": "chart_import", "next_tool": "plot"}
        result = ToolResult(ok=False, output=output, data=data)
        self.rec.last = result
        return result


class _PythonSteps:
    """Scripted python results. Each call takes the next result."""

    name = "python"
    description = "run python"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"code": {"type": "string"}},
    }

    def __init__(self, rec: _Rec, steps: list[ToolResult]) -> None:
        self.rec = rec
        self.steps = steps
        self.i = 0

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        self.rec.calls.append("python")
        result = self.steps[min(self.i, len(self.steps) - 1)]
        self.i += 1
        self.rec.last = result
        return result


def _refusal(*, words: bool) -> ToolResult:
    if words:
        output = (
            "Python refused: import 'matplotlib' is not allowed in this cell. "
            "Call plot with the data: pass xs and ys as comma-separated numbers "
            "and out='name.png'."
        )
    else:
        output = "Python refused: blocked."
    return ToolResult(
        ok=False,
        output=output,
        data={"refusal": "chart_import", "next_tool": "plot"},
    )


def _redo(text: str = "1, 4, 9, 16, 25, 36, 49, 64") -> ToolResult:
    return ToolResult(
        ok=True,
        output=text,
        data={"code": "print(squares)", "result": text},
    )


def _no_data() -> ToolResult:
    return ToolResult(ok=False, output="Python failed: the cell stopped.", data={})


class _RealPython(PythonTool):
    def __init__(self, rec: _Rec) -> None:
        self.rec = rec

    async def run(self, **kwargs: Any) -> ToolResult:
        result = await super().run(**kwargs)
        self.rec.calls.append("python")
        self.rec.last = result
        return result


async def _allow(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
    del cid, tool, args, summary
    return "allow"


def _loop(
    router: _ScriptedRouter,
    tools: ToolRegistry,
    *,
    native: bool,
) -> tuple[EventBus, AgentLoop]:
    bus = EventBus()
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 6
    cfg["agent"]["intent_preflight"] = False
    cfg["agent"]["native_tool_calling"] = native
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    return bus, loop


def _done(events: list[Any]) -> str:
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    return str(done.payload.get("text") or "")


def _tools(rec: _Rec, python_tool: Any, *, plot_ok: bool = True) -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(python_tool)
    tools.register(_Plot(rec, ok=plot_ok))
    tools.register(_Document(rec))
    return tools


_PLOT = {"action": "line", "xs": "1,2,3,4,5,6,7,8", "ys": "1,4,9,16,25,36,49,64", "out": "squares.png"}
_DOC = {"title": "Squares", "body": "1, 4, 9, 16, 25, 36, 49, 64", "format": "md"}


@pytest.mark.asyncio
@pytest.mark.parametrize("native", _MODES)
async def test_real_matplotlib_refusal_gets_one_plot_round(
    native: bool
) -> None:
    rec = _Rec()
    router = _ScriptedRouter(
        [
            [("tool_calls", [_call("python", {"code": "import matplotlib"})])],
            [("tool_calls", [_call("plot", _PLOT)])],
            [("tool_calls", [_call("document", _DOC)])],
            [("token", "The chart and the note are ready.")],
        ]
    )
    bus, loop = _loop(
        router,
        _tools(rec, _RealPython(rec)),
        native=native,
    )
    events = await _collect(bus, loop.run(_ASK, "fast"))
    assert rec.last is not None
    assert rec.last.data.get("next_tool") == "plot"
    assert rec.calls == ["python", "plot", "document"]
    assert CHART_FAILED_REPLY not in _done(events)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", _MODES)
async def test_refusal_then_python_redo_then_plot(
    native: bool
) -> None:
    """A python call that returns data keeps plot owed, so plot still runs."""
    rec = _Rec()
    router = _ScriptedRouter(
        [
            [("tool_calls", [_call("python", {"code": "import matplotlib"})])],
            [("tool_calls", [_call("python", {"code": "print(squares)"})])],
            [("tool_calls", [_call("plot", _PLOT)])],
            [("tool_calls", [_call("document", _DOC)])],
            [("token", "The chart and the note are ready.")],
        ]
    )
    bus, loop = _loop(
        router,
        _tools(rec, _PythonSteps(rec, [_refusal(words=True), _redo()])),
        native=native,
    )
    events = await _collect(bus, loop.run(_ASK, "fast"))
    assert rec.last is not None
    assert rec.last.ok is True
    assert "result" in rec.last.data
    assert "next_tool" not in rec.last.data
    assert rec.calls == ["python", "python", "plot", "document"]
    assert CHART_FAILED_REPLY not in _done(events)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", _MODES)
async def test_chart_words_without_the_marker_do_not_stop_the_turn(
    native: bool
) -> None:
    rec = _Rec()
    router = _ScriptedRouter(
        [
            [("tool_calls", [_call("python", {"code": "import matplotlib"})])],
            [("tool_calls", [_call("plot", _PLOT)])],
            [("token", "The chart is ready.")],
        ]
    )
    bus, loop = _loop(
        router,
        _tools(rec, _Python(rec, marker=False, words=True)),
        native=native,
    )
    events = await _collect(bus, loop.run(_ASK, "fast"))
    assert rec.calls == ["python", "plot"]
    assert CHART_FAILED_REPLY not in _done(events)


@pytest.mark.asyncio
@pytest.mark.parametrize("native", _MODES)
async def test_no_extra_round_when_plot_was_already_tried(
    native: bool
) -> None:
    rec = _Rec()
    router = _ScriptedRouter(
        [
            [("tool_calls", [_call("plot", _PLOT)])],
            [("tool_calls", [_call("python", {"code": "import matplotlib"})])],
            [("tool_calls", [_call("plot", _PLOT)])],
            [("token", "")],
            [("token", "")],
        ]
    )
    bus, loop = _loop(
        router,
        _tools(rec, _Python(rec, marker=True, words=False), plot_ok=False),
        native=native,
    )
    events = await _collect(bus, loop.run(_ASK, "fast"))
    assert rec.calls == ["plot", "python"]
    assert _done(events) == CHART_FAILED_REPLY
    assert router.i == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("native", _MODES)
async def test_two_data_redos_spend_the_cap_before_plot(
    native: bool
) -> None:
    """Two python calls that return data use the cap. Plot does not get a third."""
    rec = _Rec()
    router = _ScriptedRouter(
        [
            [("tool_calls", [_call("python", {"code": "import matplotlib"})])],
            [("tool_calls", [_call("python", {"code": "print(squares)"})])],
            [("tool_calls", [_call("python", {"code": "print(list(squares))"})])],
            [("tool_calls", [_call("plot", _PLOT)])],
            [("token", "The chart is ready.")],
        ]
    )
    bus, loop = _loop(
        router,
        _tools(rec, _PythonSteps(rec, [_refusal(words=True), _redo(), _redo()])),
        native=native,
    )
    events = await _collect(bus, loop.run(_ASK, "fast"))
    assert rec.calls == ["python", "python", "python"]
    assert _done(events) == CHART_FAILED_REPLY
    assert router.i == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("native", _MODES)
async def test_python_redo_without_data_ends_before_plot(
    native: bool
) -> None:
    """A later python call with no result data ends the owed plot."""
    rec = _Rec()
    router = _ScriptedRouter(
        [
            [("tool_calls", [_call("python", {"code": "import matplotlib"})])],
            [("tool_calls", [_call("python", {"code": "print(squares)"})])],
            [("tool_calls", [_call("plot", _PLOT)])],
            [("token", "The chart is ready.")],
        ]
    )
    bus, loop = _loop(
        router,
        _tools(rec, _PythonSteps(rec, [_refusal(words=True), _no_data()])),
        native=native,
    )
    events = await _collect(bus, loop.run(_ASK, "fast"))
    assert rec.last is not None
    assert rec.last.ok is False
    assert "result" not in rec.last.data
    assert rec.calls == ["python", "python"]
    assert _done(events) == CHART_FAILED_REPLY
    assert router.i == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("native", _MODES)
async def test_only_one_extra_round_when_plot_is_not_called(
    native: bool
) -> None:
    rec = _Rec()
    router = _ScriptedRouter(
        [
            [("tool_calls", [_call("python", {"code": "import matplotlib"})])],
            [("tool_calls", [_call("python", {"code": "print(1)"})])],
            [("tool_calls", [_call("plot", _PLOT)])],
            [("token", "The chart is ready.")],
        ]
    )
    bus, loop = _loop(
        router,
        _tools(rec, _Python(rec, marker=True, words=True)),
        native=native,
    )
    events = await _collect(bus, loop.run(_ASK, "fast"))
    assert rec.calls == ["python", "python"]
    assert _done(events) == CHART_FAILED_REPLY
    assert router.i == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("native", _MODES)
async def test_failed_plot_on_the_extra_round_ends_the_turn(
    native: bool
) -> None:
    rec = _Rec()
    router = _ScriptedRouter(
        [
            [("tool_calls", [_call("python", {"code": "import matplotlib"})])],
            [("tool_calls", [_call("plot", _PLOT)])],
            [("tool_calls", [_call("document", _DOC)])],
            [("token", "")],
        ]
    )
    bus, loop = _loop(
        router,
        _tools(rec, _Python(rec, marker=True, words=True), plot_ok=False),
        native=native,
    )
    events = await _collect(bus, loop.run(_ASK, "fast"))
    assert rec.calls == ["python", "plot"]
    assert _done(events) == CHART_FAILED_REPLY
    assert router.i == 2


def test_pending_round_reads_the_field_not_a_sentence() -> None:
    from arelis.core.evidence import EvidenceLedger
    from arelis.core.loop_helpers import python_plot_round_pending, python_plot_stop_line

    ledger = EvidenceLedger()
    assert python_plot_round_pending(
        next_tool="plot",
        ledger=ledger,
        plot_available=True,
        extra_rounds=0,
    )
    assert python_plot_round_pending(
        next_tool="plot",
        ledger=ledger,
        plot_available=True,
        extra_rounds=1,
    )
    assert (
        python_plot_round_pending(
            next_tool="",
            ledger=ledger,
            plot_available=True,
            extra_rounds=0,
        )
        is False
    )
    assert (
        python_plot_round_pending(
            next_tool="plot",
            ledger=ledger,
            plot_available=True,
            extra_rounds=1,
            python_returned_data=False,
        )
        is False
    )
    assert (
        python_plot_stop_line(
            next_tool="plot",
            ledger=ledger,
            plot_available=True,
            extra_rounds=0,
        )
        is None
    )
    assert (
        python_plot_stop_line(
            next_tool="plot",
            ledger=ledger,
            plot_available=True,
            extra_rounds=1,
            python_returned_data=False,
        )
        == CHART_FAILED_REPLY
    )
    assert (
        python_plot_stop_line(
            next_tool="plot",
            ledger=ledger,
            plot_available=True,
            extra_rounds=1,
            idle_round=True,
        )
        == CHART_FAILED_REPLY
    )
    assert (
        python_plot_stop_line(
            next_tool="plot",
            ledger=ledger,
            plot_available=True,
            extra_rounds=2,
        )
        == CHART_FAILED_REPLY
    )
    ledger.record_tool("plot", ok=False, output="nope", data={})
    assert (
        python_plot_round_pending(
            next_tool="plot",
            ledger=ledger,
            plot_available=True,
            extra_rounds=0,
        )
        is False
    )
    assert (
        python_plot_stop_line(
            next_tool="plot",
            ledger=ledger,
            plot_available=True,
            extra_rounds=0,
        )
        == CHART_FAILED_REPLY
    )
    ledger.record_tool("plot", ok=True, output="Wrote a.png", data={"path": "a.png"})
    assert (
        python_plot_stop_line(
            next_tool="plot",
            ledger=ledger,
            plot_available=True,
            extra_rounds=1,
        )
        is None
    )
