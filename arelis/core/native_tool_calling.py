"""Helper for checking native_tool_calling experiment flag.

When `agent.native_tool_calling=true`, the regex/intent routing layer
is disabled so models with strong native tool calling can select tools
without deterministic preflight nudges or redirects fighting their choices.

Safety gates (SMS/email authorization, confirm-before-write, workspace
boundary, banned tools) stay ON regardless of this flag.
"""

from __future__ import annotations

import re
from typing import Any


def native_tool_calling(agent_cfg: dict[str, Any] | None) -> bool:
    """Return true when native tool calling experiment is enabled.

    Args:
        agent_cfg: Agent configuration dict (may be None or empty)

    Returns:
        True when agent.native_tool_calling is explicitly true, else false
    """
    if agent_cfg is None:
        return False
    return bool(agent_cfg.get("native_tool_calling", False))


# Parameter descriptions to keep when native_tool_calling is on.
# Maps (tool_name, param_name) to the description string.
NATIVE_PARAM_HINTS: dict[tuple[str, str], str] = {
    ("notes", "text"): "Note body. REQUIRED for action=add.",
    ("workspace", "content"): "File body. REQUIRED for action=write.",
    ("tasks", "goal_id"): "Attach to a GOAL id (from goals).",
    ("tasks", "parent_id"): "ONLY a parent TASK id (subtask), never a goal id.",
    ("catalog", "target"): "Body name only (Moon, Mars, 499). Not a sentence.",
    ("catalog", "date"): (
        "Omit for how far, closest, or farthest. APOD or one sky day only."
    ),
    ("catalog", "query"): "arxiv or ads search text only. Not a planet.",
}

# For notes tool, only expose 'text' in native mode, not the aliases
NATIVE_NOTES_ONLY_TEXT = True


def native_arg_problem(name: str, args: dict[str, Any] | None) -> str | None:
    """Check for missing required arguments in native tool calling mode.
    
    Returns a blocking message when required arguments are missing, else None.
    This is called only when native_tool_calling is enabled.
    """
    tool = (name or "").strip()
    args = args or {}
    action = str(args.get("action") or "").strip().lower()
    
    # notes add needs text (or content/body/fact aliases)
    if tool == "notes" and action == "add":
        text = str(
            args.get("text")
            or args.get("content")
            or args.get("body")
            or args.get("fact")
            or ""
        )
        if not text.strip():
            return (
                "notes add needs text=<the note body>. "
                "Call notes again with action=add, title, text."
            )
    
    # workspace write needs content (None is invalid, empty string is valid)
    if tool == "workspace" and action == "write":
        content = args.get("content")
        if content is None:
            return (
                "workspace write needs content=<the exact file text>. "
                "Call workspace again with action=write, path, content."
            )
    
    return None


# Pattern to detect "no task with id N" errors from tasks tool
_TASKS_NO_TASK_PATTERN = re.compile(r"no task with id (\d+)", re.IGNORECASE)


def append_native_task_hint(
    name: str,
    args: dict[str, Any] | None,
    ok: bool,
    output: str,
) -> str:
    """Append a hint to tasks tool output when parent_id vs goal_id is confused.
    
    Called as a post-result hook only when native_tool_calling is enabled.
    Returns the possibly-modified output string.
    """
    if name != "tasks" or ok:
        return output
    
    args = args or {}
    action = str(args.get("action") or "").strip().lower()
    
    # Only for action=add with parent_id but no goal_id
    if action != "add":
        return output
    
    parent_id = args.get("parent_id")
    goal_id = args.get("goal_id")
    
    # Only hint when parent_id was provided and goal_id was not
    if parent_id is None or goal_id is not None:
        return output
    
    # Check if the error matches "no task with id N"
    match = _TASKS_NO_TASK_PATTERN.search(output)
    if match:
        task_id = match.group(1)
        return (
            f"{output} parent_id is a TASK id. "
            f"To file under goal #{task_id} use goal_id={task_id}."
        )
    
    return output
