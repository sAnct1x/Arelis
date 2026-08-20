from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from arelis.tools.safety import redact_secrets

# Placeholder / empty-write args must never reach an Allow card (U7).
_PLACEHOLDER_ARG = re.compile(
    r"(?i)<[^>]*>|\buser_phone_number\b|\byour_phone\b|\bphone_number_here\b|"
    r"\bTODO\b|\bTBD\b|\bxxx+\b"
)

# read        no observable change, safe to auto-run
# write       changes files on disk, gated behind the confirm card
# side_effect calls out to another local service and produces artifacts
ToolRisk = Literal["read", "write", "side_effect"]

# Capability classes (Wave 3 + trustworthy): coarser blast-radius labels for
# docs + audits. Orthogonal to ToolRisk / confirm: risk drives the card; class
# names the scope.
# READ                 no durable change
# WRITE_LOCAL          mutates local state (files, contacts, tasks, memory)
# WRITE_LOCAL_ARTIFACT writes a generated artifact (research report markdown)
# WRITE_EXTERNAL       leaves the machine (email, SMS, synced calendar)
# SIDE_EFFECT_LOCAL    local service side effect (Comfy image, VL see, browser)
CapabilityClass = Literal[
    "READ",
    "WRITE_LOCAL",
    "WRITE_LOCAL_ARTIFACT",
    "WRITE_EXTERNAL",
    "SIDE_EFFECT_LOCAL",
]

# Browser drive is a local side effect (opens/controls the user's browser).
# Confirm is gated by confirm_browser, not confirm_image.
# Vision (see one image) is gated by confirm_vision for the same reason.

# Actions that turn the workspace tool from a reader into a writer. The tool
# itself is registered as "read" because list/read are the common case, so the
# confirm gate has to look at the action argument rather than the risk field.
WORKSPACE_WRITE_ACTIONS = {"write", "edit"}
CONTACTS_WRITE_ACTIONS = {"add", "update", "remove"}
AGENDA_WRITE_ACTIONS = {"create", "update", "delete"}
TASKS_WRITE_ACTIONS = {"add", "done", "reopen", "remove", "attach", "detach"}
GOALS_WRITE_ACTIONS = {
    "add",
    "update",
    "pause",
    "resume",
    "done",
    "drop",
    "remove",
}
MEMORY_WRITE_ACTIONS = {"remember", "forget", "prefer", "decide", "episode"}
ROOMS_WRITE_ACTIONS = {"create", "update", "forget"}
SCHEDULE_WRITE_ACTIONS = {"create", "create_briefing", "delete", "run_now"}

# Approved one at a time, never covered by "allow all this turn". A file write
# can be undone by editing the file; a sent email, SMS, or calendar mutate
# cannot be casually undone, and the card is the permission step.
NEVER_BATCH = {"send_email", "send_sms", "agenda", "external_read"}


def confirm_args_blocked(name: str, args: dict[str, Any] | None) -> str | None:
    """Return a reason when this call must not show an Allow card, else None."""
    tool = (name or "").strip()
    args = args or {}
    action = str(args.get("action") or "").strip().lower()
    for key, value in args.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        if _PLACEHOLDER_ARG.search(text):
            return f"Placeholder argument {key}={text!r} — fill a real value first."
    if tool == "workspace" and action == "write":
        content = str(args.get("content") or "")
        if not content.strip():
            return "workspace write has empty content — nothing to Allow."
    if tool == "document":
        body = str(args.get("body") or "")
        rows = str(args.get("rows") or "")
        title = str(args.get("title") or "")
        from_path = str(args.get("from_path") or "")
        if (
            not body.strip()
            and not rows.strip()
            and not title.strip()
            and not from_path.strip()
        ):
            return "document has empty body — nothing to Allow."
    if tool == "contacts" and action in CONTACTS_WRITE_ACTIONS:
        phone = str(args.get("phone") or args.get("number") or "").strip()
        if phone and _PLACEHOLDER_ARG.search(phone):
            return f"Contacts phone looks like a placeholder: {phone!r}"
    return None


