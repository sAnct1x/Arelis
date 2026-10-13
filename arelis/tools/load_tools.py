"""Schema for load_tools. Calling it does not load anything yet.

The session list includes this tool only when agent.tool_loading is
tail or front. The registry does not register it while the flag is off.
"""

from __future__ import annotations

from typing import Any

from arelis.tools.base import ToolResult
from arelis.tools.groups import GROUPS, MENU


def _description() -> str:
    phrases = " ".join(MENU[name] for name in GROUPS)
    return f"{phrases} Call before using a tool you do not see."


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

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        return ToolResult(ok=False, output="not available yet")
