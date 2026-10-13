"""A memory save is confirmed in a sentence, not the tool's receipt line.

The live miss shipped "Remembered: weekly run distance: 24.14016 kilometers"
as the whole reply. A forget receipt stays the tool's own line.
"""

from __future__ import annotations

import asyncio
from typing import Any

from arelis.config import shipped_num_ctx
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.eval.harness import _ScriptedRouter
from arelis.memory import MemoryStore
from arelis.tools.base import ToolRegistry
from arelis.tools.calculator import CalculatorTool
from arelis.tools.memory_tool import MemoryTool
from arelis.tools.units import UnitsTool

_CHAIN = (
    "Convert 5 miles to kilometers, then multiply those kilometers by 3, "
    "then remember that result as my weekly run distance."
)


def _call(name: str, arguments: dict[str, Any]) -> tuple[str, Any]:
    return (
        "tool_calls",
        [
            {
                "type": "function",
                "function": {"name": name, "arguments": arguments},
            }
        ],
    )


def _registry(store: MemoryStore) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(UnitsTool())
    reg.register(CalculatorTool())
    reg.register(MemoryTool(store))
    return reg


async def _allow(*_args: Any, **_kwargs: Any) -> str:
    return "allow"


async def _run(text: str, script: list[list[tuple[str, Any]]], store: MemoryStore) -> str:
    router = _ScriptedRouter(script)
    bus = EventBus()
    memory = SessionMemory()
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(EventType.ASSISTANT_DONE, capture)
    loop = AgentLoop(
        bus,
        router,
        _registry(store),
        memory,
        persona="You are Arelis under eval.",
        config={
            "agent": {
                "max_rounds": 6,
                "exactness": True,
                "numeric_gate": True,
                "evidence_gate": True,
                "native_tool_calling": False,
            },
            "ollama": {"num_ctx": shipped_num_ctx()},
        },
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    bus_task = asyncio.create_task(bus.run())
    try:
        await loop.run(text, "fast", source="eval")
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()
        try:
            await bus_task
        except asyncio.CancelledError:
            pass
    done = next((event for event in events if event.type == EventType.ASSISTANT_DONE), None)
    return str((done.payload.get("text") if done else "") or "")


def test_weekly_run_is_confirmed_without_the_receipt(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    script = [
        [_call("units", {"action": "convert", "quantity": "5 miles", "to": "kilometers"})],
        [_call("calculator", {"expression": "8.04672 * 3"})],
        [_call("memory", {"action": "remember", "fact": "weekly run distance"})],
        [("token", "")],
    ]
    text = asyncio.run(_run(_CHAIN, script, store))
    store.close()
    assert not text.startswith("Remembered:")
    assert "24.14016" in text
    assert "remember" in text.casefold()


def test_a_person_is_confirmed_in_a_sentence(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    script = [
        [_call("memory", {"action": "remember", "fact": "my dentist is Dr Lee"})],
        [("token", "")],
    ]
    text = asyncio.run(_run("Remember my dentist is Dr Lee.", script, store))
    store.close()
    assert not text.startswith("Remembered:")
    assert "Dr Lee" in text
    assert "remember" in text.casefold()


def test_a_forget_receipt_stays_as_the_tool_said_it(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    store.add_fact("my dentist is Dr Lee", source="explicit", status="active")
    script = [
        [_call("memory", {"action": "forget", "fact": "my dentist is Dr Lee"})],
        [("token", "")],
    ]
    text = asyncio.run(_run("Forget that my dentist is Dr Lee.", script, store))
    store.close()
    assert text == "Forgot 1 fact."
