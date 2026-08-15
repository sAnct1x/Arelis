"""Confirm card auto-skip after confirm_timeout_s (L10)."""

from __future__ import annotations

import asyncio

import pytest

from arelis.config import PROJECT_ROOT
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.tools.base import ToolRegistry


class _StubRouter:
    default_role = "fast"
    active_model = None
    models = {"fast": "mock"}

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    def apply_sticky(self, wanted, reason: str):
        return wanted, reason

    def clear_sticky(self) -> None:
        return None

    async def stream(self, role, messages, **kwargs):
        if False:
            yield ("token", "")
        return

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_confirm_timeout_auto_skips() -> None:
    bus = EventBus()
    seen: list[Event] = []

    async def capture(event: Event) -> None:
        seen.append(event)

    bus.subscribe(None, capture)
    orch = Orchestrator(
        bus,
        _StubRouter(),  # type: ignore[arg-type]
        ToolRegistry(),
        {
            "agent": {"confirm_timeout_s": 0.05},
            "workspace": {"roots": ["."]},
            "_persona_path": str(PROJECT_ROOT / "arelis" / "persona" / "arelis.md"),
        },
        SessionMemory(),
    )
    bus_task = asyncio.create_task(bus.run())
    try:
        decision = await orch._request_confirm(
            "cid-timeout",
            "workspace",
            {"action": "write", "path": "x.txt", "content": "hi"},
            "workspace(...)",
        )
        await bus.drain()
    finally:
        bus.stop()
        bus_task.cancel()

    assert decision == "skip"
    assert any(
        e.type == EventType.TOOL_CONFIRM_REPLY
        and e.payload.get("reason") == "timeout"
        for e in seen
    )
    assert any(e.type == EventType.STATUS for e in seen)


def test_workspace_describe_includes_content() -> None:
    reg = ToolRegistry()
    detail = reg.describe_call(
        "workspace",
        {"action": "write", "path": "note.txt", "content": "hello body"},
    )
    assert "note.txt" in detail
    assert "hello body" in detail
