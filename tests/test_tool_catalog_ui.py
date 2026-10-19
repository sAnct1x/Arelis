"""Browsable tool list — name + one line, not the schema essays.

Roadmap 6.3. 41+ tools and no way to learn they exist except docs or
watching one fire. Tests drive `format_tool_catalog` — no Qt.

Mutant this file is supposed to catch: a list that drops `cas` or
`remind` while those tools still exist.
"""

from __future__ import annotations

import pytest

from arelis.core.compact_prompt import (
    _SHORT_DESC,
    format_tool_catalog,
)
from arelis.core.events import EventType
from arelis.core.orchestrator_slash import OrchestratorSlash
from arelis.tools.cas import CasTool
from arelis.tools.remind import RemindTool


def _named_line(text: str, name: str) -> str:
    marker = f"`{name}`: "
    for line in text.splitlines():
        if line.startswith(marker):
            return line
    raise AssertionError(f"no name+line for {name!r} in:\n{text}")


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


