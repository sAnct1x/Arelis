"""#290: the short parameter hints reach the model when native tool calling is off."""

from __future__ import annotations

from arelis.core.compact_prompt import skinny_tool
from arelis.core.native_tool_calling import NATIVE_PARAM_HINTS


def test_short_param_hints_go_out_in_the_default_mode() -> None:
    schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}, "content": {"type": "string", "description": "long essay"}},
    }
    spec = skinny_tool("workspace", "Files.", schema)  # param_hints defaults to off
    props = spec["function"]["parameters"]["properties"]
    assert props["content"]["description"] == NATIVE_PARAM_HINTS[("workspace", "content")]
    assert "description" not in props["action"]
