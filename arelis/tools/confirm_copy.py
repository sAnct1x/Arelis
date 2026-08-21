"""Human headlines for the confirm card. Not the tool-call trace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arelis.tools.safety import redact_secrets


def _who(args: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(args.get(key) or "").strip()
        if value:
            return redact_secrets(value)
    return ""


def _path_leaf(args: dict[str, Any]) -> str:
    raw = str(args.get("path") or "").strip()
    if not raw:
        return ""
    name = Path(raw).name
    return name or raw


def confirm_headline(tool: str, args: dict[str, Any] | None = None) -> str:
    """One lowercase line: what she wants to do, not `tool(args)`."""
    name = (tool or "").strip().lower()
    args = args or {}
    action = str(args.get("action") or "").strip().lower()

    if name == "send_sms":
        who = _who(args, "to")
        return f"text {who}" if who else "send a text"
    if name == "send_email":
        who = _who(args, "to")
        subject = _who(args, "subject")
        if who and subject:
            return f"email {who}"
        if who:
            return f"email {who}"
        return "send email"
    if name == "workspace":
        leaf = _path_leaf(args)
        if action in {"write", "create"}:
            return f"write {leaf}" if leaf else "write a file"
        if action == "edit":
            return f"edit {leaf}" if leaf else "edit a file"
        if action == "delete":
            return f"delete {leaf}" if leaf else "delete a file"
        return f"workspace {action}" if action else "change a file"
    if name == "memory":
        verbs = {
            "remember": "remember this",
            "forget": "forget this",
            "prefer": "save this preference",
            "decide": "remember this decision",
            "episode": "save this episode",
        }
        return verbs.get(action, "change memory")
    if name == "image":
        return "make a picture"
    if name == "image_edit":
        return "edit this picture"
    if name == "plot":
        leaf = Path(str(args.get("out") or "").replace("\\", "/")).name
        return f"write {leaf}" if leaf else "write a plot"
    if name == "document":
        leaf = Path(str(args.get("filename") or "").replace("\\", "/")).name
        title = _who(args, "title")
        fmt = str(args.get("format") or "").strip().lower()
        replacing = str(args.get("replace") or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
            "replace",
        }
        verb = "replace" if replacing else "write"
        if leaf:
            return f"{verb} {leaf}"
        if title and fmt:
            return f"{verb} {title}.{fmt}"
        if fmt:
            return f"{verb} a {fmt}"
        return f"{verb} a file"
    if name == "browser":
        target = _who(args, "url", "target", "query", "destination", "place")
        if action in {"open", "navigate"}:
            return f"open {target}" if target else "open her window"
        if action == "search":
            return f"search {target}" if target else "search in her window"
        if action == "click":
            return "click in her window"
        if action == "type":
            return "type in her window"
        if action == "maps":
            return f"directions to {target}" if target else "open maps"
        if action == "read":
            return "read this tab"
        if action == "screenshot":
            return "screenshot this tab"
        if action == "relaunch":
            return "restart her window"
        if action == "reserve":
            return f"reserve {target}" if target else "open a reservation"
        return f"{action} in her window" if action else "use her window"
    if name == "vision":
        return "see this image"
    if name == "camera":
        return "use the camera"
    if name == "ocr":
        return "read text on screen" if action == "screen" else "read this text"
    if name == "clipboard":
        return "read the clipboard"
    if name == "agenda":
        if action in {"create", "update"}:
            title = _who(args, "summary", "title")
            return "add to calendar" if not title else f"calendar: {title}"
        if action == "delete":
            return "delete a calendar event"
        if action == "sync":
            return "sync the calendar"
        return "change the calendar"
    if name == "contacts":
        who = _who(args, "who", "name", "id")
        if action == "remove":
            return f"remove contact {who}" if who else "remove a contact"
        return f"save contact {who}" if who else "save a contact"
    if name == "schedule":
        if action in {"create", "create_briefing"}:
            return "schedule this"
        if action == "delete":
            return "delete a scheduled job"
        if action == "run_now":
            return "run this job now"
        return "change a scheduled job"
    if name == "inbox":
        if action == "delete":
            action = "trash"
        ids = _who(args, "id")
        n = len([p for p in ids.replace(";", ",").split(",") if p.strip()]) if ids else 0
        folder = _who(args, "folder")
        sender = _who(args, "sender")
        who = sender or (f"{n} messages" if n > 1 else "this message")
        if action == "trash":
            return f"trash mail from {sender}" if sender else f"trash {who}"
        if action == "archive":
            return f"archive {who}"
        if action == "mark_read":
            return f"mark {who} read"
        if action == "mark_unread":
            return f"mark {who} unread"
        if action == "move":
            dest = folder or "a folder"
            return f"move {who} to {dest}"
        if action == "create_folder":
            return f"create folder {folder}" if folder else "create a mail folder"
        return "change the mailbox"
    if name == "rooms":
        room = _who(args, "name", "id")
        if action == "create":
            return "make a room" if not room else f"make room {room}"
        if action == "forget":
            return f"forget room {room}" if room else "forget this room"
        return "change this room"
    if name == "tasks":
        if action == "add":
            return "add a task"
        if action == "done":
            return "mark a task done"
        if action == "remove":
            return "remove a task"
        return "change a task"
    if name == "goals":
        if action == "add":
            return "add a goal"
        if action in {"done", "pause", "resume", "drop", "remove"}:
            return f"{action} a goal"
        return "change a goal"
    if name == "external_read":
        leaf = _path_leaf(args)
        return f"read {leaf}" if leaf else "read this file"
    return name.replace("_", " ") or "this step"
