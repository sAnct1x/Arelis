"""#121: empty reply after a tool must ship plain language, never raw tool output.

When the model leaves chat empty after a successful tool, Arelis used to paste
the calculator formula or a data header into the bubble. That is the bug.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from arelis.core.agent_loop import _TOOL_FREE_NUDGE, AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.core.tool_surface import session_tool_schemas
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.calculator import CalculatorTool
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter

# The retry still sends the same tool list. This line is what makes the
# round tool-free in effect.
_PLAIN_NUDGE = _TOOL_FREE_NUDGE

_EM_DASH = "\u2014"
_EN_DASH = "\u2013"


def _loop(router: _ScriptedRouter, *tools: Any) -> tuple[EventBus, AgentLoop]:
    bus = EventBus()
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 8
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
    return bus, loop


def _assert_plain_answer(text: str, *, must_have: str | None = None) -> None:
    assert text.strip(), "answer must not be empty"
    lowered = text.lower()
    assert "done" != text.strip().lower()
    assert _EM_DASH not in text
    assert _EN_DASH not in text
    assert "(686.980)/365.256" not in text
    assert "api version" not in lowered
    assert "target body name" not in lowered
    assert "calculator" not in lowered
    assert "tool" not in lowered
    if must_have is not None:
        assert must_have in text


class _HorizonsStub:
    """Offline stand-in for a raw Moon ephemeris dump."""

    name = "catalog"
    description = "named catalogs"
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {"type": "string"},
            "target": {"type": "string"},
            "table": {"type": "string"},
        },
        "required": ["action"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(
            ok=True,
            output=(
                "JPL/Horizons API\n"
                "API VERSION: 1.2\n"
                "API SOURCE: NASA/JPL Horizons API\n"
                "Target body name: Moon (301)\n"
                "Center body name: Earth (399)\n"
                "Start time: A.D. 2026-Oct-05\n"
                "Revised: Jul 31, 2013\n"
                "R.A._______(ICRF)____DEC\n"
                "  05 14 22.12 +22 14 08.3\n"
            ),
            data={"action": "horizons", "target": "Moon"},
        )


class _RecordingRouter(_ScriptedRouter):
    """Scripted router that records every stream() kwargs for tool-offer checks."""

    def __init__(self, script: list[list[tuple[str, Any]]]) -> None:
        super().__init__(script)
        self.stream_kwargs: list[dict[str, Any]] = []
        self.stream_messages: list[list[dict[str, Any]]] = []

    async def stream(self, role, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.stream_kwargs.append(dict(kwargs))
        self.stream_messages.append(json.loads(json.dumps(messages)))
        steps = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        for item in steps:
            yield item


def _assert_same_tools(router: _RecordingRouter, loop: AgentLoop, index: int) -> None:
    """The retry carries the session list, same as the other requests."""
    tools = router.stream_kwargs[index].get("tools")
    expected = session_tool_schemas(loop.tools, loop.config.get("agent"))
    assert tools == expected
    assert tools == router.stream_kwargs[0].get("tools")


def _assert_plain_nudge(router: _RecordingRouter, index: int) -> None:
    last = router.stream_messages[index][-1]
    assert last.get("role") == "system"
    assert last.get("content") == _PLAIN_NUDGE


class _CountingHorizons(_HorizonsStub):
    def __init__(self) -> None:
        self.runs = 0

    async def run(self, **kwargs: Any) -> ToolResult:
        self.runs += 1
        return await super().run(**kwargs)


@pytest.mark.asyncio
async def test_tool_call_on_a_plain_retry_is_not_executed() -> None:
    """A call on the write-up round does not run. One re-ask, then plain text."""
    ask = "how far away is the moon right now?"
    good = "The Moon is about 402,000 kilometers away right now."
    call = {
        "type": "function",
        "function": {
            "name": "catalog",
            "arguments": {
                "action": "horizons",
                "target": "Moon",
                "table": "observer",
            },
        },
    }
    router = _RecordingRouter(
        [
            [("tool_calls", [call])],
            [("token", "")],
            [("tool_calls", [call])],
            [("token", good)],
        ]
    )
    tool = _CountingHorizons()
    bus, loop = _loop(router, tool)
    events = await _collect(bus, loop.run(ask, "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    assert done.payload["text"].strip() == good
    assert tool.runs == 1
    assert len(router.stream_kwargs) == 4
    earlier = router.stream_messages[2]
    later = router.stream_messages[3]
    assert later[: len(earlier)] == earlier
    tool_rows = [row for row in later if row.get("role") == "tool"]
    applied = [
        row
        for row in tool_rows
        if "not applied" not in str(row.get("content") or "")
    ]
    discarded = [
        row
        for row in tool_rows
        if "not applied" in str(row.get("content") or "")
    ]
    assert len(applied) == 1
    assert discarded, tool_rows
    _assert_same_tools(router, loop, 2)
    _assert_same_tools(router, loop, 3)
    _assert_plain_nudge(router, 2)
    _assert_plain_nudge(router, 3)


# --- follow-up: planet-year wording + agenda lists -------------------------


async def test_mars_year_in_days_is_not_called_earth_years() -> None:
    from arelis.core.failure_copy import chat_followup_from_tool

    ask = "how many days is a year on Mars?"
    result = await CalculatorTool().run(expression=ask)
    assert result.ok, result.output
    line = chat_followup_from_tool("calculator", result.output, ask=ask)
    assert "Earth years" not in line
    assert "Earth days" in line
    assert "687" in line or "686.98" in line


async def test_mars_age_is_not_called_a_planet_year() -> None:
    from arelis.core.failure_copy import chat_followup_from_tool

    ask = "If I was born on 1990-03-03 what age would I be in a Mars year"
    result = await CalculatorTool().run(expression=ask)
    assert result.ok, result.output
    line = chat_followup_from_tool("calculator", result.output, ask=ask)
    assert "A year on Mars" not in line
    assert "Earth years" not in line
    assert "works out" in line.lower()
    assert "19.45" in line or "19.5" in line or "19" in line


