"""Local goals and commitments in memory.db.

list is free. Mutates need approval when confirm_writes is on — same
argument-dependent gate as tasks/contacts.

Goals = durable outcomes. Commitments = standing promises (same table, kind=).
Chores stay on the tasks tool.
"""

from __future__ import annotations

from typing import Any

from arelis.memory.store import MemoryStore
from arelis.tools.base import ToolResult

WRITE_ACTIONS = frozenset(
    {"add", "update", "pause", "resume", "done", "drop", "remove"}
)

_STATUS_FROM_ACTION = {
    "pause": "paused",
    "resume": "active",
    "done": "done",
    "drop": "dropped",
}

_ALLOWED_FROM: dict[str, frozenset[str]] = {
    "pause": frozenset({"active"}),
    "resume": frozenset({"paused"}),
    "done": frozenset({"active", "paused"}),
    "drop": frozenset({"active", "paused"}),
}


def _format_goal(
    row: dict[str, Any], *, open_tasks: int | None = None
) -> str:
    title = str(row.get("title") or "").strip() or "(untitled)"
    status = str(row.get("status") or "")
    kind = str(row.get("kind") or "goal")
    horizon = str(row.get("horizon") or "").strip()
    gid = row.get("id")
    line = f"#{gid} [{status}/{kind}] {title}"
    if horizon:
        line += f" (horizon {horizon})"
    if open_tasks is not None and open_tasks > 0:
        noun = "task" if open_tasks == 1 else "tasks"
        line += f" ({open_tasks} open {noun})"
    return line


