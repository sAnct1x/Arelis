"""Load named tool groups for one session.

Registered only when agent.tool_loading is tail or front. Off leaves it
out of the registry, so the tools list stays the full frozen list.

A call records the groups on the registry and returns each registered
tool's schema as one JSON line, the same object the tools array would
have carried. Loading a group that is already loaded does not add it
again, and the schemas come back again.

tail puts those lines in this tool's result, at the end of history. The
session tools array is not changed. front does the same here: the array
stays the frozen core list. Growing that array is a later change.
"""

from __future__ import annotations

import json
from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.groups import GROUPS, MENU


def _description() -> str:
    phrases = " ".join(MENU[name] for name in GROUPS)
    return f"{phrases} Call before using a tool you do not see."


def _valid_groups() -> str:
    return ", ".join(GROUPS)


class LoadTools:
    name = "load_tools"
    description = _description()
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "groups": {
                "type": "array",
                "items": {"type": "string", "enum": list(GROUPS)},
                "description": "Group names from the menu.",
            }
        },
        "required": ["groups"],
    }

    def __init__(
        self,
        registry: Any = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._registry = registry
        self._config = config

    async def run(self, groups: Any = None, **kwargs: Any) -> ToolResult:
        del kwargs
        names, error = _group_names(groups)
        if error is not None or names is None:
            return ToolResult(ok=False, output=error or "groups must be a list of group names.")
        registry = self._registry
        if registry is None or not hasattr(registry, "ollama_tools"):
            return ToolResult(
                ok=False, output="load_tools is not available in this session."
            )
        loaded = getattr(registry, "loaded_groups", None)
        if not isinstance(loaded, list):
            loaded = []
            registry.loaded_groups = loaded
        for name in names:
            if name not in loaded:
                loaded.append(name)
        return ToolResult(ok=True, output=self._schema_lines(names))

    def _hints(self) -> bool:
        from arelis.core.native_tool_calling import native_tool_calling

        agent = None
        if isinstance(self._config, dict):
            raw = self._config.get("agent")
            if isinstance(raw, dict):
                agent = raw
        return bool(native_tool_calling(agent))

    def _schema_lines(self, groups: list[str]) -> str:
        registry = self._registry
        order: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for name in GROUPS[group]:
                if name in seen or registry.get(name) is None:
                    continue
                seen.add(name)
                order.append(name)
        if not order:
            return (
                "Loaded "
                + ", ".join(groups)
                + ". No tools from those groups are registered in this session."
            )
        specs = registry.ollama_tools(set(order), param_hints=self._hints())
        by_name = {
            str((spec.get("function") or {}).get("name") or ""): spec for spec in specs
        }
        return "\n".join(
            json.dumps(by_name[name]) for name in order if name in by_name
        )


def _group_names(groups: Any) -> tuple[list[str] | None, str | None]:
    valid = _valid_groups()
    if not isinstance(groups, list):
        return None, (
            "groups must be a list of group names. Valid groups: " + valid + "."
        )
    if not groups:
        return None, "groups is empty. Valid groups: " + valid + "."
    names: list[str] = []
    for item in groups:
        if not isinstance(item, str) or not item.strip():
            return None, (
                "groups must be a list of group names. Valid groups: " + valid + "."
            )
        names.append(item.strip())
    unknown = list(dict.fromkeys(name for name in names if name not in GROUPS))
    if unknown:
        return None, (
            "Unknown group "
            + ", ".join(unknown)
            + ". Valid groups: "
            + valid
            + "."
        )
    ordered: list[str] = []
    for name in names:
        if name not in ordered:
            ordered.append(name)
    return ordered, None
