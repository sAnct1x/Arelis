"""#121: empty reply after a tool must ship plain language, never raw tool output.

When the model leaves chat empty after a successful tool, Arelis used to paste
the calculator formula or a data header into the bubble. That is the bug.
"""

from __future__ import annotations

from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from arelis.tools.calculator import CalculatorTool
from arelis.tools.solar_tool import SolarTool
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter

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


@pytest.mark.asyncio
async def test_mars_year_empty_after_calc_is_plain_language() -> None:
    """Model empty every round after calculator: no formula line in chat."""
    ask = "how long is a year on Mars?"
    router = _ScriptedRouter(
        [
            [("token", "")],
            [("token", "")],
            [("token", "")],
            [("token", "")],
        ]
    )
    bus, loop = _loop(router, CalculatorTool())
    events = await _collect(bus, loop.run(ask, "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = done.payload["text"]
    _assert_plain_answer(text, must_have="1.88")
    assert "=" not in text or "Earth years" in text or "works out" in text.lower()


@pytest.mark.asyncio
async def test_moon_distance_empty_after_data_is_plain_language() -> None:
    """Raw Horizons header must never become the chat answer."""
    ask = "how far away is the moon right now?"
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
    router = _ScriptedRouter(
        [
            [("tool_calls", [call])],
            [("token", "")],
            [("token", "")],
            [("token", "")],
        ]
    )
    bus, loop = _loop(router, _HorizonsStub())
    events = await _collect(bus, loop.run(ask, "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = done.payload["text"]
    _assert_plain_answer(text)
    assert "Moon (301)" not in text
    assert "JPL/Horizons" not in text


@pytest.mark.asyncio
async def test_mars_gravity_empty_after_body_is_plain_language() -> None:
    """Catalog-style lab lines are data, not a spoken answer."""
    ask = "how strong is gravity on Mars compared to here"
    call = {
        "type": "function",
        "function": {
            "name": "solar",
            "arguments": {"action": "body", "name": "Mars"},
        },
    }
    router = _ScriptedRouter(
        [
            [("tool_calls", [call])],
            [("token", "")],
            [("token", "")],
            [("token", "")],
        ]
    )
    bus, loop = _loop(router, SolarTool())
    events = await _collect(bus, loop.run(ask, "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = done.payload["text"]
    _assert_plain_answer(text)
    assert "surface g" not in text.lower()
    assert "GM / R^2" not in text
    assert "Reality lab catalog" not in text


@pytest.mark.asyncio
async def test_empty_once_then_summarize_sentence_ships() -> None:
    """Empty after the tool, then a real sentence on the write-up round."""
    ask = "how long is a year on Mars?"
    good = "A year on Mars is about 1.88 Earth years."
    router = _ScriptedRouter(
        [
            [("token", "")],
            [("token", good)],
        ]
    )
    bus, loop = _loop(router, CalculatorTool())
    events = await _collect(bus, loop.run(ask, "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = done.payload["text"]
    assert text.strip() == good
    assert "(686.980)/365.256" not in text


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


async def test_jupiter_year_in_earth_days_is_not_called_earth_years() -> None:
    from arelis.core.failure_copy import chat_followup_from_tool

    ask = "how many Earth days in a year on Jupiter"
    result = await CalculatorTool().run(expression=ask)
    assert result.ok, result.output
    line = chat_followup_from_tool("calculator", result.output, ask=ask)
    assert "Earth years" not in line
    assert "Earth days" in line
    assert "4332" in line or "4333" in line


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


async def test_mars_year_ratio_still_says_earth_years() -> None:
    from arelis.core.failure_copy import chat_followup_from_tool

    ask = "how long is a year on Mars?"
    result = await CalculatorTool().run(expression=ask)
    assert result.ok, result.output
    line = chat_followup_from_tool("calculator", result.output, ask=ask)
    assert line == "A year on Mars is about 1.88 Earth years."


def test_agenda_event_list_stays_readable() -> None:
    """A real today list must not become the generic data-dump line."""
    from arelis.core.failure_copy import chat_followup_from_tool

    raw = (
        "**Today**\n"
        "- 10:00 AM, lab meeting\n"
        "  Building 4\n"
        "- 2:30 PM, dentist\n"
        "\n"
        "Source: cache\n"
        "Summarize these events for the user (time, title, place, "
        "one-line notes). Do not invent events. Do not quote "
        "Google/Outlook event ids."
    )
    ask = "what's on my calendar today?"
    line = chat_followup_from_tool("agenda", raw, ask=ask)
    assert "could not put it into words" not in line.lower()
    assert "lab meeting" in line
    assert "dentist" in line
    assert "Do not invent" not in line
    assert "Summarize these events" not in line


def test_pending_reminders_list_stays_readable() -> None:
    from arelis.core.failure_copy import chat_followup_from_tool

    raw = (
        "#12  2026-10-05T18:00:00-04:00  call the dentist\n"
        "#13  2026-10-06T09:00:00-04:00  pack for the lab\n"
        "2 pending reminder(s)."
    )
    line = chat_followup_from_tool("remind", raw, ask="what reminders do I have?")
    assert "could not put it into words" not in line.lower()
    assert "call the dentist" in line
    assert "pack for the lab" in line