def capability_class(
    name: str, args: dict[str, Any] | None = None
) -> CapabilityClass:
    """Blast-radius class for a concrete tool call (argument-aware)."""
    tool = (name or "").strip()
    args = args or {}
    action = str(args.get("action") or "").strip().lower()
    if tool in {"send_email", "send_sms"}:
        return "WRITE_EXTERNAL"
    if tool == "agenda":
        if action in AGENDA_WRITE_ACTIONS:
            return "WRITE_EXTERNAL"
        # Private ICS URL → local file (option S); Allow when confirm_writes.
        if action == "sync" and str(args.get("provider") or "").strip().lower() == "ics":
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
    if tool == "workspace":
        return "WRITE_LOCAL" if action in WORKSPACE_WRITE_ACTIONS else "READ"
    if tool == "contacts":
        return "WRITE_LOCAL" if action in CONTACTS_WRITE_ACTIONS else "READ"
    if tool == "tasks":
        return "WRITE_LOCAL" if action in TASKS_WRITE_ACTIONS else "READ"
    if tool == "goals":
        return "WRITE_LOCAL" if action in GOALS_WRITE_ACTIONS else "READ"
    if tool == "memory":
        return "WRITE_LOCAL" if action in MEMORY_WRITE_ACTIONS else "READ"
    if tool == "rooms":
        return "WRITE_LOCAL" if action in ROOMS_WRITE_ACTIONS else "READ"
    if tool == "schedule":
        return "WRITE_LOCAL" if action in SCHEDULE_WRITE_ACTIONS else "READ"
    if tool == "plot":
        return "WRITE_LOCAL"
    if tool == "document":
        return "WRITE_LOCAL_ARTIFACT"
    return "READ"


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    name: str
    description: str
    parameters_schema: dict[str, Any]
    risk: ToolRisk

    async def run(self, **kwargs: Any) -> ToolResult:
        ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list(self) -> list[dict[str, str]]:
        return [{"name": t.name, "description": t.description} for t in self._tools.values()]

    def names(self) -> set[str]:
        return set(self._tools)

    def ollama_tools(self, names: set[str] | None = None) -> list[dict[str, Any]]:
        """OpenAI-style tools array for Ollama /api/chat.

        When ``names`` is set, only those tools are offered (per-turn subset).
        """
        out: list[dict[str, Any]] = []
        for tool in self._tools.values():
            if names is not None and tool.name not in names:
                continue
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters_schema,
                    },
                }
            )
        return out

    def needs_confirm(
        self,
        name: str,
        args: dict[str, Any] | None = None,
        *,
        confirm_writes: bool = True,
        confirm_image: bool = True,
        confirm_send: bool = True,
        confirm_browser: bool = True,
        confirm_vision: bool = True,
    ) -> bool:
        """Decide whether this specific call must go through the confirm card.

        Argument-dependent, not just risk-dependent: workspace(action=read) is
        free, workspace(action=write) is gated. An unknown tool returns False
        because the agent loop rejects it before it ever reaches here, and
        prompting the user to approve something that cannot run is noise.

        send_email and send_sms are named explicitly rather than riding on
        side_effect risk. That branch answers to confirm_image, named for the
        only tool that used to reach it, so turning off image confirmations
        would otherwise turn off mail/SMS confirmations as a side effect
        nobody asked for. browser and vision are gated by their own toggles
        for the same reason — they must not share the image (Comfy) toggle.
        """
        tool = self.get(name)
        if tool is None:
            return False
        args = args or {}
        if name in {"send_email", "send_sms"}:
            return confirm_send
        if name in {"image", "image_edit"}:
            # image_edit shares the image toggle rather than confirm_writes: what
            # it produces is a picture, and it writes a new file beside the
            # original rather than over anything that existed.
            return confirm_image
        if name == "browser":
            return confirm_browser
        if name == "vision":
            return confirm_vision
        if name == "camera":
            # Snapshot is a jpg write (dock shutter already does this).
            # The privacy event is the model seeing pixels (ocr / vision).
            return False
        if name == "ocr":
            # Screen grab / image text — same privacy gate as vision.
            return confirm_vision
        if name == "clipboard":
            # Privacy: clipboard often holds passwords / one-time codes.
            return confirm_writes
        if name == "workspace":
            action = str(args.get("action") or "").lower()
            return confirm_writes if action in WORKSPACE_WRITE_ACTIONS else False
        if name == "contacts":
            action = str(args.get("action") or "").lower()
            return confirm_writes if action in CONTACTS_WRITE_ACTIONS else False
        if name == "agenda":
            action = str(args.get("action") or "").lower()
            provider = str(args.get("provider") or "").lower()
            if action == "sync" and provider == "ics":
                return confirm_writes
            return confirm_writes if action in AGENDA_WRITE_ACTIONS else False
        if name == "tasks":
            action = str(args.get("action") or "").lower()
            return confirm_writes if action in TASKS_WRITE_ACTIONS else False
        if name == "goals":
            action = str(args.get("action") or "").lower()
            return confirm_writes if action in GOALS_WRITE_ACTIONS else False
        if name == "rooms":
            action = str(args.get("action") or "").lower()
            return confirm_writes if action in ROOMS_WRITE_ACTIONS else False
        if name == "schedule":
            action = str(args.get("action") or "").lower()
            return confirm_writes if action in SCHEDULE_WRITE_ACTIONS else False
        if tool.risk == "side_effect":
            return confirm_image
        if tool.risk == "write":
            return confirm_writes
        return False

    def summarize_call(self, name: str, args: dict[str, Any]) -> str:
        """One-line rendering of a pending call for the confirm card and trace.

        Redacted, because the most common thing a user is asked to approve is a
        file write, and the content being written is exactly where a key or
        password shows up. Sorted so the same call always reads the same way.
        """
        parts = [f"{k}={_short(redact_secrets(str(v)))}" for k, v in sorted(args.items())]
        joined = ", ".join(parts)
        return f"{name}({joined})" if joined else f"{name}()"

    def describe_call(self, name: str, args: dict[str, Any]) -> str:
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
            sms_tool = self.get(name)
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
        if name == "document":
            tool = self.get(name)
            preview = getattr(tool, "preview_path", None)
            dest = ""
            if callable(preview):
                try:
                    dest = str(preview(args))
                except Exception:
                    dest = ""
            title = str(args.get("title") or "").strip()
            fmt = str(args.get("format") or "").strip() or "file"
            lines = [
                f"Write a {fmt} they can open.",
                f"Lands at: {dest or '(documents folder)'}",
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
                lines.append("Glows the target, waits a beat, then clicks.")
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
        return self.summarize_call(name, args)

    async def call(self, name: str, /, **kwargs: Any) -> ToolResult:
        """Invoke a tool by name.

        `name` is positional-only on purpose. Arguments come from model output,
        so a hallucinated {"name": ...} argument would otherwise collide with
        this parameter and raise TypeError inside the agent loop, killing the
        turn with no error event and leaving the UI stuck in its busy state.
        """
        tool = self.get(name)
        if tool is None:
            return ToolResult(ok=False, output=f"Unknown tool: {name}")
        try:
            return await tool.run(**kwargs)
        except TypeError as exc:
            # Bad argument shape from the model is a recoverable tool failure,
            # not a crash: hand it back so the model can retry with valid args.
            return ToolResult(ok=False, output=f"Invalid arguments for `{name}`: {exc}")


def _short(value: Any, limit: int = 80) -> str:
    text = str(value).replace("\n", " ")
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text
