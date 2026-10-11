"""#176 plain-answer pin must not end a chain or ship a raw tool line.

C13: extract, then write a document. The turn has to reach the write.
S52b / S54b: a solar or earth status line is not the chat answer.
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
from tests.hardening_helpers import _collect, _config

_EXTRACT = (
    "path: work/a.pdf\n"
    "pages: 1-1 of 1\n"
    "source: text\n"
    "Matrix code: ALPHA-123"
)
_SOLAR = (
    "Sun (star). t=3.118e+04 s  rate=3600.0  residual E=2.794e-15  "
    "integrator=IAS15  counterfactual=False."
)
_EARTH = "Solar. Say enter Earth, or travel to Earth."
_DUMP = (
    "API VERSION: 1.2\n"
    "Target body name: Moon (301)\n"
    "Center body name: Earth (399)\n"
)

_C13 = (
    "Extract the text of work/a.pdf and then write it into a markdown "
    "document titled Extracted A."
)
_S52B = "Is the solar system simulation loaded right now?"
_S54B = "Which Reality view are we in right now, solar or Earth?"


class _Stub:
    def __init__(self, name: str, output: str) -> None:
        self.name = name
        self.description = name
        self.risk = "read"
        self.parameters_schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "path": {"type": "string"},
                "title": {"type": "string"},
                "format": {"type": "string"},
                "target": {"type": "string"},
            },
        }
        self.output = output
        self.runs = 0

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        self.runs += 1
        return ToolResult(ok=True, output=self.output)


class _Router:
    """Scripted model. Records every request so cache shape can be checked."""

    def __init__(self, decide) -> None:
        self.decide = decide
        self.i = 0
        self.sent: list[list[dict[str, Any]]] = []
        self.tools: list[Any] = []
        self.default_role = "fast"
        self.active_model = None
        self.active_role = None
        self.models = {"fast": "mock", "research": "mock", "code": "mock"}

    def model_for(self, role=None):
        del role
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        self.active_role = role
        self.active_model = "mock"
        return "mock"

    def mark_sticky(self, role) -> None:
        del role

    def apply_sticky(self, wanted, reason: str):
        return wanted, reason

    async def stream(self, role, messages, **kwargs):
        del role
        snapshot = json.loads(json.dumps(messages))
        self.sent.append(snapshot)
        self.tools.append(kwargs.get("tools"))
        self.i += 1
        for item in self.decide(self.i, snapshot):
            yield item


def _call(name: str, **args: Any) -> tuple[str, list]:
    return (
        "tool_calls",
        [{"type": "function", "function": {"name": name, "arguments": args}}],
    )


def _pinned(messages: list[dict[str, Any]]) -> bool:
    return any(item.get("content") == _TOOL_FREE_NUDGE for item in messages)


def _loop(router: _Router, *tools: _Stub) -> tuple[EventBus, AgentLoop]:
    bus = EventBus()
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 8
    cfg["agent"]["confirm_writes"] = False
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        registry,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_allow,
        is_cancelled=lambda: False,
    )
    return bus, loop


async def _allow(cid: str, tool: str, args: dict[str, Any], summary: str) -> str:
    del cid, tool, args, summary
    return "allow"


def _answer(events) -> str:
    done = next(event for event in events if event.type == EventType.ASSISTANT_DONE)
    return str(done.payload["text"])


def _same_tools(router: _Router, loop: AgentLoop) -> None:
    expected = session_tool_schemas(loop.tools, loop.config.get("agent"))
    assert router.tools
    for offered in router.tools:
        assert offered == expected


def _prefix_held(router: _Router) -> None:
    """Later requests extend the first one. The cached head stays put."""
    first = router.sent[0]
    assert first
    for later in router.sent[1:]:
        assert later[: len(first)] == first


@pytest.mark.asyncio
async def test_c13_extract_then_document_reaches_the_write() -> None:
    """Empty after doc_extract used to ship the extract and stop."""
    extract = _Stub("doc_extract", _EXTRACT)
    document = _Stub("document", "Wrote Extracted A.")

    def decide(i: int, messages: list[dict[str, Any]]):
        del messages
        if i == 1:
            return [_call("doc_extract", path="work/a.pdf")]
        if i == 2:
            return [("token", "")]
        if i == 3:
            return [_call("document", title="Extracted A", format="md")]
        return [("token", "I saved the extract as Extracted A.")]

    router = _Router(decide)
    bus, loop = _loop(router, extract, document)
    events = await _collect(bus, loop.run(_C13, "fast"))
    text = _answer(events)
    assert extract.runs == 1
    assert document.runs == 1
    assert text.strip() == "I saved the extract as Extracted A."
    assert "path: work/a.pdf" not in text
    assert not _pinned(router.sent[2])
    _same_tools(router, loop)
    _prefix_held(router)


@pytest.mark.asyncio
async def test_two_step_chain_is_not_told_to_stop_after_step_one() -> None:
    """A dump that is not already a sentence used to pin 'do not call anything'."""
    catalog = _Stub("catalog", _DUMP)
    document = _Stub("document", "Wrote Moon Note.")
    ask = (
        "Look up the moon with catalog, then write it into a markdown "
        "document titled Moon Note."
    )

    def decide(i: int, messages: list[dict[str, Any]]):
        if _pinned(messages):
            return [("token", "")]
        if i == 1:
            return [_call("catalog", action="horizons", target="Moon")]
        if i == 2:
            return [_call("document", title="Moon Note", format="md")]
        return [("token", "I wrote Moon Note from the lookup.")]

    router = _Router(decide)
    bus, loop = _loop(router, catalog, document)
    events = await _collect(bus, loop.run(ask, "fast"))
    text = _answer(events)
    assert catalog.runs == 1
    assert document.runs == 1
    assert text.strip() == "I wrote Moon Note from the lookup."
    assert "API VERSION" not in text
    _same_tools(router, loop)
    _prefix_held(router)


@pytest.mark.asyncio
async def test_s52b_solar_status_echo_is_not_the_answer() -> None:
    """The model repeating the solar line must not ship that line."""
    solar = _Stub("solar", _SOLAR)
    written = "The solar system simulation is loaded."

    def decide(i: int, messages: list[dict[str, Any]]):
        del messages
        if i == 1:
            return [_call("solar", action="status")]
        if i == 2:
            return [("token", _SOLAR)]
        if i == 3:
            return [_call("solar", action="status")]
        return [("token", written)]

    router = _Router(decide)
    bus, loop = _loop(router, solar)
    events = await _collect(bus, loop.run(_S52B, "fast"))
    text = _answer(events)
    assert text.strip() == written
    assert _SOLAR not in text
    assert "integrator=" not in text
    assert solar.runs == 1
    _same_tools(router, loop)
    _prefix_held(router)


@pytest.mark.asyncio
async def test_s52b_solar_echo_twice_uses_the_written_fallback() -> None:
    """Still a tool line on the extra round: written fallback, no third call."""
    solar = _Stub("solar", _SOLAR)

    def decide(i: int, messages: list[dict[str, Any]]):
        del messages
        if i == 1:
            return [_call("solar", action="status")]
        return [("token", _SOLAR)]

    router = _Router(decide)
    bus, loop = _loop(router, solar)
    events = await _collect(bus, loop.run(_S52B, "fast"))
    text = _answer(events)
    assert _SOLAR not in text
    assert "integrator=" not in text
    assert "could not put it into words" in text.lower()
    assert solar.runs == 1
    assert router.i == 3
    _same_tools(router, loop)
    _prefix_held(router)


@pytest.mark.asyncio
async def test_s54b_earth_status_echo_is_not_the_answer() -> None:
    """Earth status, and the word solar in the ask, still get a written reply."""
    earth = _Stub("earth", _EARTH)
    solar = _Stub("solar", _SOLAR)
    written = "We are in the solar view, not Earth."

    def decide(i: int, messages: list[dict[str, Any]]):
        del messages
        if i == 1:
            return [_call("earth", action="status")]
        if i == 2:
            return [("token", _EARTH)]
        return [("token", written)]

    router = _Router(decide)
    bus, loop = _loop(router, earth, solar)
    events = await _collect(bus, loop.run(_S54B, "fast"))
    text = _answer(events)
    assert text.strip() == written
    assert text.strip() != _EARTH
    assert earth.runs == 1
    assert solar.runs == 0
    _same_tools(router, loop)
    _prefix_held(router)
