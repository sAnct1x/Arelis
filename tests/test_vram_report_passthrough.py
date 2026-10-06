"""VRAM failure after research_report must not tag a composed line as tool paste."""
from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter

_DUMP = "API VERSION: 1.2\nTarget body name: Moon (301)\nCenter body name: Earth (399)\n"


class _ReportStub:
    name = "research_report"
    description = "write a research report"
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(ok=True, output=_DUMP)


class _ReportThenVram(_ScriptedRouter):
    def __init__(self) -> None:
        call = {
            "type": "function",
            "function": {"name": "research_report", "arguments": {"topic": "the Moon"}},
        }
        super().__init__([[("tool_calls", [call])]])
        self.calls = 0

    async def stream(self, role, messages, **kwargs: Any):
        self.calls += 1
        if self.calls >= 2:
            raise RuntimeError(
                "could not load `qwen3:14b`: could not free VRAM, gpu still has 11 GB"
            )
        async for item in super().stream(role, messages, **kwargs):
            yield item


@pytest.mark.asyncio
async def test_vram_after_report_does_not_mark_composed_line_as_tool_paste() -> None:
    bus = EventBus()
    registry = ToolRegistry()
    registry.register(_ReportStub())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 8
    router = _ReportThenVram()
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        registry,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    events = await _collect(
        bus, loop.run("write me a research report on the Moon", "fast")
    )
    assert any(
        "answering from artifact" in str(e.payload.get("text"))
        for e in events
        if e.type == EventType.THINKING
    ), "VRAM branch not reached"
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert "API VERSION" not in done.payload["text"]
    note = ([m for m in loop.memory.messages if m.role == "assistant"][-1].note or "")
    assert "not her own words" not in note
    assert "raw tool output" not in note
