"""Ceiling close: finish from tool results instead of starting another search."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from arelis.core.agent_loop import _CLOSE_PARTIAL, AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.ui.turn_watchdog import _begin_close, on_hung_turn
from arelis.ui.window_const import HUNG_CLOSE_GRACE_S
from tests.hardening_helpers import _collect, _config, _ScriptedRouter


class _ClosingScrape:
    name = "scrape"
    description = "fetch a page"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
    }

    def __init__(self) -> None:
        self.loop: AgentLoop | None = None

    async def run(self, **kwargs: object) -> ToolResult:
        del kwargs
        assert self.loop is not None
        self.loop.request_close()
        return ToolResult(ok=True, output="CH4 detected at about 5 sigma.")


def _native(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "arguments": arguments}}


class _CountingTool:
    def __init__(
        self,
        name: str,
        risk: str,
        schema: dict[str, Any],
        *,
        output: str | None = None,
    ) -> None:
        self.name = name
        self.description = name
        self.risk = risk
        self.parameters_schema = schema
        self.output = output
        self.runs = 0
        self.kwargs: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        self.kwargs.append(dict(kwargs))
        if self.output is not None:
            return ToolResult(ok=True, output=self.output)
        if self.name == "plot":
            return ToolResult(
                ok=True,
                output="Wrote series.png (line, 120 points) in plots.",
            )
        return ToolResult(ok=True, output=f"{self.name} ran")


class _CloseDuringStream(_ScriptedRouter):
    """Close after a finished call is already on the wire, then a metrics chunk."""

    def __init__(self, call: dict[str, Any]) -> None:
        super().__init__([[]])
        self.call = call
        self.loop: AgentLoop | None = None

    async def stream(self, role, messages, **kwargs):
        del role, messages, kwargs
        self.i += 1
        if self.i == 1:
            yield ("tool_calls", [self.call])
            assert self.loop is not None
            self.loop.request_close()
            yield ("metrics", {"prompt_eval_count": 8})
            return
        yield ("metrics", {"prompt_eval_count": 1})


class _StopDuringStream(_ScriptedRouter):
    """Close lands, then the user hits Stop before the stream ends."""

    def __init__(self, call: dict[str, Any], cancel: list[bool]) -> None:
        super().__init__([[]])
        self.call = call
        self.cancel = cancel
        self.loop: AgentLoop | None = None
        self.resumed_after_stop = False

    async def stream(self, role, messages, **kwargs):
        del role, messages, kwargs
        self.i += 1
        if self.i > 1:
            self.resumed_after_stop = True
            yield ("token", "should not be asked")
            return
        yield ("tool_calls", [self.call])
        assert self.loop is not None
        self.loop.request_close()
        yield ("thinking", "still drawing")
        self.cancel[0] = True
        yield ("metrics", {"prompt_eval_count": 3})
        self.resumed_after_stop = True


class _HangAfterClose(_ScriptedRouter):
    """A keepalive after close, then a real hang. Grace is what ends it."""

    def __init__(self) -> None:
        super().__init__([[]])
        self.loop: AgentLoop | None = None
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.streams = 0

    async def stream(self, role, messages, **kwargs):
        del role, messages, kwargs
        self.streams += 1
        self.i += 1
        yield ("metrics", {"prompt_eval_count": 1})
        if self.loop is not None and self.streams == 1:
            self.loop.request_close()
        yield ("metrics", {"prompt_eval_count": 2})
        self.entered.set()
        await self.release.wait()
        yield (
            "tool_calls",
            [_native("plot", {"action": "line", "xs": "1", "ys": "2", "out": "h.png"})],
        )


def _agent(
    router: _ScriptedRouter,
    tool: _CountingTool,
    *,
    confirm,
    cancel,
    ask_is_grant: bool = True,
    extra: list[_CountingTool] | None = None,
    router_removed: bool = False,
) -> tuple[EventBus, AgentLoop]:
    bus = EventBus()
    tools = ToolRegistry()
    tools.register(tool)
    for other in extra or []:
        tools.register(other)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["intent_preflight"] = False
    cfg["agent"]["max_rounds"] = 4
    cfg["agent"]["sms_preinject"] = False
    cfg["agent"]["sms_force_call"] = False
    cfg["agent"]["ask_is_grant"] = ask_is_grant
    # PR 234 removes the router, so round 1 is a model call. Preinject stays off.
    if router_removed:
        cfg["agent"]["compensation"] = {"regex_routing": False}
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=confirm,
        is_cancelled=lambda: bool(cancel[0]),
    )
    return bus, loop


def _done_text(events) -> str:
    done = [e for e in events if e.type == EventType.ASSISTANT_DONE]
    assert done, "turn published no reply"
    return str(done[-1].payload.get("text") or "")


def _plot_call() -> dict[str, Any]:
    xs = ",".join(str(i) for i in range(120))
    ys = ",".join(str((i * 3) % 17) for i in range(120))
    return _native(
        "plot",
        {"action": "line", "xs": xs, "ys": ys, "out": "series.png"},
    )


@pytest.mark.asyncio
async def test_close_during_send_still_shows_the_confirm_card() -> None:
    send = _CountingTool(
        "send_sms",
        "side_effect",
        {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "body": {"type": "string"},
            },
        },
    )
    router = _CloseDuringStream(
        _native("send_sms", {"to": "me", "body": "on my way"})
    )
    confirmed: list[str] = []

    async def decline(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
        del cid, args, summary
        confirmed.append(tool)
        return "skip"

    bus, loop = _agent(router, send, confirm=decline, cancel=[False])
    router.loop = loop
    await _collect(bus, loop.run("text me: on my way", "fast"))
    assert confirmed == ["send_sms"]
    assert send.runs == 0


class _ArmStopAndClose(_ScriptedRouter):
    """Stop and close land after the step boundary, before the stream."""

    def __init__(self, cancel: list[bool]) -> None:
        super().__init__([[("token", "should not be asked")]])
        self.cancel = cancel
        self.loop: AgentLoop | None = None
        self.model_calls = 0

    def model_for(self, role=None):
        del role
        self.model_calls += 1
        # Prepare asks once. The next ask is inside the step, before stream.
        if self.model_calls == 2 and self.loop is not None:
            self.loop.request_close()
            self.cancel[0] = True
        return "mock"


@pytest.mark.asyncio
async def test_stop_and_close_before_the_step_stops() -> None:
    """Both flags are set before the model step starts.

    The pre-stream close raises, and the handler must turn that into Stop.
    A close pass would stream again and say it is closing.
    """
    plot = _CountingTool(
        "plot",
        "write",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "xs": {"type": "string"},
                "ys": {"type": "string"},
                "out": {"type": "string"},
            },
        },
    )
    cancel = [False]
    router = _ArmStopAndClose(cancel)

    async def allow(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
        del cid, tool, args, summary
        return "allow"

    bus, loop = _agent(router, plot, confirm=allow, cancel=cancel)
    router.loop = loop
    events = await _collect(bus, loop.run("make a plot of these counts", "fast"))
    text = _done_text(events)
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    assert router.model_calls >= 2
    assert cancel[0] is True
    assert router.i == 0
    assert "closing with what I have" not in thinking
    assert plot.runs == 0
    assert text == "Stopped."
    assert text != _CLOSE_PARTIAL


class _GraceClock:
    """Single-shot stand-in for the grace QTimer. fire() is its timeout."""

    def __init__(self) -> None:
        self.ms: int | None = None
        self.active = False
        self.fired = 0
        self._cb = None

    def start(self, ms: int) -> None:
        self.ms = int(ms)
        self.active = True

    def isActive(self) -> bool:
        return self.active

    def stop(self) -> None:
        self.active = False

    def remainingTime(self) -> int:
        return int(self.ms or 0)

    def fire(self) -> None:
        self.fired += 1
        callback = self._cb
        self.active = False
        if callable(callback):
            callback()


def _grace_window(clock: _GraceClock) -> SimpleNamespace:
    return SimpleNamespace(
        _hung_watchdog=clock,
        _hung_paused_ms=None,
        _hung_closing=False,
        _turn_busy=True,
        _force_quit=False,
        _disposed=False,
        _confirm_waiting=False,
        _assistant_streaming=False,
        thinking=SimpleNamespace(append=lambda *a, **k: None),
        chat=SimpleNamespace(show_progress=lambda *a, **k: None),
        config={},
    )


@pytest.mark.asyncio
async def test_hung_close_grace_fires_when_the_stream_hangs() -> None:
    """The 180s grace clock is what ends a stream that stays hung after close.

    The loop is blocked inside the original stream. Firing the armed grace
    clock hard-cancels that task. Nothing else releases the hang.
    """
    assert HUNG_CLOSE_GRACE_S == 180
    plot = _CountingTool(
        "plot",
        "read",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "xs": {"type": "string"},
                "ys": {"type": "string"},
                "out": {"type": "string"},
            },
        },
    )
    router = _HangAfterClose()
    cancel = [False]

    async def allow(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
        del cid, tool, args, summary
        return "allow"

    bus, loop = _agent(router, plot, confirm=allow, cancel=cancel)
    router.loop = loop
    clock = _GraceClock()
    window = _grace_window(clock)
    task_box: dict[str, asyncio.Task[None]] = {}

    def _cancel_turn(*, schedule_next: bool, reason: str = "stop") -> None:
        del schedule_next
        if reason != "hung":
            return
        cancel[0] = True
        running = task_box.get("task")
        if running is not None and not running.done():
            running.cancel()

    window._cancel_turn = _cancel_turn
    window._set_busy = lambda _busy: None
    window._on_hung_turn = lambda: on_hung_turn(window)
    clock._cb = window._on_hung_turn

    events: list[Any] = []

    async def capture(event: Any) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    runner = asyncio.create_task(bus.run())
    task = asyncio.create_task(loop.run("make a plot of these counts", "fast"))
    task_box["task"] = task
    try:
        await asyncio.wait_for(router.entered.wait(), timeout=5)
        # Close already landed and the original stream is still hung.
        assert router.streams == 1
        _begin_close(window, loop)
        assert window._hung_closing is True
        assert clock.ms == HUNG_CLOSE_GRACE_S * 1000
        assert clock.isActive()
        # The grace interval elapsed. This is the clock's timeout.
        clock.fire()
        assert clock.fired == 1
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        router.release.set()
    await bus.drain()
    bus.stop()
    runner.cancel()
    text = _done_text(events)
    assert plot.runs == 0
    assert router.streams == 1
    assert text == "Stopped."
    assert text != _CLOSE_PARTIAL


class _SendThenShutTools(_ScriptedRouter):
    """Round 1 is the model. Close lands on a finished send. Later rounds
    try tools the send already shut off, including one the wrap-up list allows.
    """

    def __init__(
        self,
        send_call: dict[str, Any],
        later: list[dict[str, Any]],
        *,
        later_prose: str = "",
        mark_reask: bool = False,
    ) -> None:
        super().__init__([[]])
        self.send_call = send_call
        self.later = later
        self.later_prose = later_prose
        self.mark_reask = mark_reask
        self.loop: AgentLoop | None = None

    async def stream(self, role, messages, **kwargs):
        del role, messages, kwargs
        self.i += 1
        if self.i == 1:
            if self.mark_reask and self.loop is not None:
                turn = getattr(self.loop, "_active_turn", None)
                if turn is not None:
                    turn.plain_reask_used = True
            yield ("tool_calls", [self.send_call])
            assert self.loop is not None
            self.loop.request_close()
            yield ("metrics", {"prompt_eval_count": 4})
            return
        if self.later_prose:
            yield ("token", self.later_prose)
        yield ("tool_calls", list(self.later))
        yield ("metrics", {"prompt_eval_count": 2})


_CLOSE_PROSE = "Already sent."


def _sms_tool() -> _CountingTool:
    return _CountingTool(
        "send_sms",
        "side_effect",
        {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "body": {"type": "string"},
            },
        },
        output="Sent.",
    )


def _thinking(events) -> str:
    return " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )


