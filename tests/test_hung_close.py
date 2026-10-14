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
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter


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


@pytest.mark.asyncio
async def test_close_after_a_tool_does_not_search_again() -> None:
    scrape = _ClosingScrape()
    bus = EventBus()
    router = _ScriptedRouter(
        [
            [
                (
                    "tool_calls",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "scrape",
                                "arguments": {"url": "https://example.com/k2"},
                            },
                        }
                    ],
                )
            ],
            [
                (
                    "token",
                    "Methane is the measurement I actually have. I did not get to the rest.",
                )
            ],
        ]
    )
    tools = ToolRegistry()
    tools.register(scrape)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 8
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
    scrape.loop = loop
    events = await _collect(
        bus,
        loop.run("what did JWST measure in this atmosphere?", "fast"),
    )
    thinking = " ".join(
        str(e.payload.get("text") or "")
        for e in events
        if e.type == EventType.THINKING
    )
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = str(done.payload.get("text") or "")
    assert "closing with what I have" in thinking
    assert "Methane" in text
    assert router.i == 2
    assert "scrape" in loop.tools_used


def _native(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "arguments": arguments}}


class _CountingTool:
    def __init__(self, name: str, risk: str, schema: dict[str, Any]) -> None:
        self.name = name
        self.description = name
        self.risk = risk
        self.parameters_schema = schema
        self.runs = 0
        self.kwargs: list[dict[str, Any]] = []

    async def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        self.kwargs.append(dict(kwargs))
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
) -> tuple[EventBus, AgentLoop]:
    bus = EventBus()
    tools = ToolRegistry()
    tools.register(tool)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["intent_preflight"] = False
    cfg["agent"]["max_rounds"] = 4
    cfg["agent"]["sms_preinject"] = False
    cfg["agent"]["sms_force_call"] = False
    cfg["agent"]["ask_is_grant"] = ask_is_grant
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
async def test_close_request_during_stream_keeps_finished_tool_call() -> None:
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
    router = _CloseDuringStream(_plot_call())
    confirmed: list[str] = []

    async def allow(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
        del cid, args, summary
        confirmed.append(tool)
        return "allow"

    bus, loop = _agent(router, plot, confirm=allow, cancel=[False])
    router.loop = loop
    events = await _collect(bus, loop.run("make a plot of these counts", "fast"))
    text = _done_text(events)
    assert plot.runs == 1
    assert text != _CLOSE_PARTIAL
    assert _CLOSE_PARTIAL not in text
    assert confirmed == [] or confirmed == ["plot"]


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


@pytest.mark.asyncio
async def test_close_during_write_still_shows_the_confirm_card() -> None:
    write = _CountingTool(
        "workspace",
        "write",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
        },
    )
    router = _CloseDuringStream(
        _native(
            "workspace",
            {"action": "write", "path": "notes/today.txt", "content": "desk note"},
        )
    )
    confirmed: list[str] = []

    async def decline(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
        del cid, args, summary
        confirmed.append(tool)
        return "skip"

    bus, loop = _agent(
        router,
        write,
        confirm=decline,
        cancel=[False],
        ask_is_grant=False,
    )
    router.loop = loop
    await _collect(bus, loop.run("do the thing", "fast"))
    assert confirmed == ["workspace"]
    assert write.runs == 0


@pytest.mark.asyncio
async def test_user_stop_mid_stream_aborts_immediately() -> None:
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
    router = _StopDuringStream(_plot_call(), cancel)

    async def allow(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
        del cid, tool, args, summary
        return "allow"

    bus, loop = _agent(router, plot, confirm=allow, cancel=cancel)
    router.loop = loop
    events = await _collect(bus, loop.run("make a plot of these counts", "fast"))
    text = _done_text(events)
    assert plot.runs == 0
    assert router.i == 1
    assert router.resumed_after_stop is False
    assert text == "Stopped."
    assert text != _CLOSE_PARTIAL


class _GraceTimer:
    def __init__(self) -> None:
        self.started: int | None = None

    def start(self, ms: int) -> None:
        self.started = int(ms)

    def isActive(self) -> bool:
        return self.started is not None

    def stop(self) -> None:
        self.started = None


def _grace_window() -> SimpleNamespace:
    return SimpleNamespace(
        _hung_watchdog=_GraceTimer(),
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
    assert HUNG_CLOSE_GRACE_S == 180
    window = _grace_window()
    armed = SimpleNamespace(request_close=lambda: None)
    _begin_close(window, armed)
    assert window._hung_watchdog.started == HUNG_CLOSE_GRACE_S * 1000
    assert window._hung_closing is True

    hard: dict[str, str] = {}

    def _cancel_turn(*, schedule_next: bool, reason: str = "stop") -> None:
        del schedule_next
        hard["reason"] = reason

    window._cancel_turn = _cancel_turn
    window._set_busy = lambda _busy: None
    on_hung_turn(window)
    assert hard.get("reason") == "hung"

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
    events: list[Any] = []

    async def capture(event: Any) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    runner = asyncio.create_task(bus.run())
    task = asyncio.create_task(loop.run("make a plot of these counts", "fast"))
    try:
        await asyncio.wait_for(router.entered.wait(), timeout=5)
        # Still the original stream. A close on the keepalive would have
        # started a second one and left this hang for the grace clock.
        assert router.streams == 1
    finally:
        cancel[0] = True
        router.release.set()
    await task
    await bus.drain()
    bus.stop()
    runner.cancel()
    text = _done_text(events)
    assert plot.runs == 0
    assert text == "Stopped."
    assert text != _CLOSE_PARTIAL
