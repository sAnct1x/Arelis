"""One table for Allow, capability class, and batch rules.

OpenAI's 2026 Agents SDK treats approval as a per-call decision
(``needs_approval`` bool or callable) and a persisted interruption. Arelis
already pauses on the bus; this module is the missing table those pauses
read. ``ToolRegistry.needs_confirm`` and ``capability_class`` used to each
re-list the same write-actions. Adding a tool meant editing both and hoping
they stayed twins.

Risk on the Tool object still answers "what kind of thing is this." This
table answers "does *this* call pause, and how wide is the blast." They are
orthogonal on purpose: workspace is risk=read because list/read is the
common case; write/edit still pause.

Do not shrink the tool schema from here. Authorization (hide send unless
this utterance asked) lives in ``tool_subset``. Jobs omit tools with
``build_tool_registry(attended=False)``; they do not consult this table
to drop Comfy ``image`` — that registration is pinned by tests.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from arelis.paths import display_path
from arelis.tools.safety import redact_secrets

# read        no observable change, safe to auto-run
# write       changes files on disk, gated behind the confirm card
# side_effect calls out to another local service and produces artifacts
ToolRisk = Literal["read", "write", "side_effect"]

# Orthogonal to ToolRisk / confirm: risk drives the card; class names the scope.
CapabilityClass = Literal[
    "READ",
    "WRITE_LOCAL",
    "WRITE_LOCAL_ARTIFACT",
    "WRITE_EXTERNAL",
    "SIDE_EFFECT_LOCAL",
]

# Actions that turn a reader into a writer. The tool is registered as "read"
# because list/read is the common case; the gate looks at the action argument.
WORKSPACE_WRITE_ACTIONS = frozenset({"write", "edit", "keep", "delete", "remove"})
CONTACTS_WRITE_ACTIONS = frozenset({"add", "update", "remove"})
AGENDA_WRITE_ACTIONS = frozenset({"create", "update", "delete"})
TASKS_WRITE_ACTIONS = frozenset({"add", "done", "reopen", "remove", "attach", "detach"})
GOALS_WRITE_ACTIONS = frozenset({
    "add",
    "update",
    "pause",
    "resume",
    "done",
    "drop",
    "remove",
})
MEMORY_WRITE_ACTIONS = frozenset({"remember", "forget", "prefer", "decide", "episode"})
ROOMS_WRITE_ACTIONS = frozenset({"create", "update", "forget"})
SCHEDULE_WRITE_ACTIONS = frozenset({"create", "create_briefing", "delete", "run_now"})
SOLAR_WRITE_ACTIONS = frozenset({
    "impulse",
    "add_probe",
    "add_planet",
    "fetch_maps",
    "tracer",
    "l4",
    "epoch",
})
INBOX_WRITE_ACTIONS = frozenset({
    "trash",
    "delete",
    "archive",
    "mark_read",
    "mark_unread",
    "move",
    "create_folder",
})

# Approved one at a time, never covered by "allow all this turn".
NEVER_BATCH = frozenset({"send_email", "send_sms", "agenda", "external_read", "inbox"})

ConfirmToggle = Literal["none", "send", "image", "browser", "vision", "writes"]


def _action(args: dict[str, Any] | None) -> str:
    return str((args or {}).get("action") or "").strip().lower()


def _inbox_action(args: dict[str, Any] | None) -> str:
    action = _action(args)
    return "trash" if action == "delete" else action


# Filament: the spoken ask is the grant. Only a destructive call pauses.
_CONFIRM_MODE = "card"

DELETE_ACTIONS = {
    "contacts": frozenset({"remove"}),
    "agenda": frozenset({"delete"}),
    "tasks": frozenset({"remove"}),
    "goals": frozenset({"drop", "remove"}),
    "memory": frozenset({"forget"}),
    "rooms": frozenset({"forget"}),
    "schedule": frozenset({"delete"}),
    "inbox": frozenset({"trash", "delete"}),
    "workspace": frozenset({"delete", "remove"}),
}


def set_confirm_mode(mode: str) -> None:
    """card (sodium) or voice (filament). Tests reset this via apply_theme."""
    global _CONFIRM_MODE
    _CONFIRM_MODE = "voice" if (mode or "").strip().lower() == "voice" else "card"


def confirm_mode() -> str:
    return _CONFIRM_MODE


def action_is_delete(name: str, args: dict[str, Any] | None) -> bool:
    """True when this call removes something that cannot be walked back easily."""
    tool = (name or "").strip()
    action = _inbox_action(args) if tool == "inbox" else _action(args)
    wanted = DELETE_ACTIONS.get(tool)
    return bool(wanted and action in wanted)


def _browser_is_pay(args: dict[str, Any] | None) -> bool:
    """Checkout / Pay / Buy — she stops. You click, or you say yes."""
    from arelis.browser.walls import pay_cta_label

    action = _action(args)
    if action not in {"click", "press", "type"}:
        return False
    raw = args or {}
    label = str(raw.get("text") or raw.get("target") or raw.get("url") or "")
    return pay_cta_label(label) is not None


def action_is_destructive(name: str, args: dict[str, Any] | None) -> bool:
    """Pay, delete, forget. Writes, sends, and opening a page are not this."""
    if action_is_delete(name, args):
        return True
    return (name or "").strip() == "browser" and _browser_is_pay(args)


def action_is_write(name: str, args: dict[str, Any] | None) -> bool:
    """True when this call's action is in that tool's write set."""
    tool = (name or "").strip()
    action = _action(args)
    table = {
        "workspace": WORKSPACE_WRITE_ACTIONS,
        "contacts": CONTACTS_WRITE_ACTIONS,
        "agenda": AGENDA_WRITE_ACTIONS,
        "tasks": TASKS_WRITE_ACTIONS,
        "goals": GOALS_WRITE_ACTIONS,
        "memory": MEMORY_WRITE_ACTIONS,
        "rooms": ROOMS_WRITE_ACTIONS,
        "schedule": SCHEDULE_WRITE_ACTIONS,
        "solar": SOLAR_WRITE_ACTIONS,
        "inbox": INBOX_WRITE_ACTIONS,
    }
    writes = table.get(tool)
    if writes is None:
        return False
    if tool == "inbox":
        return _inbox_action(args) in writes
    if tool == "agenda" and action == "sync":
        provider = str((args or {}).get("provider") or "").strip().lower()
        return provider == "ics"
    return action in writes


def confirm_toggle(
    name: str,
    args: dict[str, Any] | None = None,
    *,
    risk: ToolRisk | None = None,
) -> ConfirmToggle:
    """Which Settings toggle this call answers to, or none."""
    tool = (name or "").strip()
    if tool in {"send_email", "send_sms"}:
        return "send"
    if tool in {"image", "image_edit"}:
        return "image"
    if tool == "browser":
        return "browser"
    if tool == "vision":
        return "vision"
    if tool == "camera":
        return "none"
    if tool == "ocr":
        return "vision"
    if tool == "earth":
        return "none"
    if tool == "clipboard":
        return "writes"
    if tool in {
        "workspace",
        "contacts",
        "agenda",
        "tasks",
        "goals",
        "rooms",
        "solar",
        "schedule",
        "inbox",
    }:
        return "writes" if action_is_write(tool, args) else "none"
    if risk == "side_effect":
        return "image"
    if risk == "write":
        return "writes"
    return "none"


def evaluate_confirm(
    name: str,
    args: dict[str, Any] | None = None,
    *,
    risk: ToolRisk | None = None,
    confirm_writes: bool = True,
    confirm_image: bool = True,
    confirm_send: bool = True,
    confirm_browser: bool = True,
    confirm_vision: bool = True,
) -> bool:
    """Decide whether this call must go through the confirm card.

    Argument-dependent, not just risk-dependent. An unknown tool (no risk)
    and a read action both return False — the loop rejects unknown names
    before it reaches here.

    Voice mode (filament) skips the card: saying the ask is the grant.
    Destructive calls still pause so she can ask out loud.
    """
    if _CONFIRM_MODE == "voice":
        return action_is_destructive(name, args)
    toggle = confirm_toggle(name, args, risk=risk)
    if toggle == "send":
        return confirm_send
    if toggle == "image":
        return confirm_image
    if toggle == "browser":
        return confirm_browser
    if toggle == "vision":
        return confirm_vision
    if toggle == "writes":
        return confirm_writes
    return False


def evaluate_capability(
    name: str, args: dict[str, Any] | None = None
) -> CapabilityClass:
    """Blast-radius class for a concrete tool call (argument-aware)."""
    tool = (name or "").strip()
    action = _action(args)
    if tool in {"send_email", "send_sms"}:
        return "WRITE_EXTERNAL"
    if tool == "inbox":
        return "WRITE_EXTERNAL" if action_is_write(tool, args) else "READ"
    if tool == "agenda":
        if action in AGENDA_WRITE_ACTIONS:
            return "WRITE_EXTERNAL"
        if action == "sync" and str((args or {}).get("provider") or "").strip().lower() == "ics":
            return "WRITE_LOCAL"
        return "READ"
    if tool == "research_report":
        return "WRITE_LOCAL_ARTIFACT"
    if tool in {
        "image",
        "image_edit",
        "browser",
        "vision",
        "camera",
        "clipboard",
        "ocr",
    }:
        return "SIDE_EFFECT_LOCAL"
    if tool in {
        "workspace",
        "contacts",
        "tasks",
        "goals",
        "memory",
        "rooms",
        "solar",
        "schedule",
    }:
        return "WRITE_LOCAL" if action_is_write(tool, args) else "READ"
    if tool == "earth":
        return "READ"
    if tool == "plot":
        return "WRITE_LOCAL"
    if tool == "document":
        return "WRITE_LOCAL_ARTIFACT"
    return "READ"


def batch_ok(name: str) -> bool:
    """False when this tool must never ride along with 'rest of this ask'."""
    return (name or "").strip() not in NEVER_BATCH


def confirm_toggles_for_call(
    name: str,
    *,
    confirm_writes: bool,
    confirm_image: bool,
    confirm_send: bool,
    confirm_browser: bool,
    confirm_vision: bool,
    allow_writes_this_turn: bool,
) -> dict[str, bool]:
    """Turn-scoped toggles. 'Rest of this ask' does not cover mail/SMS/agenda."""
    return {
        "confirm_writes": confirm_writes
        and (not allow_writes_this_turn or name == "agenda"),
        "confirm_image": confirm_image and not allow_writes_this_turn,
        "confirm_send": confirm_send,
        "confirm_browser": confirm_browser and not allow_writes_this_turn,
        "confirm_vision": confirm_vision and not allow_writes_this_turn,
    }


def describe_call(
    name: str,
    args: dict[str, Any],
    *,
    lookup: Callable[[str], Any] | None = None,
    summarize: Callable[[str, dict[str, Any]], str] | None = None,
) -> str:
    """A fuller rendering of a pending call, for the confirm card.

    summarize_call is one line with every argument cut to 80 characters,
    which is right for a trace and wrong for an approval. An email is the
    case that breaks it: the recipient runs off the end and the body never
    appears at all, so there is nothing to actually approve.
    """
    if name == "send_email":
        to = str(args.get("to") or "").strip() or "(you)"
        subject = str(args.get("subject") or "").strip() or "(no subject)"
        body = redact_secrets(str(args.get("body") or "")).strip()
        return f"To:      {to}\nSubject: {subject}\n\n{body}"
    if name == "send_sms":
        from arelis.sms import format_sms_confirm

        to = str(args.get("to") or "").strip()
        body = redact_secrets(str(args.get("body") or "")).strip()
        # Prefer the tool's loader so tests (and any future alternate book)
        # match what send_sms will actually resolve.
        contacts = None
        sms_tool = (lookup or (lambda _n: None))(name)
        loader = getattr(sms_tool, "_load_contacts", None)
        if callable(loader):
            contacts = loader()
        return format_sms_confirm(to, body, contacts=contacts)
    if name == "contacts":
        action = str(args.get("action") or "").strip().lower() or "?"
        who = str(args.get("who") or args.get("id") or "").strip() or "(missing id)"
        if action == "remove":
            return f"Remove contact: {who}"
        lines = [f"Action:  {action}", f"Id/who:  {who}"]
        for label, key in (
            ("Name", "name"),
            ("Phone", "phone"),
            ("Aliases", "aliases"),
            ("Email", "email"),
        ):
            value = str(args.get(key) or "").strip()
            if value:
                lines.append(f"{label}:{' ' * (9 - len(label))}{value}")
        return "\n".join(lines)
    if name == "image":
        prompt = redact_secrets(str(args.get("prompt") or "")).strip() or "(no prompt)"
        return (
            "Generate an image with ComfyUI.\n"
            "If ComfyUI is not already running, Arelis will start it "
            "(uses GPU/VRAM).\n\n"
            f"Prompt: {prompt}"
        )
    if name == "external_read":
        path = str(args.get("path") or "").strip() or "(path)"
        return (
            "Read-only access to a file outside the workspace roots "
            "for this session.\n\n"
            f"Path: {path}\n\n"
            "Arelis will not write or edit this path."
        )
    if name == "plot":
        tool = (lookup or (lambda _n: None))(name)
        preview = getattr(tool, "preview_path", None)
        dest = ""
        if callable(preview):
            try:
                dest = display_path(preview(args))
            except Exception:
                dest = ""
        action = str(args.get("action") or "line").strip() or "line"
        lines = [
            f"Write a {action} chart you can open.",
            f"Lands in: {dest or 'the plots folder'}",
        ]
        title = str(args.get("title") or "").strip()
        if title:
            lines.append(f"Title: {title}")
        return "\n".join(lines)
    if name == "inbox":
        action = str(args.get("action") or "").strip().lower() or "list"
        if action == "delete":
            action = "trash"
        ids = str(args.get("id") or "").strip()
        folder = str(args.get("folder") or "").strip()
        lines = [f"Mailbox {action}"]
        if ids:
            lines.append(f"Id: {ids}")
        if folder:
            lines.append(f"Folder: {folder}")
        sender = str(args.get("sender") or "").strip()
        if sender:
            lines.append(f"From: {sender}")
        if action == "trash":
            lines.append("Goes to Trash (Gmail Bin), not gone forever.")
        return "\n".join(lines)
    if name == "document":
        tool = (lookup or (lambda _n: None))(name)
        preview = getattr(tool, "preview_path", None)
        dest = ""
        if callable(preview):
            try:
                dest = display_path(preview(args))
            except Exception:
                dest = ""
        title = str(args.get("title") or "").strip()
        fmt = str(args.get("format") or "").strip() or "file"
        lines = [
            f"Write a {fmt} you can open.",
            f"Lands in: {dest or 'the documents folder'}",
        ]
        if title:
            lines.append(f"Title: {title}")
        source = str(args.get("from_path") or "").strip()
        if source:
            lines.append(f"From: {source}")
        return "\n".join(lines)
    if name == "vision":
        path = str(args.get("path") or "").strip() or "(path)"
        question = str(args.get("question") or "").strip()
        lines = [
            "See local image (vision)",
            f"Path: {path}",
        ]
        if question:
            lines.append(f"Question: {question}")
        else:
            lines.append("Question: (default describe)")
        lines.append(
            "Unloads the chat model briefly, runs the VL model, then "
            "rewarms conversation. One still — seeing does not authorize "
            "sending or navigating."
        )
        return "\n".join(lines)
    if name == "browser":
        action = str(args.get("action") or "").strip().lower() or "?"
        which = str(args.get("browser") or "default").strip() or "default"
        lines = [
            f"Browser {action}",
            f"Browser: {which}",
        ]
        if args.get("private"):
            lines.append("Private: yes (Firefox)")
        for label, key in (
            ("URL", "url"),
            ("Target", "target"),
            ("Ref", "ref"),
            ("Text", "text"),
        ):
            value = str(args.get(key) or "").strip()
            if value:
                lines.append(f"{label}: {value}")
        if action == "open":
            lines.append(
                "Shows this URL in Arelis Chrome (same tab, not a second copy)."
            )
        if action == "scroll":
            lines.append("Scrolls the page or a snapshot ref into view.")
        if action == "press":
            lines.append("Presses a key in her Chrome (Enter, Escape, Tab, arrows).")
        if action == "select":
            lines.append("Picks a dropdown option (snapshot ref + option text).")
        if action == "wait":
            lines.append("Pauses briefly so the page can settle (max 8s).")
        if action == "click":
            lines.append(
                "Glows the target in her Chrome, waits a beat, then clicks. "
                "text= is the visible label; nth=1 is the first result."
            )
        if action == "type":
            lines.append(
                "Types into a non-secret field. into= is the field label "
                "(search, email). She does not type passwords."
            )
        if action == "back":
            lines.append("Goes back one page in her Chrome. The tab stays.")
        if action == "forward":
            lines.append("Goes forward one page in her Chrome.")
        if action == "reload":
            lines.append("Reloads the current tab.")
        if action == "find":
            lines.append("Lists visible controls matching the text. Does not click.")
        if action == "tabs":
            tab = str(args.get("tab") or "").strip().lower()
            if tab == "new":
                lines.append("Opens a new tab in her Chrome.")
            elif tab == "close":
                lines.append("Closes the current tab. The window stays.")
        if action == "navigate":
            lines.append(
                "Navigates a controlled browser tab. If the browser is open "
                "without debugging, may restart it with control."
            )
        if action == "relaunch":
            lines.append(
                "This will close and restart the browser with control enabled "
                "(session restore when supported)."
            )
            if str(args.get("url") or args.get("target") or "").strip():
                lines.append("Then open the URL/target above.")
        if action == "screenshot":
            lines.append(
                "Saves a PNG under outputs/images/. Describe it with vision "
                "in a follow-up call (not automatic)."
            )
            if args.get("full_page"):
                lines.append("Full page: yes")
        if action == "read":
            lines.append(
                "Reads compact text of the tab she is on (not a web scrape)."
            )
        if action == "maps":
            dest = str(args.get("destination") or args.get("url") or "").strip()
            if dest:
                lines.append(f"Destination: {dest}")
            lines.append(
                "Opens Google Maps directions in her Chrome and returns "
                "a phone link you can text."
            )
        if action == "search":
            query = str(args.get("query") or args.get("text") or "").strip()
            site = str(args.get("site") or "google").strip() or "google"
            if query:
                lines.append(f"Query: {query}")
            lines.append(f"Site: {site}")
            lines.append(
                "Opens search results in her Chrome. Add to cart is fine; "
                "stop before Checkout / Pay."
            )
        if action == "reserve":
            place = str(
                args.get("place") or args.get("query") or args.get("destination") or ""
            ).strip()
            if place:
                lines.append(f"Place: {place}")
            party = args.get("party")
            if party not in (None, ""):
                lines.append(f"Party: {party}")
            if str(args.get("date") or "").strip():
                lines.append(f"Date: {args.get('date')}")
            if str(args.get("time") or "").strip():
                lines.append(f"Time: {args.get('time')}")
            lines.append(
                "Opens OpenTable (or Resy / Google) with party/date/time "
                "in the URL. You click Book / Reserve."
            )
        return "\n".join(lines)
    if name == "clipboard":
        return (
            "Read system clipboard text\n"
            "May include passwords or private notes — only if you "
            "intend to share what is currently copied."
        )
    if name == "ocr":
        action = str(args.get("action") or "").strip().lower() or "text"
        if action == "screen":
            return (
                "Capture primary screen and OCR with local Tesseract (CPU)\n"
                "Saves a PNG under outputs/images/, then extracts text."
            )
        path = str(args.get("path") or "").strip() or "?"
        return (
            f"OCR local image (Tesseract CPU)\nPath: {path}\n"
            "One still — seeing does not authorize sending or navigating."
        )
    if name == "agenda":
        action = str(args.get("action") or "").strip().lower() or "?"
        provider = str(args.get("provider") or "").strip().lower() or "?"
        lines = [
            f"Calendar {action}",
            f"Provider: {provider}",
        ]
        if action == "sync" and provider == "ics":
            lines.append(
                "Download calendar.ics_url from secrets into the local "
                "ICS file (overwrites tools.briefing.calendar_path)."
            )
            return "\n".join(lines)
        for label, key in (
            ("Title", "summary"),
            ("Start", "start"),
            ("End", "end"),
            ("Keep", "keep"),
            ("Event id", "event_id"),
            ("Location", "location"),
        ):
            value = str(args.get(key) or "").strip()
            if value:
                lines.append(f"{label}: {value}")
        if args.get("all_day"):
            lines.append("All-day: yes")
        return "\n".join(lines)
    if name == "tasks":
        action = str(args.get("action") or "").strip().lower() or "?"
        if action == "remove":
            return f"Remove task #{args.get('id') or '?'}"
        if action == "done":
            return f"Mark task #{args.get('id') or '?'} done"
        if action == "reopen":
            return f"Reopen task #{args.get('id') or '?'}"
        if action == "attach":
            return (
                f"Attach task #{args.get('id') or '?'} → "
                f"goal #{args.get('goal_id') or '?'}"
            )
        if action == "detach":
            return f"Detach task #{args.get('id') or '?'} from goal"
        lines = [f"Action:  {action}"]
        title = str(args.get("title") or "").strip()
        if title:
            lines.append(f"Title:   {title}")
        due = str(args.get("due") or "").strip()
        if due:
            lines.append(f"Due:     {due}")
        tid = args.get("id")
        if tid is not None and str(tid).strip() != "":
            lines.append(f"Id:      {tid}")
        gid = args.get("goal_id")
        if gid is not None and str(gid).strip() != "":
            lines.append(f"Goal:    #{gid}")
        return "\n".join(lines)
    if name == "goals":
        action = str(args.get("action") or "").strip().lower() or "?"
        verbs = {
            "remove": "Hard-remove goal",
            "done": "Mark goal done",
            "pause": "Pause goal",
            "resume": "Resume goal",
            "drop": "Drop goal (soft abandon)",
            "add": "Add goal",
            "update": "Update goal",
        }
        head = verbs.get(action, f"Goal {action}")
        lines = [head]
        tid = args.get("id")
        if tid is not None and str(tid).strip() != "":
            lines.append(f"Id:      {tid}")
        title = str(args.get("title") or "").strip()
        if title:
            lines.append(f"Title:   {title}")
        kind = str(args.get("kind") or "").strip()
        if kind:
            lines.append(f"Kind:    {kind}")
        horizon = str(args.get("horizon") or "").strip()
        if horizon:
            lines.append(f"Horizon: {horizon}")
        return "\n".join(lines)
    if name == "workspace":
        action = str(args.get("action") or "").strip().lower() or "?"
        path = str(args.get("path") or "").strip() or "(path)"
        lines = [f"Workspace {action}", f"Path: {path}"]
        if action in {"write", "edit"}:
            content = redact_secrets(str(args.get("content") or args.get("new_text") or ""))
            if not content.strip():
                lines.append("Content: (empty)")
            else:
                preview = content if len(content) <= 1200 else content[:1199] + "…"
                lines.append("")
                lines.append(preview)
        return "\n".join(lines)
    if summarize is not None:
        return summarize(name, args)
    return f"{name}()"
