"""Read recent inbound texts Arelis already announced (notification / SMSGate).

An empty list here has two meanings and they are not interchangeable: nobody
texted, or the bridge is dark and we cannot see. Inbound rides a notification
listener on the phone, which Doze, a muted conversation or battery
optimisation can stop without telling anyone, and on the companion path there
is no PC-side fallback poll to notice — `supports_inbox_poll` returns False
unless an SMSGate inbox URL is configured as well.

This tool used to answer both cases with "No inbound texts recorded this
session", which reads as a clean no. Asked "did Robin text back?", that is a
confident wrong answer about someone's messages, produced by the feature the
user named as their worst-behaving one.
"""

from __future__ import annotations

from typing import Any

from arelis.sms_ingest import COMPANION_PRESENCE, RECENT_INBOUND
from arelis.tools.base import Tool, ToolResult


class InboundSmsTool(Tool):
    name = "inbound_sms"
    description = (
        "List recent inbound texts that arrived while Arelis was open "
        "(Google Messages notifications and SMSGate fallback). Everyone who "
        "texted, not only people in contacts. Use this when the user asks "
        "whether someone texted back, what they said, or for recent SMS — "
        "do not web_search social media for private replies. If it reports "
        "that the phone bridge has not checked in, say that — never turn it "
        "into 'no new messages'."
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
        age = COMPANION_PRESENCE.age_seconds()
        if not items:
            if age is None:
                # Never heard from the phone. This is not "no messages", it is
                # "no way to know", and saying the first would be inventing an
                # answer about the user's messages.
                return ToolResult(
                    ok=False,
                    output=(
                        "I cannot tell whether anyone texted. "
                        + COMPANION_PRESENCE.describe()
                        + " Do not report this as 'no new messages' — check "
                        "the phone is on the same network, that Arelis has "
                        "notification access, and that battery optimisation "
                        "is off for it."
                    ),
                    data={
                        "messages": [],
                        "count": 0,
                        "bridge": "unknown",
                        "fail_class": "fail:bridge_unknown",
                    },
                )
            return ToolResult(
                ok=True,
                output=(
                    "No inbound texts recorded this session. "
                    + COMPANION_PRESENCE.describe()
                    + " Arelis only sees messages while the desktop UI is "
                    "open, and a muted conversation or a phone in Doze can "
                    "stop them arriving without any error."
                ),
                data={
                    "messages": [],
                    "count": 0,
                    "bridge": "seen",
                    "bridge_age_s": int(age),
                },
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
            data={
                "messages": items,
                "count": len(items),
                "bridge": "unknown" if age is None else "seen",
                "bridge_age_s": None if age is None else int(age),
            },
        )
