"""Static system prefix must stay byte-stable across turns."""

from __future__ import annotations

from arelis.core.agent_loop import (
    STATIC_TOOL_POLICY,
    TOOL_POLICY,
    static_prefix_text,
    static_system_prefix,
)
from arelis.core.skills import SKILL_CORE, assemble_skill_focus


def test_static_prefix_identical_across_assemblies() -> None:
    persona = "You are Arelis, a local assistant."
    a = static_prefix_text(persona)
    b = static_prefix_text(persona)
    assert a == b
    assert STATIC_TOOL_POLICY in a
    assert SKILL_CORE in a
    assert a.startswith(persona)
    # Full union stays available for tests/docs but is not the live prefix.
    assert len(STATIC_TOOL_POLICY) < len(TOOL_POLICY)


def test_static_prefix_is_persona_then_skill_core() -> None:
    persona = "Persona line."
    msgs = static_system_prefix(persona)
    assert len(msgs) == 2
    assert msgs[0] == {"role": "system", "content": persona}
    assert msgs[1] == {"role": "system", "content": STATIC_TOOL_POLICY}
    assert msgs[1]["content"] == SKILL_CORE


def test_skill_focus_is_trailer_not_prefix() -> None:
    """Focus bodies differ by user text; static prefix must not include them."""
    tools = {"browser", "web_search", "weather", "send_sms", "calculator"}
    focus_a = assemble_skill_focus("open youtube.com", available_tools=tools)
    focus_b = assemble_skill_focus("what's the weather today?", available_tools=tools)
    assert focus_a
    assert focus_b
    assert focus_a != focus_b
    persona = "You are Arelis."
    prefix = static_prefix_text(persona)
    assert focus_a not in prefix
    assert focus_b not in prefix
    assert "### This turn — focus skills" not in prefix
