"""In-process timers. ``remind me in 20 minutes`` — not ``schedule``.

list is free. in / at / cancel change persisted state. The tool is
registered as risk=read because list is the common case; parent policy
should gate the writes:

    REMIND_WRITE_ACTIONS = frozenset({"in", "at", "cancel"})
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from arelis.reminders import Reminder, ReminderError, ReminderStore
from arelis.tools.base import ToolResult

# Parent policy.py: add this to the action_is_write table under "remind".
REMIND_WRITE_ACTIONS = frozenset({"in", "at", "cancel"})
WRITE_ACTIONS = REMIND_WRITE_ACTIONS


class RemindTool:
    name = "remind"
    description = (
        "In-process reminder / timer (tray toast when due). "
        "action=in needs a message plus minutes and/or seconds (hours ok); "
        "action=at needs a local ISO or YYYY-MM-DD HH:MM plus a message; "
        "action=list pending; action=cancel needs id. "
        "Max 7 days — later than that is schedule or agenda, not this. "
        "Does not use Windows Task Scheduler. in/at/cancel are writes."
    )
    # list dominates. Parent policy gates in/at/cancel via REMIND_WRITE_ACTIONS.
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["in", "at", "list", "cancel"],
                "description": (
                    "in = delay from now, at = local datetime, list pending, "
                    "cancel by id"
                ),
            },
            "minutes": {
                "type": "number",
                "description": "Delay minutes for action=in (combine with seconds/hours)",
            },
            "seconds": {
                "type": "number",
                "description": "Delay seconds for action=in",
            },
            "hours": {
                "type": "number",
                "description": "Delay hours for action=in",
            },
            "when": {
                "type": "string",
                "description": (
                    "Local due time for action=at: ISO or YYYY-MM-DD HH:MM"
                ),
            },
            "at": {
                "type": "string",
                "description": "Alias for when on action=at",
            },
            "message": {
                "type": "string",
                "description": "What to say when it fires (in / at)",
            },
            "text": {
                "type": "string",
                "description": "Alias for message",
            },
            "id": {
                "type": "string",
                "description": "Reminder id for action=cancel",
            },
        },
        "required": ["action"],
    }

    def __init__(self, store: ReminderStore | Path | str | None = None) -> None:
        if isinstance(store, ReminderStore):
            self.store = store
        else:
            self.store = ReminderStore(store)

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action == "in":
            return self._in(kwargs)
        if action == "at":
            return self._at(kwargs)
        if action == "list":
            return self._list()
        if action == "cancel":
            return self._cancel(kwargs)
        return ToolResult(
            ok=False,
            output="Unknown action. Use in, at, list, or cancel.",
        )

    def _in(self, kwargs: dict[str, Any]) -> ToolResult:
        message = _message(kwargs)
        if message is None:
            return ToolResult(ok=False, output="remind in needs a message.")
        try:
            item = self.store.add_in(
                message,
                minutes=kwargs.get("minutes"),
                seconds=kwargs.get("seconds"),
                hours=kwargs.get("hours"),
            )
        except ReminderError as exc:
            return ToolResult(ok=False, output=str(exc))
        return _created(item)

    def _at(self, kwargs: dict[str, Any]) -> ToolResult:
        message = _message(kwargs)
        if message is None:
            return ToolResult(ok=False, output="remind at needs a message.")
        when = str(
            kwargs.get("when")
            or kwargs.get("at")
            or kwargs.get("datetime")
            or ""
        ).strip()
        if not when:
            return ToolResult(
                ok=False,
                output="remind at needs when= as ISO or YYYY-MM-DD HH:MM.",
            )
        try:
            item = self.store.add_at(when, message)
        except ReminderError as exc:
            return ToolResult(ok=False, output=str(exc))
        return _created(item)

    def _list(self) -> ToolResult:
        rows = self.store.list_pending()
        if not rows:
            return ToolResult(
                ok=True,
                output="No pending reminders.",
                data={"reminders": []},
            )
        listed = [_pending_row(item) for item in rows]
        lines = [
            f"#{row['id']}  {row['due']}  {row['message']}" for row in listed
        ]
        lines.append(f"{len(listed)} pending reminder(s).")
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={"reminders": listed},
        )

    def _cancel(self, kwargs: dict[str, Any]) -> ToolResult:
        raw = kwargs.get("id")
        if raw is None or str(raw).strip() == "":
            return ToolResult(ok=False, output="remind cancel needs an id.")
        item = self.store.cancel(raw)
        if item is None:
            return ToolResult(ok=False, output=f"No reminder with id {raw}.")
        return ToolResult(
            ok=True,
            output=f"Cancelled #{item.id}: {item.message}",
            data={"id": item.id, "message": item.message},
        )


def _message(kwargs: dict[str, Any]) -> str | None:
    text = str(kwargs.get("message") or kwargs.get("text") or "").strip()
    return text or None


def _created(item: Reminder) -> ToolResult:
    due = _display_due(item.due_iso)
    return ToolResult(
        ok=True,
        output=f"I'll remind you at {due}: {item.message} (#{item.id})",
        data=item.fire_payload(),
    )


def _pending_row(item: Reminder) -> dict[str, Any]:
    return {
        "id": item.id,
        "due": _display_due(item.due_iso),
        "due_iso": item.due_iso,
        "message": item.message,
    }


def _display_due(due_iso: str) -> str:
    try:
        when = datetime.fromisoformat(due_iso.replace("Z", "+00:00"))
    except ValueError:
        return due_iso
    return when.strftime("%Y-%m-%d %H:%M")
