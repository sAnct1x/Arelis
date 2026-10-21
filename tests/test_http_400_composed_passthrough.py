"""HTTP 400 after a tool must not mark a composed sentence as tool paste."""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry
from arelis.tools.calculator import CalculatorTool
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter


class _CalcThen400(_ScriptedRouter):
    """First stream calls calculator. The next stream is an object-parse 400."""

    def __init__(self) -> None:
        super().__init__([[]])
        self.calls = 0

    async def stream(self, role, messages, **kwargs: Any):
        del role, messages, kwargs
        self.calls += 1
        if self.calls == 1:
            yield (
                "tool_calls",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": {"expression": "how long is a year on Mars?"},
                        },
                    }
                ],
            )
            return
        raise RuntimeError(
            "The local model returned HTTP 400 for model `mock`: closing '}'"
        )


@pytest.mark.asyncio
async def test_http_400_after_calc_does_not_mark_composed_as_passthrough() -> None:
    ask = "how long is a year on Mars?"
    bus = EventBus()
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 8
    router = _CalcThen400()
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
    events = await _collect(bus, loop.run(ask, "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = done.payload["text"]
    assert "1.88" in text
    assert "Earth years" in text
    assert router.calls == 2
    assistant = [m for m in loop.memory.messages if m.role == "assistant"]
    assert assistant
    note = assistant[-1].note or ""
    assert "not her own words" not in note
    assert "raw tool output" not in note
