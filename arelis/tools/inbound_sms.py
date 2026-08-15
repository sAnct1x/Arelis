"""Read recent inbound texts Arelis already announced (notification / SMSGate)."""

from __future__ import annotations

from typing import Any

from arelis.sms_ingest import RECENT_INBOUND
from arelis.tools.base import Tool, ToolResult


class InboundSmsTool(Tool):
    name = "inbound_sms"
    description = (
        "List recent inbound texts that arrived while Arelis was open "
        "(Google Messages notifications and SMSGate fallback). Use this when "
        "the user asks whether someone texted back, what they said, or for "
        "recent SMS — do not web_search social media for private replies."
    )
    risk = "read"
    parameters_schema = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many recent messages to return (default 10).",
            },
        },
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        try:
            limit = int(kwargs.get("limit") or 10)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, 40))
        items = RECENT_INBOUND.list(limit=limit)
        if not items:
            return ToolResult(
                ok=True,
                output=(
                    "No inbound texts recorded this session. Arelis only sees "
                    "messages while the desktop UI is open and the Android "
                    "notify companion (or SMSGate fallback) is working."
                ),
                data={"messages": [], "count": 0},
            )
        lines = []
        for i, item in enumerate(items, 1):
            who = item.get("display_from") or item.get("contact_name") or item.get("from")
            body = (item.get("body") or "").replace("\n", " ").strip()
            when = item.get("time") or ""
            src = item.get("source") or ""
            tail = f" ({src})" if src else ""
            stamp = f" @ {when}" if when else ""
            lines.append(f"{i}. {who}{stamp}{tail}: {body or '(no body)'}")
        return ToolResult(
            ok=True,
            output="Recent inbound texts:\n" + "\n".join(lines),
            data={"messages": items, "count": len(items)},
        )
