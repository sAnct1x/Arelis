"""Restored Allow cards: execute the parked send and tell the bus.

Live turns wait on the orchestrator. Core-parked / restored cards have no
waiter — Allow has to run the tool here. One helper so the window only
decides, and confirm_exec stays the only place a restored send is invoked.
"""

from __future__ import annotations

from typing import Any

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.presence.confirm_exec import execute_pending_confirm
from arelis.presence.pending_confirms import PendingConfirm


async def emit_restored_confirm(
    bus: EventBus,
    item: PendingConfirm,
    config: dict[str, Any],
) -> tuple[bool, str]:
    """Run a stored send after Allow and publish STATUS + TOOL_RESULT."""
    ok, output = await execute_pending_confirm(item, config)
    await bus.publish(
        Event(
            EventType.STATUS,
            {"message": output if ok else f"Pending send failed: {output}"},
        )
    )
    await bus.publish(
        Event(
            EventType.TOOL_RESULT,
            {
                "tool": item.tool,
                "ok": ok,
                "output": output,
                "data": {},
                "source": "pending_confirm",
            },
        )
    )
    return ok, output
