"""The 9B sends linspace/sin,cos. A traceback then a silent think spiral is the hang.

Fail-before: on main this call is ok=False and the output is a Python traceback.
Bad range args used to raise before plot's own try, so tools.call let ValueError
kill the turn. A tool error that finished the turn also left think=false on.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry
from tests.hardening_helpers import _config, _deny, _ScriptedRouter
from tests.test_plot_charts import _tool


def _call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "arguments": arguments}}


class _ThinkRouter(_ScriptedRouter):
    """Scripted router that records think= from each stream."""

    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        super().__init__(script)
        self.thinks: list[object] = []

    async def stream(self, role, messages, **kwargs):
        self.thinks.append(kwargs.get("think"))
        async for item in super().stream(role, messages, **kwargs):
            yield item


@pytest.mark.asyncio
async def test_nine_b_linspace_sine_cosine_draws_or_explains(
    tmp_path, monkeypatch
) -> None:
    """Same args as 9b-cold-r3. Must draw, or a one-line error the model can act on."""
    tool, drop = _tool(tmp_path, monkeypatch)

    result = await tool.run(
        action="line",
        xmin="0",
        xmax="6.283185307",
        xs="linspace(0, 2*pi, 100)",
        ys="sin(x), cos(x)",
        title="Sine and Cosine Functions",
        xlabel="x (radians)",
        ylabel="y",
        out="sine_cosine.png",
    )

    assert "Traceback" not in result.output
    assert result.ok, result.output
    png = drop / "sine_cosine.png"
    assert png.is_file()
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    no_bounds = await tool.run(
        action="line",
        xs="linspace(0, 2*pi, 80)",
        ys="sin(x)",
        out="sine_only.png",
    )
    assert no_bounds.ok, no_bounds.output
    assert "Traceback" not in no_bounds.output

    counted = await tool.run(
        action="line",
        xs="arange(0, 1, 0.5)",
        ys="0, 1",
        out="arange.png",
    )
    assert counted.ok, counted.output
    assert "Traceback" not in counted.output

    bad = await tool.run(action="line", xs="1,2,3", ys="sin(x), cos(x)")
    assert not bad.ok
    assert "Traceback" not in bad.output
    assert "ys" in bad.output
    assert "expr=" in bad.output
    assert "xmax" in bad.output

    # Promotion used to run before plot's try. ys must be a formula so that
    # path runs; ys="1,2" skipped it and hid the crash.
    crash_n = await tool.run(
        action="line",
        xs="linspace(0, 2*pi, n)",
        ys="sin(x)",
        out="nope.png",
    )
    assert not crash_n.ok
    assert "Traceback" not in crash_n.output
    assert "not a number" in crash_n.output
    assert "n" in crash_n.output
    assert not (drop / "nope.png").is_file()

    crash_cap = await tool.run(
        action="line",
        xs="linspace(0, 1, 9000)",
        ys="sin(x)",
        out="nope-cap.png",
    )
    assert not crash_cap.ok
    assert "Traceback" not in crash_cap.output
    assert "9000" in crash_cap.output
    assert "5000" in crash_cap.output
    assert not (drop / "nope-cap.png").is_file()

    evil = await tool.run(
        action="line",
        xs="linspace(__import__('os').name, 1, 2)",
        ys="sin(x)",
        out="nope-import.png",
    )
    assert not evil.ok
    assert "Traceback" not in evil.output
    assert not (drop / "nope-import.png").is_file()

    crash = {"action": "line", "xs": "linspace(0, 2*pi, n)", "ys": "sin(x)"}
    router = _ThinkRouter(
        [
            [("tool_calls", [_call("plot", crash)])],
            [("tool_calls", [_call("plot", crash)])],
            [("token", "ok")],
        ]
    )
    bus = EventBus()
    tools = ToolRegistry()
    tools.register(tool)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 6
    cfg["agent"]["confirm_writes"] = False
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
    task = asyncio.create_task(bus.run())
    try:
        await loop.run("plot sine from 0 to 2pi", "fast")
        assert False in router.thinks, router.thinks
        n_first = len(router.thinks)
        await loop.run("what time is it?", "fast")
        rest = router.thinks[n_first:]
        assert rest, router.thinks
        assert rest[0] is not False, rest
    finally:
        await bus.drain()
        bus.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
