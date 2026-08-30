"""What the app says it is doing, in the user's words, while a turn runs.

A turn that calls tools paints nothing until the tools finish: the draft is
retracted when a round turns out to be a preamble, so the thread is blank on
purpose. Measured on 2026-08-14, a turn offering the full tool surface — which is
every SMS turn — cost 34 to 36 seconds cold. Half a minute of blank thread is the
single thing that made this app feel hung.

The signals that existed were not enough. The composer placeholder said "model
loading…", which stops being true the moment the model has loaded and is calling
tools. The Thinking dock was told, in developer terms — ``weather {'days': 2}`` —
and it is closed by default, so the first tool call flung it open mid-turn as the
only proof of life. And the honest "still working, the answer is held back" line
was reactive: it fired when the user pressed Esc, meaning you had to try to cancel
before the app would admit it was busy.

So this is the copy for a status line that shows without being asked, in the
transcript where the user is already looking. Phrasing rule: say the errand, not
the tool. "checking the weather", not "calling weather". The tool name is an
implementation detail the user did not choose and should not have to learn.
"""

from __future__ import annotations

from typing import Any

# The bare waiting state: a turn is running and no tool has been named yet.
THINKING_STATUS = "✦ thinking…"

# Startup pin + prefix seed. The first message waits on this; calling it
# "thinking" made a 40s load look like a hung reply.
WARMING_STATUS = "✦ loading the model…"

# Between an Allow card appearing and the user answering it. The card is on screen
# and says what it wants, so this only has to stop the shimmer from claiming work
# is happening while nothing is.
WAITING_STATUS = "✦ waiting for you…"

# The errand each tool is running, in the user's words. Anything absent falls back
# to the tool name, which is honest and dull rather than wrong.
_ERRANDS: dict[str, str] = {
    "agenda": "looking at your calendar",
    "analyze": "reading the table",
    "browser": "driving the browser",
    "calculator": "working that out",
    "cas": "working the algebra",
    "python": "running the numbers",
    "diagnostics": "running my tests",
    "camera": "looking through the camera",
    "clipboard": "reading your clipboard",
    "contacts": "looking up the contact",
    "doc_extract": "reading the document",
    "document": "writing the file",
    "git_info": "checking the repo",
    "goals": "checking your goals",
    "image": "generating an image",
    "inbound_sms": "checking your texts",
    "inbox": "checking your email",
    "memory": "remembering that",
    "ocr": "reading the text in the image",
    "recall": "looking back through our conversations",
    "research_report": "researching",
    "scrape": "reading the page",
    "schedule": "setting up the schedule",
    "send_email": "writing the email",
    "send_sms": "writing the text",
    "tasks": "checking your tasks",
    "user_location": "working out where you are",
    "vision": "looking at the image",
    "weather": "checking the weather",
    "web_search": "searching the web",
    "workspace": "reading the file",
    "earth": "looking at Earth",
    "solar": "looking at Reality",
}

# A few tools do more than one thing, and the difference is worth a word. Keyed by
# tool, then by the action argument the tool declares.
_BY_ACTION: dict[str, dict[str, str]] = {
    "workspace": {
        "read": "reading the file",
        "write": "saving the file",
        "list": "looking through the folder",
        "search": "searching your files",
    },
    "memory": {
        "add": "remembering that",
        "search": "checking what I remember",
        "list": "checking what I remember",
    },
    "tasks": {
        "add": "adding that task",
        "done": "closing that task",
        "list": "checking your tasks",
    },
    "goals": {
        "add": "adding that goal",
        "list": "checking your goals",
    },
    "inbox": {
        "list": "checking your email",
        "read": "reading the email",
        "search": "searching your email",
    },
    "schedule": {
        "create": "setting up the schedule",
        "create_briefing": "setting up the morning briefing",
        "delete": "removing that schedule",
        "list": "checking your schedules",
        "run_now": "running that job now",
    },
    "earth": {
        "enter": "looking at Earth",
        "leave": "leaving Earth",
        "live": "pulling live Earth feeds",
        "dump": "writing an Earth dump",
        "track": "tracking a contact",
        "ride": "riding a contact",
        "search": "searching Earth contacts",
        "coverage": "checking Earth coverage",
        "layer": "toggling an Earth layer",
        "status": "looking at Earth",
    },
}


def tool_errand(tool: str, args: dict[str, Any] | None = None) -> str:
    """The errand in her words, no star. Empty if there is no tool."""
    name = (tool or "").strip()
    if not name:
        return ""
    action = str((args or {}).get("action") or "").strip().lower()
    errand = _BY_ACTION.get(name, {}).get(action) or _ERRANDS.get(name)
    return errand or f"using {name}"


def tool_status_line(tool: str, args: dict[str, Any] | None = None) -> str:
    """The shimmer line for a tool that just started.

    Falls back to the tool's own name rather than inventing an errand for it. A
    new tool should read as slightly unpolished, not as the wrong sentence.
    """
    errand = tool_errand(tool, args)
    if not errand:
        return THINKING_STATUS
    return f"✦ {errand}…"


__all__ = [
    "THINKING_STATUS",
    "WAITING_STATUS",
    "WARMING_STATUS",
    "tool_errand",
    "tool_status_line",
]
