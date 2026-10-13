"""Definition of load_tools. It reports a group. It does not load one.

The session list changes only when agent.tool_loading is on, and then
only by this one extra tool. Calling it prints the menu line and the
tool names. It does not register those tools.
"""

from __future__ import annotations

from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.groups import GROUPS, MENU

_GROUP_NAMES = tuple(GROUPS)


def _menu_list() -> str:
    names = _GROUP_NAMES
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + ", or " + names[-1]


def _asked_groups(raw: Any) -> list[str] | None:
    """Group names from a list or a comma-separated string. None if unusable."""
    if isinstance(raw, str):
        parts = [part.strip().lower() for part in raw.split(",")]
    elif isinstance(raw, (list, tuple)):
        parts = []
        for item in raw:
            if not isinstance(item, str):
                return None
            parts.append(item.strip().lower())
    else:
        return None
    asked: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part or part in seen:
            continue
        seen.add(part)
        asked.append(part)
    return asked


class LoadTools:
    name = "load_tools"
    description = (
        f"Report tool names for groups= {_menu_list()}. "
        "Does not change the session tool list."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "groups": {
                "type": "array",
                "items": {"type": "string", "enum": list(_GROUP_NAMES)},
                "description": "One or more group names from the menu.",
            }
        },
        "required": ["groups"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        asked = _asked_groups(kwargs.get("groups"))
        known = ", ".join(_GROUP_NAMES)
        if not asked:
            return ToolResult(
                ok=False,
                output=f"Name one or more groups: {known}.",
            )
        unknown = [name for name in asked if name not in GROUPS]
        if unknown:
            return ToolResult(
                ok=False,
                output=f"Unknown group {unknown[0]}. Groups: {known}.",
            )
        lines: list[str] = []
        tools: list[str] = []
        for name in asked:
            lines.append(MENU[name])
            lines.append("tools: " + ", ".join(GROUPS[name]))
            tools.extend(GROUPS[name])
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={"groups": asked, "tools": tools},
        )
