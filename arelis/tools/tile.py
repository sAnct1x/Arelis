"""Show or hide an Arelis View-menu tile. No Allow — it is the window itself."""

from __future__ import annotations

from typing import Any

from arelis.core.tile_complete import TILE_NAMES
from arelis.tools.base import ToolResult


class TileTool:
    name = "tile"
    description = (
        "Open or close an Arelis tile (the View menu): thinking, workspace, "
        "history, notifications, camera, contacts, calendar, world. "
        "action=open shows it; action=close hides it. "
        "World is the physics-room plate (hands sandbox / solar lab). "
        "page=solar enters the lab; page=hands enters the toy. "
        "Omit page for the chooser. "
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
            "page": {
                "type": "string",
                "enum": ["solar", "hands"],
                "description": "World page. solar is the lab; hands is the toy. Omit for the chooser.",
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
                    "notifications, camera, contacts, calendar, or world."
                ),
            )
        type(self).last_name = name
        page = str(kwargs.get("page") or "").strip().lower()
        if page not in {"", "solar", "hands"}:
            page = ""
        if name != "world":
            page = ""
        verb = "Opened" if action == "open" else "Closed"
        data: dict[str, Any] = {
            "open": action == "open",
            "close": action == "close",
            "name": name,
        }
        if page:
            data["page"] = page
        note = f" {page}" if page else ""
        return ToolResult(
            ok=True,
            output=f"{verb} {name}{note}.",
            data=data,
        )
