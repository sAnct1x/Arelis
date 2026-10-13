"""The tool_loading flag and the load_tools definition.

Default stays off, so the model-facing tool list is the same list as
before this flag. Turning the flag on registers load_tools and nothing
else. The call reports a group's menu and tool names. It does not add
or remove any other tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

_DASHES = ("\u2013", "\u2014")
_DEFAULT = Path(__file__).resolve().parents[1] / "arelis" / "config" / "default.yaml"


def test_flag_defaults_off() -> None:
    from arelis.core.tool_loading import tool_loading

    shipped = yaml.safe_load(_DEFAULT.read_text(encoding="utf-8"))
    assert shipped["agent"]["tool_loading"] is False
    assert tool_loading(None) is False
    assert tool_loading({}) is False
    assert tool_loading({"tool_loading": False}) is False
    assert tool_loading({"tool_loading": True}) is True


def test_load_tools_definition_is_plain() -> None:
    from arelis.tools.groups import GROUPS
    from arelis.tools.load_tools import LoadTools

    tool = LoadTools()
    assert tool.name == "load_tools"
    assert tool.risk == "read"
    schema = tool.parameters_schema
    assert schema["required"] == ["groups"]
    groups = schema["properties"]["groups"]
    assert groups["type"] == "array"
    assert groups["items"]["enum"] == list(GROUPS)
    description = tool.description
    assert description.strip()
    assert not any(mark in description for mark in _DASHES)
    for name in GROUPS:
        assert name in description
    assert "core" not in description.split(". ", 1)[0]


def test_flag_off_leaves_every_profile_without_load_tools() -> None:
    from scripts.measure_tool_schema import registry_for_profile

    for profile in ("default", "worst", "mac"):
        names = registry_for_profile(profile).names()
        assert "load_tools" not in names, profile


def test_flag_on_registers_only_the_definition() -> None:
    from arelis.config import load_config
    from arelis.tools import build_tool_registry
    from scripts.measure_tool_schema import _router, registry_for_profile

    off = registry_for_profile("default")
    config = load_config()
    config["agent"]["tool_loading"] = True
    config["_vl_model_installed"] = False
    on = build_tool_registry(
        config, allow_send=True, attended=True, router=_router()
    )
    assert on.names() == set(off.names()) | {"load_tools"}
    assert "load_tools" not in off.names()


def test_call_reports_the_group_and_leaves_the_registry() -> None:
    import asyncio

    from arelis.tools.groups import GROUPS, MENU
    from arelis.tools.load_tools import LoadTools
    from scripts.measure_tool_schema import registry_for_profile

    registry = registry_for_profile("default")
    before = set(registry.names())
    result = asyncio.run(LoadTools().run(groups=["images", "calendar"]))
    assert result.ok
    assert MENU["images"] in result.output
    assert MENU["calendar"] in result.output
    assert list(result.data["groups"]) == ["images", "calendar"]
    assert list(result.data["tools"]) == list(GROUPS["images"]) + list(GROUPS["calendar"])
    assert set(registry.names()) == before
    assert "load_tools" not in before


def test_unknown_group_is_refused() -> None:
    import asyncio

    from arelis.tools.load_tools import LoadTools

    result = asyncio.run(LoadTools().run(groups=["core"]))
    assert not result.ok
    assert "core" in result.output
    empty = asyncio.run(LoadTools().run(groups=[]))
    assert not empty.ok


def test_definition_fits_the_core_budget() -> None:
    from arelis.tools.base import ToolRegistry
    from arelis.tools.groups import CORE
    from arelis.tools.load_tools import LoadTools
    from scripts.measure_tool_schema import (
        registry_for_profile,
        schema_token_estimate,
        tool_specs,
    )

    core = [
        spec
        for spec in tool_specs(registry_for_profile("worst"))
        if spec["function"]["name"] in CORE
    ]
    alone = ToolRegistry()
    alone.register(LoadTools())
    specs = core + alone.ollama_tools()
    tokens = schema_token_estimate(len(json.dumps(specs)))
    assert tokens <= 2000, tokens
