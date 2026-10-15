"""agent.tool_loading is off, tail, or front.

Off is the shipped default and must stay byte-identical to the worst-profile
list saved before this flag. tail and front send only the registered core
tools plus load_tools, frozen for the session. An unknown value falls back
to off.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_GOLDEN = Path(__file__).parent / "fixtures" / "worst_profile_tools.json"


def _names(specs: list[dict]) -> list[str]:
    return [spec["function"]["name"] for spec in specs]


def _core_names(registered: list[str]) -> list[str]:
    from arelis.tools.groups import CORE

    core = set(CORE)
    return [name for name in registered if name in core]


def test_tail_list_is_frozen_and_equals_warmup() -> None:
    from arelis.config import load_config
    from arelis.core.tool_surface import session_tool_schemas
    from arelis.llm.startup import prefix_warmup_for
    from scripts.measure_tool_schema import registry_for_profile, tool_specs

    config = load_config()
    config.setdefault("agent", {})["tool_loading"] = "tail"
    reg = registry_for_profile("worst")
    turn = session_tool_schemas(reg, config["agent"])
    again = session_tool_schemas(reg, config["agent"])
    warm = prefix_warmup_for(config, reg)
    assert warm is not None
    assert again is turn
    assert warm.tools is turn
    registered = _names(tool_specs(registry_for_profile("worst")))
    assert _names(turn) == [*_core_names(registered), "load_tools"]


def test_load_tools_enum_matches_groups() -> None:
    from arelis.core.tool_surface import session_tool_schemas
    from arelis.tools.groups import GROUPS, MENU
    from arelis.tools.load_tools import LoadTools
    from scripts.measure_tool_schema import (
        registry_for_profile,
        schema_token_estimate,
    )

    schema = LoadTools.parameters_schema
    assert schema["required"] == ["groups"]
    assert schema["properties"]["groups"]["items"]["enum"] == list(GROUPS)
    description = LoadTools.description
    assert "Call before using a tool you do not see." in description
    for phrase in MENU.values():
        assert phrase in description
    specs = session_tool_schemas(
        registry_for_profile("worst"), {"tool_loading": "tail"}
    )
    tokens = schema_token_estimate(len(json.dumps(specs)))
    assert tokens <= 2000, tokens


def test_shipped_default_is_off_without_a_warning(caplog) -> None:
    """The real default.yaml must parse as off, and boolean False must too.

    An unquoted off is YAML boolean False. That used to hit the unknown
    fallback and log on every turn and at warmup.
    """
    import yaml

    from arelis.config import DEFAULT_CONFIG_PATH
    from arelis.core.tool_surface import _tool_loading_mode

    shipped = yaml.safe_load(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    raw = shipped["agent"]["tool_loading"]
    assert raw == "off"
    with caplog.at_level(logging.INFO, logger="arelis.core.tool_surface"):
        assert _tool_loading_mode(shipped["agent"]) == "off"
        assert _tool_loading_mode({"tool_loading": False}) == "off"
    assert "not off, tail, or front" not in caplog.text