class GoalsTool:
    name = "goals"
    description = (
        "List, add, update, pause, resume, complete, drop, or remove durable "
        "goals and commitments in memory.db. Use for outcomes and standing "
        "promises — not chores (use tasks; link chores with tasks goal_id/"
        "attach) and not identity prefs (use memory prefer/decide). "
        "action=list for active items (or status=paused|done|dropped|all); "
        "list shows open-task counts when linked. Writes need Allow."
    )
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list",
                    "add",
                    "update",
                    "pause",
                    "resume",
                    "done",
                    "drop",
                    "remove",
                ],
                "description": (
                    "list active goals (default), add, update fields, "
                    "pause/resume/done/drop status, or hard-remove"
                ),
            },
            "title": {
                "type": "string",
                "description": "Title for add/update",
            },
            "id": {
                "type": "integer",
                "description": "Goal id for update/status/remove",
            },
            "kind": {
                "type": "string",
                "enum": ["goal", "commitment"],
                "description": "goal (default) or commitment",
            },
            "horizon": {
                "type": "string",
                "description": "Optional horizon text (e.g. this month, Q3)",
            },
            "notes": {
                "type": "string",
                "description": "Optional short notes",
            },
            "status": {
                "type": "string",
                "enum": ["active", "paused", "done", "dropped", "all"],
                "description": "For list: active (default), paused, done, dropped, or all",
            },
            "limit": {
                "type": "integer",
                "description": "Max rows for list (default 50)",
            },
        },
        "required": ["action"],
    }

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    async def run(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action") or "").strip().lower()
        if action == "list":
            return self._list(kwargs)
        if action == "add":
            return self._add(kwargs)
        if action == "update":
            return self._update(kwargs)
        if action in _STATUS_FROM_ACTION:
            return self._set_status(kwargs, action)
        if action == "remove":
            return self._remove(kwargs)
        return ToolResult(
            ok=False,
            output=(
                "Unknown action. Use list, add, update, pause, resume, "
                "done, drop, or remove."
            ),
        )

    def _list(self, kwargs: dict[str, Any]) -> ToolResult:
        raw_status = str(kwargs.get("status") or "active").strip().lower()
        if raw_status == "all":
            status: str | None = None
        elif raw_status in {"active", "paused", "done", "dropped"}:
            status = raw_status
        else:
            return ToolResult(
                ok=False,
                output="status must be active, paused, done, dropped, or all.",
            )
        kind_raw = str(kwargs.get("kind") or "").strip().lower()
        kind: str | None = kind_raw if kind_raw else None
        if kind is not None and kind not in {"goal", "commitment"}:
            return ToolResult(
                ok=False,
                output="kind must be goal or commitment.",
            )
        limit = int(kwargs.get("limit") or 50)
        if limit < 1:
            limit = 1
        rows = self.store.list_goals(status=status, kind=kind, limit=limit)
        if not rows:
            label = "active" if status == "active" else (status or "matching")
            return ToolResult(
                ok=True,
                output=f"No {label} goals.",
                data={"goals": []},
            )
        lines: list[str] = []
        for row in rows:
            gid = row.get("id")
            n_open = 0
            if gid is not None:
                n_open = len(
                    self.store.list_tasks(
                        status="open", goal_id=int(gid), limit=200
                    )
                )
            lines.append(_format_goal(row, open_tasks=n_open))
        lines.append("")
        lines.append(f"{len(rows)} goal(s).")
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={"goals": rows},
        )

    def _add(self, kwargs: dict[str, Any]) -> ToolResult:
        title = str(kwargs.get("title") or "").strip()
        if not title:
            return ToolResult(ok=False, output="goals add needs a title.")
        if len(title) > 400:
            return ToolResult(
                ok=False,
                output="That title is too long. Keep it to one short line.",
            )
        kind = str(kwargs.get("kind") or "goal").strip().lower() or "goal"
        if kind not in {"goal", "commitment"}:
            return ToolResult(
                ok=False,
                output="kind must be goal or commitment.",
            )
        horizon = str(kwargs.get("horizon") or "").strip() or None
        notes = str(kwargs.get("notes") or "").strip() or None
        if notes and len(notes) > 800:
            return ToolResult(
                ok=False,
                output="Notes are too long. Keep them under 800 characters.",
            )
        try:
            goal_id = self.store.add_goal(
                title,
                kind=kind,
                horizon=horizon,
                notes=notes,
                source="explicit",
            )
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        if goal_id is None:
            return ToolResult(ok=False, output="Could not add that goal.")
        row = self.store.get_goal(goal_id) or {
            "id": goal_id,
            "title": title,
            "kind": kind,
            "status": "active",
            "horizon": horizon,
            "notes": notes,
        }
        return ToolResult(
            ok=True,
            output=f"Added: {_format_goal(row)}",
            data={
                "id": goal_id,
                "title": title,
                "kind": kind,
                "status": "active",
                "horizon": horizon,
            },
        )

    def _update(self, kwargs: dict[str, Any]) -> ToolResult:
        goal_id = kwargs.get("id")
        if goal_id is None or str(goal_id).strip() == "":
            return ToolResult(ok=False, output="Pass id= to update a goal.")
        try:
            gid = int(goal_id)
        except (TypeError, ValueError):
            return ToolResult(ok=False, output="id must be an integer.")
        existing = self.store.get_goal(gid)
        if existing is None:
            return ToolResult(ok=False, output=f"No goal with id {gid}.")
        title = kwargs.get("title")
        kind = kwargs.get("kind")
        horizon = kwargs.get("horizon")
        notes = kwargs.get("notes")
        if (
            title is None
            and kind is None
            and horizon is None
            and notes is None
        ):
            return ToolResult(
                ok=False,
                output="Pass at least one of title, kind, horizon, or notes.",
            )
        title_text = str(title).strip() if title is not None else None
        if title_text is not None and len(title_text) > 400:
            return ToolResult(
                ok=False,
                output="That title is too long. Keep it to one short line.",
            )
        kind_text = str(kind).strip().lower() if kind is not None else None
        notes_text = str(notes) if notes is not None else None
        if notes_text is not None and len(notes_text.strip()) > 800:
            return ToolResult(
                ok=False,
                output="Notes are too long. Keep them under 800 characters.",
            )
        try:
            ok = self.store.update_goal(
                gid,
                title=title_text,
                kind=kind_text,
                horizon=str(horizon) if horizon is not None else None,
                notes=notes_text,
            )
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        if not ok:
            return ToolResult(ok=False, output=f"Could not update goal {gid}.")
        row = self.store.get_goal(gid) or existing
        return ToolResult(
            ok=True,
            output=f"Updated: {_format_goal(row)}",
            data={"id": gid, "title": row.get("title"), "status": row.get("status")},
        )

    def _set_status(self, kwargs: dict[str, Any], action: str) -> ToolResult:
        goal_id = kwargs.get("id")
        if goal_id is None or str(goal_id).strip() == "":
            return ToolResult(ok=False, output="Pass id= for this action.")
        try:
            gid = int(goal_id)
        except (TypeError, ValueError):
            return ToolResult(ok=False, output="id must be an integer.")
        existing = self.store.get_goal(gid)
        if existing is None:
            return ToolResult(ok=False, output=f"No goal with id {gid}.")
        current = str(existing.get("status") or "")
        allowed = _ALLOWED_FROM[action]
        if current not in allowed:
            return ToolResult(
                ok=False,
                output=(
                    f"Cannot {action} a goal that is {current}. "
                    f"Allowed from: {', '.join(sorted(allowed))}."
                ),
            )
        new_status = _STATUS_FROM_ACTION[action]
        if not self.store.set_goal_status(gid, new_status):
            return ToolResult(ok=False, output=f"Could not update goal {gid}.")
        row = self.store.get_goal(gid) or {**existing, "status": new_status}
        verbs = {
            "pause": "Paused",
            "resume": "Resumed",
            "done": "Done",
            "drop": "Dropped",
        }
        note = ""
        if action == "done":
            note = (
                " (still stored — default goals list shows active only; "
                "call goals action=list status=done or status=all to see it)"
            )
        return ToolResult(
            ok=True,
            output=f"{verbs[action]}: {_format_goal(row)}{note}",
            data={"id": gid, "status": new_status, "title": row.get("title")},
        )

    def _remove(self, kwargs: dict[str, Any]) -> ToolResult:
        goal_id = kwargs.get("id")
        if goal_id is None or str(goal_id).strip() == "":
            return ToolResult(ok=False, output="Pass id= to remove a goal.")
        try:
            gid = int(goal_id)
        except (TypeError, ValueError):
            return ToolResult(ok=False, output="id must be an integer.")
        existing = self.store.get_goal(gid)
        if existing is None:
            return ToolResult(ok=False, output=f"No goal with id {gid}.")
        if not self.store.remove_goal(gid):
            return ToolResult(ok=False, output=f"Could not remove goal {gid}.")
        return ToolResult(
            ok=True,
            output=f"Removed: {_format_goal(existing)}",
            data={"id": gid, "title": existing.get("title")},
        )
