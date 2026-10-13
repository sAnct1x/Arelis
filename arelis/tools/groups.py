"""Tool groups for a later loader. Nothing in the product imports this yet.

Core stays in the always-loaded set. Every other tool sits in exactly one
group. Menu phrases and keywords are plain lowercase text a later menu can
show and match. Insertion order of GROUPS is the menu order.
"""

from __future__ import annotations

CORE: tuple[str, ...] = (
    "recall",
    "memory",
    "web_search",
    "web_fetch",
    "scrape",
    "calculator",
    "units",
    "weather",
    "user_location",
    "notes",
    "remind",
    "clipboard",
    "python",
    "diagnostics",
    "tile",
)

GROUPS: dict[str, tuple[str, ...]] = {
    "images": ("image", "image_edit", "vision", "camera", "ocr", "diagram"),
    "comms": ("send_sms", "inbound_sms", "send_email", "inbox", "contacts"),
    "calendar": ("agenda", "schedule", "tasks", "goals"),
    "astro": ("solar", "earth", "catalog", "cas", "plot", "data_cell"),
    "files": (
        "workspace",
        "document",
        "pdf",
        "doc_extract",
        "analyze",
        "sql",
        "transcribe",
    ),
    "code": ("git_info", "run_script", "run_task"),
    "research": ("research_report", "browser"),
    "pc_home": ("desktop", "rooms", "watch"),
}

MENU: dict[str, str] = {
    "images": "images (draw, edit, look, camera, read text, diagrams)",
    "comms": "comms (text, email, inbox, contacts)",
    "calendar": "calendar (agenda, schedule, tasks, goals)",
    "astro": "astro (solar, earth, catalogs, algebra, plots, data)",
    "files": "files (workspace, documents, pdf, extract, tables, audio)",
    "code": "code (git, scripts, project tasks)",
    "research": "research (reports, browser)",
    "pc_home": "pc and home (desktop, rooms, watch)",
}

KEYWORDS: dict[str, tuple[str, ...]] = {
    "images": (
        "image",
        "images",
        "picture",
        "pictures",
        "pic",
        "photo",
        "photos",
        "draw",
        "drawing",
        "edit",
        "vision",
        "look",
        "look at",
        "camera",
        "webcam",
        "ocr",
        "read text",
        "diagram",
        "diagrams",
        "diagramme",
        "screenshot",
    ),
    "comms": (
        "sms",
        "text",
        "text message",
        "texts",
        "send a text",
        "email",
        "e mail",
        "mail",
        "inbox",
        "contact",
        "contacts",
        "phone book",
        "message",
    ),
    "calendar": (
        "calendar",
        "calender",
        "calandar",
        "agenda",
        "schedule",
        "appointment",
        "meeting",
        "todo",
        "to do",
        "to do list",
        "goal",
        "goals",
        "task",
        "tasks",
    ),
    "astro": (
        "astro",
        "astronomy",
        "solar",
        "sun",
        "planet",
        "planets",
        "earth",
        "quake",
        "earthquake",
        "catalog",
        "catalogue",
        "cas",
        "algebra",
        "equation",
        "plot",
        "chart",
        "graph",
        "data cell",
        "fits",
    ),
    "files": (
        "file",
        "files",
        "workspace",
        "folder",
        "document",
        "doc",
        "pdf",
        "extract",
        "analyze",
        "analyse",
        "sql",
        "database",
        "spreadsheet",
        "transcribe",
        "transcription",
        "audio",
    ),
    "code": (
        "git",
        "commit",
        "repo",
        "repository",
        "script",
        "run script",
        "run a script",
        "run task",
        "code",
    ),
    "research": (
        "research",
        "report",
        "research report",
        "browser",
        "browse",
        "web browser",
        "chrome",
    ),
    "pc_home": (
        "desktop",
        "computer",
        "pc",
        "rooms",
        "room",
        "watch",
        "window",
    ),
}

_BY_TOOL: dict[str, str] = {name: "core" for name in CORE}
for _group, _names in GROUPS.items():
    for _name in _names:
        _BY_TOOL[_name] = _group


def group_of(tool_name: str) -> str | None:
    """Return "core", a group name, or None when the tool is not in the table."""
    return _BY_TOOL.get(tool_name)


def tools_in(group: str) -> tuple[str, ...]:
    """Tools in one group. "core" is the always-loaded set."""
    if group == "core":
        return CORE
    return GROUPS[group]
