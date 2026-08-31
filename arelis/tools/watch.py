"""Read-only snapshot of the house watch (ports, inbound, outbound APIs)."""

from __future__ import annotations

from typing import Any

from arelis.guard import get_watch
from arelis.tools.base import ToolResult


class WatchTool:
    name = "watch"
    description = (
        "Report the house watch: listeners Arelis bound (ingest / IPC), "
        "inbound rate limits and bad-token lockouts, outbound API volume, "
        "and whether Earth/web egress is muted. Call only when the user asks "
        "if we are safe, if ports are open, if APIs are being hammered, or "
        "what the watch sees. Do not invent a threat. The numbers in the "
        "result are the truth — say them. This is not antivirus and does not "
        "scan the whole PC."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        del kwargs
        snap = get_watch().snapshot()
        return ToolResult(ok=True, output=snap.as_text(), data=snap.__dict__)
