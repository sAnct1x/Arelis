"""One real turn per landed route. Not the Arelis window.

AgentLoop.run, the eval stub registry, plus tile and run_script stubs so
those names are on the menu. ModelRouter points at local qwen3.5:9b with
warm_on_start off. If a preinject misses, stream hits that model and this
script stops. Side-effect tools are stubs: nothing is sent, opened, or run.
"""

from __future__ import annotations

import asyncio
import sys

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.eval.harness import _StubTool, foundation_registry, shipped_num_ctx
from arelis.llm.ollama import OllamaProvider
from arelis.llm.router import ModelRouter

CASES = (
    ("what's the weather in austin", "weather"),
    ("open my calendar", "agenda"),
    ("what is on my calendar today", "agenda"),
    ("what is 17-3", "calculator"),
    ("what is the gravitational constant", "units"),
    (
        "Email brian@example.com subject: Status body: All green on the deploy.",
        "send_email",
    ),
    ("text brian that I'm running late", ""),
    ("text 5551112222 that I am running late", "send_sms"),
    ("open x.com", "browser"),
    ("show me the workspace", "tile"),
    ("where is the Drive strip?", "workspace"),
    ("run measure_drift.py", "run_script"),
)


async def one(phrase: str, expect: str) -> tuple[bool, str]:
    order: list[str] = []
    stream_calls = 0
    provider = OllamaProvider("http://127.0.0.1:11434", timeout_s=120)
    router = ModelRouter(
        provider,
        {"fast": "qwen3.5:9b"},
        warm_on_start=False,
        rewarm_after_switch=False,
    )
    real_stream = router.stream

    async def stream(*args, **kwargs):
        nonlocal stream_calls
        stream_calls += 1
        tools = kwargs.get("tools")
        n = 0 if not tools else len(tools)
        order.append(f"stream:tools={n}")
        async for item in real_stream(*args, **kwargs):
            yield item

    router.stream = stream  # type: ignore[method-assign]

    tools = foundation_registry()
    tools.register(_StubTool("tile", risk="read"))
    tools.register(_StubTool("run_script", risk="side_effect"))
    real_call = tools.call

    async def call(name: str, /, **kwargs):
        order.append("tool:" + str(name))
        return await real_call(name, **kwargs)

    tools.call = call  # type: ignore[method-assign]

    bus = EventBus()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    for et in (EventType.TOOL_START, EventType.TOOL_CONFIRM, EventType.ERROR):
        bus.subscribe(et, capture)

    confirms: list[str] = []

    async def _confirm(_cid, tool: str, *_a, **_k) -> str:
        confirms.append(str(tool or ""))
        return "allow"

    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        persona="You are Arelis under a route check.",
        config={
            "agent": {
                "max_rounds": 2,
                "tool_output_chars": 4000,
                "tool_summary_inject": True,
                "confirm_writes": True,
                "confirm_send": True,
                "confirm_browser": True,
                "confirm_run": True,
                "ask_is_grant": False,
                "intent_preflight": True,
                "exactness": True,
                "numeric_gate": True,
                "sms_force_call": True,
                "email_force_call": True,
                "weather_force_call": True,
                "agenda_force_call": True,
                "skill_tool_subset": False,
                "research_tool_subset": False,
                "turn_telemetry": False,
                "lessons": False,
            },
            "ollama": {"num_ctx": shipped_num_ctx()},
        },
        request_confirm=_confirm,
        is_cancelled=lambda: False,
    )
    bus_task = asyncio.create_task(bus.run())
    err = ""
    try:
        await loop.run(phrase, "fast", source="eval")
        await bus.drain()
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass
        await provider._client.aclose()

    started = [
        str(e.payload.get("tool") or "")
        for e in events
        if e.type == EventType.TOOL_START
    ]
    first = started[0] if started else ""
    if expect:
        route_first = bool(order) and order[0] == f"tool:{expect}"
        ok = route_first and first == expect and not err
    else:
        # Incomplete draft. The route must not send. The model may be asked.
        ok = "tool:send_sms" not in order and first != "send_sms" and not err
    line = (
        f"phrase={phrase!r} expect={expect} first={first or '-'} "
        f"order={order} stream_calls={stream_calls} "
        f"confirms={confirms} ok={ok}"
    )
    if err:
        line += f" err={err}"
    return ok, line


async def main() -> int:
    failed = False
    for phrase, expect in CASES:
        ok, line = await one(phrase, expect)
        print(line, flush=True)
        if not ok:
            failed = True
            print(f"MISS route did not fire for {expect}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
