"""A remembered label keeps the number this turn already computed."""

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


def _facts(store: MemoryStore) -> list[str]:
    return [str(row["text"]) for row in store.list_facts(status="active")]


def test_weekly_run_keeps_the_computed_distance(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    script = [
        [_call("units", {"action": "convert", "quantity": "5 miles", "to": "kilometers"})],
        [_call("calculator", {"expression": "8.04672 * 3"})],
        [_call("memory", {"action": "remember", "fact": "weekly run distance"})],
        [("token", "Stored.")],
    ]
    asyncio.run(_run(_CHAIN, script, store))
    stored = _facts(store)
    store.close()
    assert any("24.14" in text and "kilometers" in text for text in stored), stored


def test_a_fact_that_already_has_a_number_stays(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    fact = "weekly run distance is 10 kilometers"
    script = [
        [_call("units", {"action": "convert", "quantity": "5 miles", "to": "kilometers"})],
        [_call("calculator", {"expression": "8.04672 * 3"})],
        [_call("memory", {"action": "remember", "fact": fact})],
        [("token", "Stored.")],
    ]
    asyncio.run(_run(_CHAIN, script, store))
    stored = _facts(store)
    store.close()
    assert stored == [fact]


def test_remembering_a_person_with_no_math_stays(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    fact = "my dentist is Dr Lee"
    script = [
        [_call("memory", {"action": "remember", "fact": fact})],
        [("token", "Stored.")],
    ]
    asyncio.run(_run("Remember my dentist is Dr Lee.", script, store))
    stored = _facts(store)
    store.close()
    assert stored == [fact]


def test_a_number_from_an_earlier_turn_is_not_used(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    router = _ScriptedRouter(
        [
            [
                (
                    "tool_calls",
                    [
                        {
                            "type": "function",
                            "function": {
                                "name": "units",
                                "arguments": {
                                    "action": "convert",
                                    "quantity": "5 miles",
                                    "to": "kilometers",
                                },
                            },
                        },
                        {
                            "type": "function",
                            "function": {
                                "name": "calculator",
                                "arguments": {"expression": "8.04672 * 3"},
                            },
                        },
                    ],
                )
            ],
            [("token", "That distance is 24.14016 kilometers.")],
            [_call("memory", {"action": "remember", "fact": "weekly run distance"})],
            [("token", "Stored.")],
        ]
    )
    bus = EventBus()
    memory = SessionMemory()
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

    async def both() -> str:
        bus_task = asyncio.create_task(bus.run())
        try:
            await loop.run(
                "Convert 5 miles to kilometers, then multiply those kilometers by 3.",
                "fast",
                source="eval",
            )
            await bus.drain()
            prior = " ".join(str(row.get("content") or "") for row in memory.as_ollama())
            await loop.run(
                "Remember that as my weekly run distance.",
                "fast",
                source="eval",
            )
            await bus.drain()
        finally:
            bus.stop()
            bus_task.cancel()
            try:
                await bus_task
            except asyncio.CancelledError:
                pass
        return prior

    prior = asyncio.run(both())
    stored = _facts(store)
    store.close()
    assert "24.14016" in prior
    assert stored == ["weekly run distance"]


def test_a_sum_that_did_not_use_the_conversion_stays_a_bare_number(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db")
    store.start_session()
    script = [
        [_call("units", {"action": "convert", "quantity": "5 miles", "to": "kilometers"})],
        [_call("calculator", {"expression": "2 + 2"})],
        [_call("memory", {"action": "remember", "fact": "my lucky number"})],
        [("token", "Stored.")],
    ]
    asyncio.run(
        _run(
            "Convert 5 miles to kilometers, then add 2 and 2, "
            "then remember that sum as my lucky number.",
            script,
            store,
        )
    )
    stored = _facts(store)
    store.close()
    assert stored == ["my lucky number: 4"]
