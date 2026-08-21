"""Show or hide an Arelis View-menu tile. No Allow — it is the window itself."""

from __future__ import annotations

from typing import Any

from arelis.core.tile_complete import TILE_NAMES
from arelis.tools.base import ToolResult


class TileTool:
    name = "tile"
    description = (
        "Open or close an Arelis tile (the View menu): thinking, workspace, "
        "history, notifications, camera, contacts, calendar. "
        "action=open shows it; action=close hides it. "
        "For calendar events use agenda, not this tool. "
        "Do not use the browser to open these."
    )
    risk = "read"
    last_name: str = ""
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["open", "close"],
                "description": "open shows the tile; close hides it",
            },
            "name": {
                "type": "string",
                "enum": list(TILE_NAMES),
                "description": "Which tile. Omit on close to reuse the last one.",
            },
        },
        "required": ["action"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action not in {"open", "close"}:
            return ToolResult(
                ok=False,
                output="Unknown action. Use open or close.",
            )
        name = str(kwargs.get("name") or "").strip().lower()
        if not name:
            name = (type(self).last_name or "").strip().lower()
        if name not in TILE_NAMES:
            return ToolResult(
                ok=False,
                output=(
                    "Name a tile: thinking, workspace, history, "
                    "notifications, camera, contacts, or calendar."
                ),
            )
        type(self).last_name = name
        verb = "Opened" if action == "open" else "Closed"
        return ToolResult(
            ok=True,
            output=f"{verb} {name}.",
            data={"open": action == "open", "close": action == "close", "name": name},
        )
