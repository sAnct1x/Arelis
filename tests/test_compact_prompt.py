"""Skinny schemas and telegraph policy — what Ollama sees every turn."""

from __future__ import annotations

import json

from arelis.config import load_config
from arelis.core.compact_prompt import (
    _SHORT_DESC,
    COMPACT_TOOL_POLICY,
    skinny_description,
    skinny_ollama_tool,
    skinny_parameters,
)
from arelis.tools import build_tool_registry


def test_skinny_description_uses_the_map() -> None:
    assert skinny_description("weather", "a long unused essay. more.") == (
        _SHORT_DESC["weather"]
    )


def test_skinny_description_falls_back_to_first_sentence() -> None:
    assert skinny_description("unknown_tool", "First sentence. Rest.") == "First sentence"


def test_skinny_parameters_drop_description_keep_enums() -> None:
    schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add"],
                "description": "a long essay about listing",
            }
        },
        "required": ["action"],
        "description": "top-level essay",
    }
    out = skinny_parameters(schema)
    assert "description" not in out
    assert out["required"] == ["action"]
    assert out["properties"]["action"]["enum"] == ["list", "add"]
    assert "description" not in out["properties"]["action"]


def test_skinny_ollama_tool_shape() -> None:
    tool = skinny_ollama_tool(
        "weather",
        "unused",
        {"type": "object", "properties": {"place": {"type": "string"}}},
    )
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "weather"
    assert tool["function"]["description"] == _SHORT_DESC["weather"]
    assert "description" not in json.dumps(tool["function"]["parameters"])


def test_every_registered_tool_has_a_skinny_line() -> None:
    names = build_tool_registry(load_config()).names()
    missing = sorted(names - set(_SHORT_DESC))
    assert not missing, f"add skinny lines for {missing}"


def test_shipped_schemas_are_skinny() -> None:
    tools = build_tool_registry(load_config()).ollama_tools()
    assert tools
    blob = json.dumps(tools)
    for tool in tools:
        fn = tool["function"]
        name = fn["name"]
        assert fn["description"] == _SHORT_DESC[name]
        assert "description" not in json.dumps(fn["parameters"])
        assert len(fn["description"]) < 160
    assert "Would you like me to proceed" not in blob


def test_compact_policy_is_the_shipped_policy() -> None:
    from arelis.core.agent_loop import TOOL_POLICY
    from arelis.core.skills import full_tool_policy

    assert full_tool_policy() == COMPACT_TOOL_POLICY
    assert TOOL_POLICY == COMPACT_TOOL_POLICY
