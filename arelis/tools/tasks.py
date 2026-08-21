"""Local task list in memory.db.

list is free. add/done/reopen/remove/attach/detach need approval when
confirm_writes is on — same argument-dependent gate as contacts.
"""

from __future__ import annotations

from typing import Any

from arelis.core.bus import emit_nowait
from arelis.core.events import Event, EventType
from arelis.memory.store import MemoryStore
from arelis.tools.base import ToolResult

WRITE_ACTIONS = frozenset({"add", "done", "reopen", "remove", "attach", "detach"})


def _notify_tasks(action: str, **extra: Any) -> None:
    emit_nowait(Event(EventType.TASKS_CHANGED, {"action": action, **extra}))


def _format_task(row: dict[str, Any]) -> str:
    title = str(row.get("title") or "").strip() or "(untitled)"
    status = str(row.get("status") or "")
    due = str(row.get("due") or "").strip()
    tid = row.get("id")
    line = f"#{tid} [{status}] {title}"
    if due:
        line += f" (due {due})"
    gid = row.get("goal_id")
    if gid is not None and str(gid).strip() != "":
        line += f" → goal #{gid}"
    return line


class TasksTool:
    name = "tasks"
    description = (
        "List, add, complete, reopen, remove, or link local to-dos (chores) "
        "stored in memory.db. Use action=list for open tasks (or status=done|all; "
        "optional goal_id to filter). action=add needs title (optional due, "
        "goal_id). action=attach needs id + goal_id; action=detach needs id. "
        "action=done|reopen|remove need id. For durable outcomes use goals; "
        "link chores to a goal with goal_id / attach. Writes are confirmed "
        "before they are saved."
    )
    # list is free; needs_confirm special-cases write actions.
    risk = "read"
    parameters_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list",
                    "add",
                    "done",
                    "reopen",
                    "remove",
                    "attach",
                    "detach",
                ],
                "description": (
                    "list open tasks (default), add, mark done, reopen, "
                    "remove, attach to a goal, or detach from a goal"
                ),
            },
            "title": {
                "type": "string",
                "description": "Task text for action=add",
            },
            "id": {
                "type": "integer",
                "description": "Task id for done/reopen/remove/attach/detach",
            },
            "due": {
                "type": "string",
                "description": "Optional due date/text for add (e.g. 2026-08-10)",
            },
            "goal_id": {
                "type": "integer",
                "description": (
                    "Goal id: filter for list; set on add; required for attach"
                ),
            },
            "status": {
                "type": "string",
                "enum": ["open", "done", "all"],
                "description": "For list: open (default), done, or all",
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
        if action == "done":
            return self._set_status(kwargs, "done")
        if action == "reopen":
            return self._set_status(kwargs, "open")
        if action == "remove":
            return self._remove(kwargs)
        if action == "attach":
            return self._attach(kwargs)
        if action == "detach":
            return self._detach(kwargs)
        return ToolResult(
            ok=False,
            output=(
                "Unknown action. Use list, add, done, reopen, remove, "
                "attach, or detach."
            ),
        )

    def _list(self, kwargs: dict[str, Any]) -> ToolResult:
        raw_status = str(kwargs.get("status") or "open").strip().lower()
        if raw_status == "all":
            status: str | None = None
        elif raw_status in {"open", "done"}:
            status = raw_status
        else:
            return ToolResult(
                ok=False,
                output="status must be open, done, or all.",
            )
        goal_id, err = _optional_int(kwargs.get("goal_id"), label="goal_id")
        if err:
            return ToolResult(ok=False, output=err)
        limit = int(kwargs.get("limit") or 50)
        if limit < 1:
            limit = 1
        rows = self.store.list_tasks(status=status, goal_id=goal_id, limit=limit)
        if not rows:
            label = "open" if status == "open" else (status or "matching")
            suffix = f" for goal #{goal_id}" if goal_id is not None else ""
            return ToolResult(
                ok=True,
                output=f"No {label} tasks{suffix}.",
                data={"tasks": [], "goal_id": goal_id},
            )
        lines = [_format_task(row) for row in rows]
        lines.append("")
        lines.append(f"{len(rows)} task(s).")
        return ToolResult(
            ok=True,
            output="\n".join(lines),
            data={"tasks": rows, "goal_id": goal_id},
        )

    def _add(self, kwargs: dict[str, Any]) -> ToolResult:
        title = str(kwargs.get("title") or "").strip()
        if not title:
            return ToolResult(ok=False, output="tasks add needs a title.")
        if len(title) > 400:
            return ToolResult(
                ok=False,
                output="That title is too long. Keep it to one short line.",
            )
        due = str(kwargs.get("due") or "").strip() or None
        goal_id, err = _optional_int(kwargs.get("goal_id"), label="goal_id")
        if err:
            return ToolResult(ok=False, output=err)
        if goal_id is not None and self.store.get_goal(goal_id) is None:
            return ToolResult(ok=False, output=f"No goal with id {goal_id}.")
        try:
            task_id = self.store.add_task(
                title, due=due, goal_id=goal_id, source="explicit"
            )
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        if task_id is None:
            return ToolResult(ok=False, output="Could not add that task.")
        row = self.store.get_task(task_id) or {
            "id": task_id,
            "title": title,
            "status": "open",
            "due": due,
            "goal_id": goal_id,
        }
        _notify_tasks("add", id=task_id)
        return ToolResult(
            ok=True,
            output=f"Added: {_format_task(row)}",
            data={
                "id": task_id,
                "title": title,
                "status": "open",
                "due": due,
                "goal_id": goal_id,
            },
        )

    def _set_status(self, kwargs: dict[str, Any], status: str) -> ToolResult:
        tid, err = _require_int(kwargs.get("id"), label="id")
        if err or tid is None:
            return ToolResult(ok=False, output=err or "Pass id= for this action.")
        existing = self.store.get_task(tid)
        if existing is None:
            return ToolResult(ok=False, output=f"No task with id {tid}.")
        if not self.store.set_task_status(tid, status):
            return ToolResult(ok=False, output=f"Could not update task {tid}.")
        row = self.store.get_task(tid) or {**existing, "status": status}
        verb = "Done" if status == "done" else "Reopened"
        _notify_tasks(status, id=tid)
        return ToolResult(
            ok=True,
            output=f"{verb}: {_format_task(row)}",
            data={
                "id": tid,
                "status": status,
                "title": row.get("title"),
                "goal_id": row.get("goal_id"),
            },
        )

    def _remove(self, kwargs: dict[str, Any]) -> ToolResult:
        tid, err = _require_int(kwargs.get("id"), label="id")
        if err or tid is None:
            return ToolResult(ok=False, output=err or "Pass id= to remove a task.")
        existing = self.store.get_task(tid)
        if existing is None:
            return ToolResult(ok=False, output=f"No task with id {tid}.")
        if not self.store.remove_task(tid):
            return ToolResult(ok=False, output=f"Could not remove task {tid}.")
        _notify_tasks("remove", id=tid)
        return ToolResult(
            ok=True,
            output=f"Removed: {_format_task(existing)}",
            data={
                "id": tid,
                "title": existing.get("title"),
                "goal_id": existing.get("goal_id"),
            },
        )

    def _attach(self, kwargs: dict[str, Any]) -> ToolResult:
        tid, err = _require_int(kwargs.get("id"), label="id")
        if err or tid is None:
            return ToolResult(ok=False, output=err or "attach needs id=.")
        goal_id, gerr = _require_int(kwargs.get("goal_id"), label="goal_id")
        if gerr or goal_id is None:
            return ToolResult(ok=False, output=gerr or "attach needs goal_id=.")
        existing = self.store.get_task(tid)
        if existing is None:
            return ToolResult(ok=False, output=f"No task with id {tid}.")
        if self.store.get_goal(goal_id) is None:
            return ToolResult(ok=False, output=f"No goal with id {goal_id}.")
        try:
            if not self.store.set_task_goal(tid, goal_id):
                return ToolResult(ok=False, output=f"Could not attach task {tid}.")
        except ValueError as exc:
            return ToolResult(ok=False, output=str(exc))
        row = self.store.get_task(tid) or {**existing, "goal_id": goal_id}
        _notify_tasks("attach", id=tid, goal_id=goal_id)
        return ToolResult(
            ok=True,
            output=f"Attached: {_format_task(row)}",
            data={"id": tid, "goal_id": goal_id, "title": row.get("title")},
        )

    def _detach(self, kwargs: dict[str, Any]) -> ToolResult:
        tid, err = _require_int(kwargs.get("id"), label="id")
        if err or tid is None:
            return ToolResult(ok=False, output=err or "detach needs id=.")
        existing = self.store.get_task(tid)
        if existing is None:
            return ToolResult(ok=False, output=f"No task with id {tid}.")
        if existing.get("goal_id") is None:
            return ToolResult(
                ok=True,
                output=f"Already unlinked: {_format_task(existing)}",
                data={"id": tid, "goal_id": None, "title": existing.get("title")},
            )
        if not self.store.set_task_goal(tid, None):
            return ToolResult(ok=False, output=f"Could not detach task {tid}.")
        row = self.store.get_task(tid) or {**existing, "goal_id": None}
        _notify_tasks("detach", id=tid)
        return ToolResult(
            ok=True,
            output=f"Detached: {_format_task(row)}",
            data={"id": tid, "goal_id": None, "title": row.get("title")},
        )


def _optional_int(raw: Any, *, label: str) -> tuple[int | None, str | None]:
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, f"{label} must be an integer."


def _require_int(raw: Any, *, label: str) -> tuple[int | None, str | None]:
    if raw is None or str(raw).strip() == "":
        return None, f"Pass {label}= for this action."
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, f"{label} must be an integer."
