"""#122: a reply that is only Done, plus a link, is not an answer.

Orbit facts for Phobos and Deimos already come from the NASA fact sheet.
What was left is the turn that read a page and then stopped at Done.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.events import EventType
from arelis.core.memory import SessionMemory
from arelis.tools.base import ToolRegistry, ToolResult
from tests.hardening_helpers import _collect, _config, _deny, _ScriptedRouter

_ASK = "which way does Phobos rise and set, and is Deimos farther from Mars than Phobos?"
_PAGE = (
    "# Phobos and Deimos\n"
    "Site: example.com\n\n"
    "Phobos rises in the west and sets in the east about twice a day. "
    "Deimos is farther from Mars than Phobos, and its orbit takes longer than a Mars day. "
    "Those are the two moons."
)
_PAGE_URL = "https://example.com/mars-moons"
_DONE_ONLY = re.compile(r"(?is)^done[.!]?(?:\s+https?://\S+)?\s*$")


class _MoonPage:
    """Offline stand-in for one fetched page. No network."""

    name = "scrape"
    description = "fetch a page"
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(ok=True, output=_PAGE, data={"url": _PAGE_URL})


def _scrape_call() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "scrape",
            "arguments": {"url": _PAGE_URL},
        },
    }


def _loop(router: _ScriptedRouter) -> tuple[EventBus, AgentLoop]:
    bus = EventBus()
    tools = ToolRegistry()
    tools.register(_MoonPage())
    cfg = _config()
    cfg["agent"]["chat_fast_path"] = False
    cfg["agent"]["max_rounds"] = 8
    loop = AgentLoop(
        bus,
        router,  # type: ignore[arg-type]
        tools,
        SessionMemory(),
        "persona",
        cfg,
        request_confirm=_deny,
        is_cancelled=lambda: False,
    )
    return bus, loop


def _answer_before_sources(text: str) -> str:
    return text.split("**Sources:**", 1)[0].strip()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    (
        "Done",
        "Done.",
        "Done\nhttps://example.com/mars-moons",
    ),
)
async def test_done_plus_a_link_is_not_the_answer_about_the_moons(reply: str) -> None:
    """After the page is read, Done is not the reply. The moons are."""
    router = _ScriptedRouter(
        [
            [("tool_calls", [_scrape_call()])],
            [("token", reply)],
            [("token", reply)],
        ]
    )
    bus, loop = _loop(router)
    events = await _collect(bus, loop.run(_ASK, "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = str(done.payload["text"])
    body = _answer_before_sources(text)
    assert _DONE_ONLY.match(body) is None
    low = body.lower()
    assert "rises in the west and sets in the east" in low
    assert "farther from mars than phobos" in low
    assert "longer than a mars day" in low
    assert _PAGE_URL in text


@pytest.mark.asyncio
async def test_a_real_sentence_that_starts_with_done_still_ships() -> None:
    """Done followed by the actual fact is an answer and stays one."""
    sentence = "Done. Phobos rises in the west and sets in the east about twice a day."
    router = _ScriptedRouter(
        [
            [("tool_calls", [_scrape_call()])],
            [("token", sentence)],
        ]
    )
    bus, loop = _loop(router)
    events = await _collect(bus, loop.run(_ASK, "fast"))
    done = next(e for e in events if e.type == EventType.ASSISTANT_DONE)
    text = str(done.payload["text"])
    assert text.startswith(sentence)
    assert "rises in the west and sets in the east" in text.lower()
