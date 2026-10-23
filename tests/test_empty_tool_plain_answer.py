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


# Spoken forecast from the real weather tool. The colon dump is for the
# model. Empty-after-tool and a dump echo both ship this sentence.
_SPOKEN_SPRINGFIELD = (
    "It's 61\u00b0F and overcast in Springfield, Illinois. "
    "High 66\u00b0F, low 48\u00b0F. "
    "Tomorrow is clear, high 70\u00b0F, low 52\u00b0F. "
    "Saturday is light rain, high 64\u00b0F, low 49\u00b0F. "
    "Sunday is partly cloudy, high 62\u00b0F, low 46\u00b0F."
)
_SPOKEN_SPRINGFIELD_NO_SKY = (
    "It's 61\u00b0F in Springfield, Illinois. "
    "High 66\u00b0F, low 48\u00b0F. "
    "Tomorrow is clear, high 70\u00b0F, low 52\u00b0F. "
    "Saturday is light rain, high 64\u00b0F, low 49\u00b0F. "
    "Sunday is partly cloudy, high 62\u00b0F, low 46\u00b0F."
)


class _CloseAfterWeather(_RecordingRouter):
    """Close once the weather call is on the wire, then an empty close pass."""

    def __init__(self, call: dict[str, Any]) -> None:
        super().__init__([[("tool_calls", [call])], [("token", "")]])
        self.loop: AgentLoop | None = None

    async def stream(self, role, messages, **kwargs):  # type: ignore[no-untyped-def]
        self.stream_kwargs.append(dict(kwargs))
        self.stream_messages.append(json.loads(json.dumps(messages)))
        self.i += 1
        if self.i == 1:
            yield ("tool_calls", self.script[0][0][1])
            assert self.loop is not None
            self.loop.request_close()
            return
        yield ("token", "")


@pytest.mark.asyncio
async def test_weather_empty_or_echoed_is_a_spoken_sentence() -> None:
    """Empty, echoed, or late fallback weather dump ships the spoken forecast."""
    from arelis.core.agent_loop import _WRITE_AFTER_TOOL_NOTICE
    from arelis.voice.speech_text import prepare_spoken_text
    from tests.test_weather_tool import _IL, _few_days, _Standins

    stand = _Standins([_IL])
    stand.reading = _few_days()
    primed = await stand.tool().run(place="Springfield, Illinois")
    assert primed.ok, primed.output
    dump = str(primed.output or "")
    reply = str((primed.data or {}).get("reply") or "")
    assert dump.startswith("Springfield, Illinois:")
    assert reply == _SPOKEN_SPRINGFIELD
    assert dump != reply

    bare = dict(_few_days())
    bare["current"] = {
        key: value
        for key, value in dict(bare.get("current") or {}).items()
        if key != "weather_code"
    }
    stand.reading = bare
    no_sky = await stand.tool().run(place="Springfield, Illinois")
    assert str((no_sky.data or {}).get("reply") or "") == _SPOKEN_SPRINGFIELD_NO_SKY
    assert "unknown" not in str((no_sky.data or {}).get("reply") or "").lower()
    stand.reading = _few_days()

    call = {
        "type": "function",
        "function": {
            "name": "weather",
            "arguments": {"place": "Springfield, Illinois"},
        },
    }
    calc_call = {
        "type": "function",
        "function": {
            "name": "calculator",
            "arguments": {"expression": "1+1"},
        },
    }
    ask = "what's the weather in Springfield, Illinois?"

    def _assert_spoken(text: str) -> None:
        assert text == _SPOKEN_SPRINGFIELD
        assert dump not in text
        assert "Springfield, Illinois:" not in text
        assert "could not put it into words" not in text
        heard = prepare_spoken_text(text)
        assert "degrees Fahrenheit" in heard
        assert "\u00b0" not in heard

    def _assert_pin(router: _RecordingRouter) -> None:
        assert any(
            item.get("content") == _WRITE_AFTER_TOOL_NOTICE
            for msgs in router.stream_messages
            for item in msgs
        )

    async def _done(router: _RecordingRouter, *tools: Any) -> str:
        bus, loop = _loop(router, *tools)
        if hasattr(router, "loop"):
            router.loop = loop
        events = await _collect(bus, loop.run(ask, "fast"))
        thinking = [
            str(e.payload.get("text") or "")
            for e in events
            if e.type == EventType.THINKING
        ]
        assert not any("asking for a write-up" in line for line in thinking)
        done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
        text = str(done.payload.get("text") or "").strip()
        _assert_spoken(text)
        _assert_pin(router)
        return text

    # Empty-after-tool and a dump echo (already-plain + raw-line).
    await _done(
        _RecordingRouter([[("tool_calls", [call])], [("token", "")]]),
        stand.tool(),
    )
    await _done(
        _RecordingRouter([[("tool_calls", [call])], [("token", dump)]]),
        stand.tool(),
    )

    # HTTP 400 after the tool (turn_round four_line).
    class _WeatherThen400(_RecordingRouter):
        async def stream(self, role, messages, **kwargs):  # type: ignore[no-untyped-def]
            self.stream_kwargs.append(dict(kwargs))
            self.stream_messages.append(json.loads(json.dumps(messages)))
            self.i += 1
            if self.i == 1:
                yield ("tool_calls", [call])
                return
            raise RuntimeError(
                "The local model returned HTTP 400 for model `mock`: closing '}'"
            )

    await _done(_WeatherThen400([[]]), stand.tool())

    # VRAM after weather, with research_report already marked used.
    class _WeatherThenVram(_RecordingRouter):
        loop: AgentLoop | None = None

        async def stream(self, role, messages, **kwargs):  # type: ignore[no-untyped-def]
            self.stream_kwargs.append(dict(kwargs))
            self.stream_messages.append(json.loads(json.dumps(messages)))
            self.i += 1
            if self.i == 1:
                yield ("tool_calls", [call])
                return
            assert self.loop is not None
            self.loop.tools_used.add("research_report")
            raise RuntimeError(
                "could not load `qwen3:14b`: could not free VRAM, gpu still has 11 GB"
            )

    await _done(_WeatherThenVram([[]]), stand.tool())

    # Dump pasted on the plain-answer retry (turn_round ~972).
    await _done(
        _RecordingRouter(
            [
                [("tool_calls", [calc_call])],
                [("tool_calls", [call])],
                [("tool_calls", [call]), ("token", dump)],
                [("tool_calls", [call]), ("token", dump)],
            ]
        ),
        CalculatorTool(),
        stand.tool(),
    )

    # Close pass with the weather result already in hand (turn_round ~1028).
    await _done(_CloseAfterWeather(call), stand.tool())


