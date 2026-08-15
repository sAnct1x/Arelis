"""Sliding-window history cap bounds the dynamic trailer."""

from __future__ import annotations

import asyncio
from typing import Any

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.eval.harness import _ScriptedRouter, foundation_registry


def test_history_max_messages_drops_overflow() -> None:
    async def _run() -> dict[str, Any]:
        bus = EventBus()
        memory = SessionMemory()
        for i in range(20):
            memory.add("user", f"user note {i} " + ("x" * 40))
            memory.add("assistant", f"assistant note {i} " + ("y" * 40))
        assert len(memory.messages) == 40

        router = _ScriptedRouter(
            [
                [
                    ("token", "ok"),
                    (
                        "metrics",
                        {
                            "prompt_eval_count": 200,
                            "prompt_eval_duration": 100_000_000,
                            "eval_count": 5,
                            "eval_duration": 50_000_000,
                        },
                    ),
                ]
            ]
        )
        loop = AgentLoop(
            bus,
            router,  # type: ignore[arg-type]
            foundation_registry(),
            memory,
            persona="You are Arelis under test.",
            config={
                "agent": {
                    "max_rounds": 2,
                    "history_max_messages": 10,
                    "turn_telemetry": True,
                    "skill_cards": False,
                    "exactness": False,
                    "numeric_gate": False,
                    "evidence_gate": False,
                    "chat_fast_path": True,
                    "summarize_max_ms": 1,
                },
                "ollama": {"num_ctx": 8192},
            },
            request_confirm=lambda *_a, **_k: "allow",
            is_cancelled=lambda: False,
        )
        bus_task = asyncio.create_task(bus.run())
        try:
            await loop.run("hi", "fast", source="test")
            await bus.drain()
        finally:
            bus.stop()
            bus_task.cancel()
            try:
                await bus_task
            except asyncio.CancelledError:
                pass
        timer = loop._timer
        assert timer is not None
        return {
            "kept": timer.history_kept,
            "dropped": timer.history_dropped,
        }

    result = asyncio.run(_run())
    assert result["kept"] is not None and result["kept"] <= 10
    assert result["dropped"] is not None and result["dropped"] >= 30


def test_scripted_router_import_surface() -> None:
    # Guard: harness exports the router the window test uses.
    assert EventType.ASSISTANT_DONE
