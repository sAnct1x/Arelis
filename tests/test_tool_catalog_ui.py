"""Browsable tool list — name + one line, not the schema essays.

Roadmap 6.3. 41+ tools and no way to learn they exist except docs or
watching one fire. Tests drive `format_tool_catalog` — no Qt.

Mutant this file is supposed to catch: a list that drops `cas` or
`remind` while those tools still exist.
"""

from __future__ import annotations

import re

import pytest

from arelis.core.compact_prompt import (
    _SHORT_DESC,
    TOOLS_SLASH,
    format_tool_catalog,
    skinny_description,
)
from arelis.core.events import EventType
from arelis.core.orchestrator_slash import OrchestratorSlash
from arelis.tools.cas import CasTool
from arelis.tools.remind import RemindTool


def _named_line(text: str, name: str) -> str:
    marker = f"`{name}` — "
    for line in text.splitlines():
        if line.startswith(marker):
            return line
    raise AssertionError(f"no name+line for {name!r} in:\n{text}")


def test_tools_slash_is_the_idle_chip_command() -> None:
    assert TOOLS_SLASH == "/tools"
    from pathlib import Path

    idle = Path("arelis/ui/void_idle.py").read_text(encoding="utf-8")
    slash = Path("arelis/core/orchestrator_slash.py").read_text(encoding="utf-8")
    turns = Path("arelis/core/orchestrator_turns.py").read_text(encoding="utf-8")
    assert "TOOLS_SLASH" in idle and "_add_tools_chip" in idle
    assert "format_tool_catalog" in slash and "_emit_tools" in slash
    assert "_emit_tools" in turns


def test_catalog_names_cas_and_remind_while_those_tools_exist() -> None:
    assert CasTool.name == "cas"
    assert RemindTool.name == "remind"
    assert "cas" in _SHORT_DESC
    assert "remind" in _SHORT_DESC
    text = format_tool_catalog()
    cas = _named_line(text, "cas")
    remind = _named_line(text, "remind")
    assert "symbolic" in cas.lower() or "math" in cas.lower()
    assert "timer" in remind.lower() or "minutes" in remind.lower()


def test_catalog_is_name_plus_one_line() -> None:
    text = format_tool_catalog()
    named = [line for line in text.splitlines() if " — " in line]
    assert len(named) >= 41
    for line in named:
        assert line.count("\n") == 0
        assert len(line) <= 220
        assert re.match(r"`[a-z0-9_]+` — \S", line)


def test_catalog_does_not_dump_essays() -> None:
    """A wall of schema prose is how we used to hide the names."""
    text = format_tool_catalog()
    assert "parameters" not in text.lower()
    assert "properties" not in text.lower()
    body = "\n".join(line for line in text.splitlines() if " — " in line)
    assert "\n\n" not in body


def test_partial_registry_still_keeps_tools_that_exist() -> None:
    """Passing weather-only must not drop cas/remind. They still exist."""
    text = format_tool_catalog(
        [{"name": "weather", "description": "forecast. defaults to home"}]
    )
    _named_line(text, "cas")
    _named_line(text, "remind")
    _named_line(text, "weather")


@pytest.mark.asyncio
async def test_slash_tools_publishes_the_catalog() -> None:
    """ /tools is the same formatter, not a name dump and not a model turn."""

    class _Bus:
        def __init__(self) -> None:
            self.events: list[object] = []

        async def publish(self, event: object) -> None:
            self.events.append(event)

    class _Tools:
        def list(self) -> list[dict[str, str]]:
            return [{"name": "weather", "description": "forecast"}]

    host = type("Host", (), {"bus": _Bus(), "tools": _Tools()})()
    await OrchestratorSlash._emit_tools(host)
    assert len(host.bus.events) == 1
    event = host.bus.events[0]
    assert event.type == EventType.ASSISTANT_DONE
    text = str(event.payload.get("text") or "")
    _named_line(text, "cas")
    _named_line(text, "remind")
    assert "What she can do" in text


def test_catalog_uses_short_desc_not_a_long_fallback() -> None:
    essay = (
        "A very long tool description that would have been the old schema "
        "essay dumped into chat. Second sentence should never appear."
    )
    text = format_tool_catalog([{"name": "cas", "description": essay}])
    line = _named_line(text, "cas")
    assert "Second sentence" not in line
    assert skinny_description("cas", essay) in line
