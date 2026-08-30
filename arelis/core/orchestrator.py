from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
from pathlib import Path
from typing import Any
from uuid import uuid4

from arelis.attachments import (
    continue_prior_attachment_ask,
    continue_prior_image_describe,
    format_attachments_block,
)
from arelis.browser.hold import set_paused
from arelis.config import load_persona
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.confirm_speech import (
    apply_confirm_edit,
    classify_hangup,
    classify_voice_act,
)
from arelis.core.events import Event, EventType
from arelis.core.failure_copy import turn_failed_notice
from arelis.core.memory import SessionMemory, tool_trace_entry, tool_trace_note
from arelis.core.untrusted import confirm_note_after_external
from arelis.llm.router import ModelRole, ModelRouter
from arelis.memory.store import MemoryStore
from arelis.rooms import (
    Room,
    RoomStore,
    looks_like_room_name,
    match_enter_intent,
    match_leave_intent,
    match_list_rooms_intent,
    match_make_room_intent,
    normalize_room_name,
)
from arelis.spatial import PHYSICS_ROOM_ID
from arelis.spatial.verbs import classify_physics_act, speech_body_names
from arelis.tools.base import NEVER_BATCH, ToolRegistry
from arelis.tools.confirm_copy import confirm_headline
from arelis.tools.safety import redact_secrets
from arelis.workspace import _WINDOWS_DRIVE, WorkspaceRoots

# Absolute paths typed in chat that may need a session read grant.
_ABS_PATH_TOKEN = re.compile(
    r"(?P<path>"
    r"(?:[A-Za-z]:[\\/][^\s\"'<>|]+)"
    r"|(?:/(?:Users|home|tmp|var|etc|opt)[^\s\"'<>|]*))"
)

log = logging.getLogger(__name__)

ROLES: set[str] = {"fast", "research"}


def research_needs_vram_swap(router: object) -> bool:
    """True when research is a different Ollama tag from fast."""
    same = getattr(router, "same_chat_weights", None)
    if callable(same):
        try:
            return not bool(same("fast", "research"))
        except Exception:
            return True
    model_for = getattr(router, "model_for", None)
    if not callable(model_for):
        return True
    try:
        from arelis.llm.ollama import same_ollama_model

        return not same_ollama_model(
            str(model_for("fast") or ""),
            str(model_for("research") or ""),
        )
    except Exception:
        return True


def comms_bypasses_sticky(text: str) -> bool:
    """True when this turn is SMS/email/agenda and must not keep a sticky hold."""
    raw = (text or "").strip()
    if not raw:
        return False
    from arelis.core.agenda_complete import (
        looks_like_calendar_create,
        looks_like_calendar_delete,
        looks_like_calendar_read,
    )
    from arelis.core.email_complete import looks_like_compose_email
    from arelis.core.sms_complete import parse_sms_utterance

    if parse_sms_utterance(raw) is not None:
        return True
    if looks_like_compose_email(raw):
        return True
    return (
        looks_like_calendar_create(raw)
        or looks_like_calendar_delete(raw)
        or looks_like_calendar_read(raw)
    )


# Auto-routing heuristics. Tool-shaped asks stay on fast because
# that path follows the tool schema far more reliably than a long
# research loop, which tends to narrate a call instead of emitting one.
TOOL_LOOP_HINT = re.compile(
    r"\b(search|web_search|google|scrape|fetch|open|read|list|write|edit"
    r"|analyze|workspace|web_fetch|file|email|inbox|mail|schedule"
    r"|weather|forecast|recall|remember|agenda|calendar|tasks?|todo"
    r"|git|sms|text|inbound|research(?:_report)?|doc_extract|pdf)\b|https?://",
    re.IGNORECASE,
)
FILE_LOOP_HINT = re.compile(
    r"\b(file|readme|path|workspace|edit|write|refactor|python|code|debug"
    r"|class|function|lint|git|branch|commit|diff)\b",
    re.IGNORECASE,
)
# Deep / heavy research only → 14b. Short factual "look this up" stays on fast
# (7b+tools). Bare "research" / "cite" alone no longer force a VRAM swap (H2).
RESEARCH_HINTS: list[re.Pattern[str]] = [
    re.compile(
        r"\b("
        r"deep\s*-?\s*dive|"
        r"multi\s*-?\s*source|"
        r"write\s+a\s+report|"
        r"thorough\s+research|"
        r"in\s*-?\s*depth\s+(?:research|look|analysis|report)|"
        r"investigate|"
        r"hypothesis|"
        r"derive|"
        r"astrophys|interferom|spectrum|"
        r"research\s+report|"
        r"cite\s+sources"
        r")\b",
        re.IGNORECASE,
    ),
]

# Slash commands run a tool directly, bypassing the model and the confirm card.
# That bypass is intentional and is scoped to text the user typed: naming a tool
# and its arguments explicitly is itself the confirmation.
#
# send_email and send_sms are deliberately absent. Every other tool here is
# undoable or local; a sent message is neither, and the card showing the
# recipient and body is the only gate it has. There is no version of typing it
# out that replaces reading what is about to leave the machine.
TOOL_CMD = re.compile(
    r"^/(?P<tool>web_search|web_fetch|scrape|workspace|analyze|image"
    r"|inbox|schedule)(?:\s+(?P<args>.+))?$",
    re.IGNORECASE,
)


class Orchestrator:
    """Turns inbound events into agent turns, and owns per-turn state.

    Cancellation and confirmation both have to work while a turn is mid-flight,
    which is why the turn runs as its own task rather than inline in the event
    handler: the bus can keep delivering TOOL_CONFIRM_REPLY and TURN_CANCEL
    while the agent loop is blocked awaiting one of them.
    """

    def __init__(
        self,
        bus: EventBus,
        router: ModelRouter,
        tools: ToolRegistry,
        config: dict[str, Any],
        memory: SessionMemory | None = None,
        workspace: WorkspaceRoots | None = None,
    ) -> None:
        self.bus = bus
        self.router = router
        self.tools = tools
        self.config = config
        self.workspace = workspace or config.get("_workspace") or WorkspaceRoots.from_config(config)
        self.config["_workspace"] = self.workspace
        # Explicit None: RoomStore has __len__, so `or` would replace a shared
        # store that merely happens to be empty — which is every first launch.
        # The tool and the loop would then be looking at a different object.
        shared_rooms = config.get("_rooms")
        self.rooms: RoomStore = shared_rooms if shared_rooms is not None else RoomStore()
        self.config["_rooms"] = self.rooms
        # The general thread to come back to when a room closes. Empty until a
        # room is entered from one.
        self._general_session = ""
        self.memory = memory or SessionMemory()
        self.persona = load_persona(config)
        self._cancel = False
        self._pause = False
        self._confirm_waiters: dict[str, asyncio.Future[str]] = {}
        # Live args for an open card so a spoken edit mutates what Allow runs.
        self._confirm_live: dict[str, dict[str, Any]] = {}
        self._last_ask: dict[str, Any] | None = None
        self._stopped_ask: dict[str, Any] | None = None
        self._turn_task: asyncio.Task[None] | None = None
        # The loop currently running, so a confirm card can see what this turn
        # has already done. None between turns.
        self._agent_loop: AgentLoop | None = None
        # One turn at a time. Turns share memory, the router (which unloads
        # models out from under each other) and the cancel flag, so overlapping
        # them corrupts all three. The desktop composer disables itself while
        # busy, but voice transcripts and scripts publish on the same channel.
        self._turn_lock = asyncio.Lock()
        bus.subscribe(EventType.USER_MESSAGE, self.on_user_message)
        bus.subscribe(EventType.VOICE_TRANSCRIPT, self.on_voice_transcript)
        bus.subscribe(EventType.TOOL_CONFIRM_REPLY, self.on_confirm_reply)
        bus.subscribe(EventType.TURN_CANCEL, self.on_turn_cancel)
        bus.subscribe(EventType.TURN_PAUSE, self.on_turn_pause)
        bus.subscribe(EventType.TURN_RESUME, self.on_turn_resume)
        bus.subscribe(EventType.SESSION_LOAD, self.on_session_load)
        bus.subscribe(EventType.MOBILE_SYNC, self.on_mobile_sync)

    def classify_role(
        self, text: str, explicit: ModelRole | None = None
    ) -> tuple[ModelRole, str]:
        """Pick a model role and a short reason code for telemetry.

        An explicit research chip always wins. The fast chip does not,
        because it is also the default, so there is no way to tell "the user
        chose fast" from "the user chose nothing" and auto-routing stays useful.
        File/git/debug asks stay on fast (workspace/code skills), not a third role.
        """
        if explicit == "research":
            return explicit, "chip"
        # Composer "fast" is an explicit pin — stay on conversation (H2). Mid-turn
        # escalate may still promote after failed tool rounds.
        if explicit == "fast":
            return "fast", "chip"
        # Deep research-shaped asks before tool/file loops: "write a report"
        # must not lose to the bare "write" file hint.
        for pattern in RESEARCH_HINTS:
            if pattern.search(text):
                return "research", "research_hint"
        if TOOL_LOOP_HINT.search(text):
            if FILE_LOOP_HINT.search(text):
                return "fast", "file_loop"
            return "fast", "tool_loop"
        return (explicit or self.router.default_role), "default"

    def choose_role(self, text: str, explicit: ModelRole | None = None) -> ModelRole:
        """Pick a model role for this message (see classify_role for reason)."""
        role, _reason = self.classify_role(text, explicit)
        return role

    async def on_voice_transcript(self, event: Event) -> None:
        """Turn speech into a message, unless it was only dictation.

        Dictated text is destined for the composer so the user can edit it
        before sending. Starting a turn from it would take the decision away
        from them, which is the difference between the two voice modes.

        Conversation mode (or a wake remainder, which sets the same flag):
        goodbye hangs up the call, stop cancels the turn, a card hears
        allow / deny / rest-of-ask, and any other sentence on a send card
        rewrites the draft. After a stop, the next line is a normal turn
        with a one-line note — the model decides. Headset barge-in arrives
        as a normal turn and cancels the running one first. Speakers with
        barge_in_as_turn false still send deliver ``control`` so only stop /
        allow / deny land — soup does not start a turn.
        """
        if event.payload.get("deliver") == "dictate":
            return
        text = (event.payload.get("text") or "").strip()
        if not text:
            return
        conversing = bool(self.config.get("_speak_replies"))
        if conversing and not self._confirm_waiters and classify_hangup(text):
            task = self._turn_task
            if task is not None and not task.done():
                await self.bus.publish(
                    Event(EventType.TURN_CANCEL, {"reason": "voice"})
                )
            await self.bus.publish(
                Event(EventType.CONVERSATION_END, {"reason": "voice"})
            )
            return
        if self.rooms.active_id == PHYSICS_ROOM_ID:
            act = classify_physics_act(text, names=speech_body_names())
            if act:
                payload = dict(act.payload())
                payload["text"] = text
                await self.bus.publish(Event(EventType.PHYSICS_VERB, payload))
                return
        control_only = event.payload.get("deliver") == "control"
        if not conversing and not control_only:
            await self.bus.publish(
                Event(EventType.USER_MESSAGE, {"text": text, "source": "voice"})
            )
            return
        act = classify_voice_act(text)
        if act == "stop":
            await self.bus.publish(Event(EventType.TURN_CANCEL, {"reason": "voice"}))
            return
        if self._confirm_waiters and act in {"allow", "skip", "allow_turn"}:
            confirm_id = next(iter(self._confirm_waiters), "")
            if confirm_id:
                await self.bus.publish(
                    Event(
                        EventType.TOOL_CONFIRM_REPLY,
                        {
                            "id": confirm_id,
                            "decision": "allow" if act != "skip" else "skip",
                            "allow_turn": act == "allow_turn",
                            "reason": "voice",
                        },
                    )
                )
            return
        if self._confirm_waiters and not control_only:
            if await self._apply_voice_confirm_edit(text):
                return
            return
        if control_only:
            return
        if conversing:
            task = self._turn_task
            if task is not None and not task.done():
                # Headset barge-in is the next question. Cancel this turn
                # first so the new USER_MESSAGE does not wait on the lock
                # behind an answer nobody is listening to anymore.
                await self.bus.publish(
                    Event(EventType.TURN_CANCEL, {"reason": "voice"})
                )
        await self.bus.publish(
            Event(EventType.USER_MESSAGE, {"text": text, "source": "voice"})
        )

    async def _apply_voice_confirm_edit(self, text: str) -> bool:
        """Rewrite the open send draft. True when the card was refreshed."""
        confirm_id = next(iter(self._confirm_waiters), "")
        live = self._confirm_live.get(confirm_id) if confirm_id else None
        if not live:
            return False
        args = live.get("args")
        tool = str(live.get("tool") or "")
        if not isinstance(args, dict):
            return False
        if not apply_confirm_edit(tool, args, text):
            return False
        await self._republish_confirm(confirm_id, live)
        await self.bus.publish(
            Event(EventType.THINKING, {"text": f"voice edit  {tool}"})
        )
        return True

    async def _republish_confirm(self, confirm_id: str, live: dict[str, Any]) -> None:
        tool = str(live.get("tool") or "")
        args = live.get("args") if isinstance(live.get("args"), dict) else {}
        summary = str(live.get("summary") or "")
        preview_args = {k: redact_secrets(str(v))[:200] for k, v in args.items()}
        await self.bus.publish(
            Event(
                EventType.TOOL_CONFIRM,
                {
                    "id": confirm_id,
                    "tool": tool,
                    "args": preview_args,
                    "full_args": {str(k): v for k, v in args.items()},
                    "summary": summary,
                    "headline": confirm_headline(tool, args),
                    "detail": self.tools.describe_call(tool, args),
                    "note": self._confirm_note(tool),
                    "batch_ok": tool not in NEVER_BATCH,
                    "reason": "voice_edit",
                },
            )
        )

    async def on_confirm_reply(self, event: Event) -> None:
        confirm_id = event.payload.get("id")
        decision = (event.payload.get("decision") or "skip").lower()
        if event.payload.get("allow_turn"):
            decision = "allow_turn"
        fut = self._confirm_waiters.get(str(confirm_id))
        if fut and not fut.done():
            fut.set_result(decision)

    async def on_turn_cancel(self, event: Event) -> None:
        """Stop the current turn as directly as possible.

        Three things are needed and none is sufficient alone. The flag stops the
        loop at its next cooperative check. Resolving pending confirms unblocks
        a turn parked on the confirm card, which no cancellation can reach on its
        own. Cancelling the task interrupts work already in flight: without it a
        30 second scrape or a long model read ignores stop until it returns.

        The last ask is kept so the next turn can tell the model she was
        stopped. No snapshot when nothing was running.
        """
        if self._last_ask and (
            (self._turn_task is not None and not self._turn_task.done())
            or self._confirm_waiters
        ):
            self._stopped_ask = dict(self._last_ask)
        self._cancel = True
        self._pause = False
        set_paused(False)
        for fut in list(self._confirm_waiters.values()):
            if not fut.done():
                fut.set_result("skip")
        task = self._turn_task
        if task is not None and not task.done():
            task.cancel()

    async def on_turn_pause(self, event: Event) -> None:
        """Freeze the drive. The page stays; Go unblocks the next step."""
        self._pause = True
        set_paused(True)
        await self.bus.publish(Event(EventType.THINKING, {"text": "drive paused"}))

    async def on_turn_resume(self, event: Event) -> None:
        self._pause = False
        set_paused(False)
        await self.bus.publish(Event(EventType.THINKING, {"text": "drive resumed"}))

    async def on_session_load(self, event: Event) -> None:
        """Swap the in-process working set for an archived conversation.

        Refused while a turn is running: the turn and the load both own
        SessionMemory, and letting them interleave would paint one conversation
        while the model answers in another.
        """
        task = self._turn_task
        if task is not None and not task.done():
            await self.bus.publish(
                Event(
                    EventType.SESSION_LOADED,
                    {
                        "ok": False,
                        "error": "Finish or stop the current turn first.",
                        "silent": bool(event.payload.get("silent")),
                    },
                )
            )
            return
        store = self._memory_store()
        if store is None:
            await self.bus.publish(
                Event(
                    EventType.SESSION_LOADED,
                    {
                        "ok": False,
                        "error": "Conversation archive is not available.",
                        "silent": bool(event.payload.get("silent")),
                    },
                )
            )
            return

        silent = bool(event.payload.get("silent"))
        if event.payload.get("new"):
            session_id = store.start_session()
            self.memory.hydrate([], summary="")
            await self.bus.publish(
                Event(
                    EventType.SESSION_LOADED,
                    {
                        "ok": True,
                        "session_id": session_id,
                        "messages": [],
                        "summary": "",
                        "new": True,
                        "silent": silent,
                    },
                )
            )
            return

        session_id = str(event.payload.get("session_id") or "").strip()
        if not session_id or not store.open_session(session_id):
            await self.bus.publish(
                Event(
                    EventType.SESSION_LOADED,
                    {
                        "ok": False,
                        "error": f"No conversation {session_id!r}.",
                        "silent": silent,
                    },
                )
            )
            return

        rows = store.get_messages(session_id)
        summary = store.get_summary(session_id)
        self.memory.hydrate(rows, summary=summary)
        await self.bus.publish(
            Event(
                EventType.SESSION_LOADED,
                {
                    "ok": True,
                    "session_id": session_id,
                    "messages": [
                        {
                            "role": row["role"],
                            "content": row["content"],
                            "note": row.get("note") or "",
                        }
                        for row in rows
                    ],
                    "summary": summary,
                    "silent": silent,
                },
            )
        )

    def _memory_store(self) -> MemoryStore | None:
        sink = self.memory.sink
        return sink if isinstance(sink, MemoryStore) else None

    async def on_mobile_sync(self, event: Event) -> None:
        """Fold phone talk into a session. Not a turn, and not a disclaimer."""
        rows = event.payload.get("messages") or []
        if not isinstance(rows, list) or not rows:
            return
        wanted = str(event.payload.get("session_id") or "").strip()
        store = self._memory_store()
        current = str(getattr(store, "session_id", "") or "") if store is not None else ""
        if store is not None and wanted and wanted != current:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                role = str(row.get("role") or "").strip().lower()
                text = str(row.get("text") or "").strip()
                if role in {"user", "assistant"} and text:
                    store.append_to_session(wanted, role, text)
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            role = str(row.get("role") or "").strip().lower()
            text = str(row.get("text") or "").strip()
            if role in {"user", "assistant"} and text:
                self.memory.add(role, text)

    async def on_user_message(self, event: Event) -> None:
        text = (event.payload.get("text") or "").strip()
        attachments = event.payload.get("attachments") or []
        if not isinstance(attachments, list):
            attachments = []
        if not text and not attachments:
            return
        explicit = event.payload.get("role")
        role: ModelRole | None = explicit if explicit in ROLES else None

        # Grant reads for attached source paths (UI usually does this too).
        for item in attachments:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source_path") or "").strip()
            if source:
                self.workspace.grant_external_read(source)

        # Commands answer inline. Every branch has to end in ASSISTANT_DONE or
        # ERROR: the desktop UI only clears its busy state on those two, so a
        # branch that returns after a STATUS event leaves the composer disabled
        # with no way back short of restarting the app.
        if text:
            tool_match = TOOL_CMD.match(text)
            if tool_match:
                await self._run_tool_command(
                    tool_match.group("tool"), tool_match.group("args") or ""
                )
                return

            if text.startswith("/role"):
                await self._set_role(text)
                return

            # Typo /roll must not silently route to research/14b (R14).
            if re.match(r"(?i)^/roll\b", text):
                await self.bus.publish(
                    Event(
                        EventType.ASSISTANT_DONE,
                        {
                            "text": (
                                "Unknown command `/roll`. Did you mean "
                                "`/role fast|research`? Try `/help`."
                            )
                        },
                    )
                )
                return

            if text.startswith("/project"):
                await self._set_project(text)
                return

            if re.match(r"(?i)^/rooms?\b", text):
                await self._room_command(text)
                return

            if re.match(r"(?i)^/leave\b", text):
                await self._leave_room()
                return

            if text in {"/help", "help"}:
                await self._emit_help()
                return

            # Spoken navigation, after the slash commands so a typed command
            # always wins. Typed and spoken are the same path: enter if the
            # room exists, create if it does not.
            if match_leave_intent(text):
                await self._leave_room()
                return
            if match_list_rooms_intent(text):
                await self._say(self._rooms_overview())
                return
            spoken = match_enter_intent(text) or match_make_room_intent(text)
            if spoken:
                await self._enter_or_create_room(spoken)
                return

            from arelis.core.document_refs import (
                latest_openable_path,
                match_open_last_document,
                match_reveal_last_document,
            )

            reveal = match_reveal_last_document(text)
            if reveal or match_open_last_document(text):
                path = latest_openable_path(self.memory.messages)
                if not path:
                    await self._say("There isn't a file from this conversation to open.")
                    return
                await self.bus.publish(
                    Event(
                        EventType.FILE_READY,
                        {
                            "path": path,
                            "abs_path": path,
                            "show_card": False,
                            "open": not reveal,
                            "reveal": reveal,
                        },
                    )
                )
                name = Path(path).name
                if reveal:
                    await self._say(f"Showing {name} in the folder.")
                else:
                    await self._say(f"Opening {name}.")
                return

        # Typed absolute paths outside roots need an Allow (read-only session grant).
        if text and not await self._ensure_external_path_grants(text):
            await self.bus.publish(
                Event(
                    EventType.ASSISTANT_DONE,
                    {
                        "text": (
                            "Skipped — I was not allowed to read the outside-"
                            "workspace path you named."
                        )
                    },
                )
            )
            return

        turn_text = text
        if attachments:
            block = format_attachments_block(attachments, user_text=text)
            if block:
                turn_text = f"{block}\n\n{text}" if text else block
            elif not text:
                turn_text = "Please look at the attached file(s)."
        elif text:
            # Bare "yea"/"ok" after an attachment offer: re-inject paths + tools.
            continued = continue_prior_attachment_ask(
                text, self.memory.messages
            )
            if continued is None:
                continued = continue_prior_image_describe(
                    text, self.memory.messages
                )
            if continued:
                turn_text = continued

        source = str(event.payload.get("source") or "chat")
        language = str(event.payload.get("language") or "")
        phone_speak = source == "mobile" and bool(event.payload.get("speak"))
        await self._run_turn(
            turn_text, role, source=source, language=language, phone_speak=phone_speak
        )

    async def _ensure_external_path_grants(self, text: str) -> bool:
        """Confirm + grant each absolute path outside roots. False if user skips."""
        candidates: list[Path] = []
        for match in _ABS_PATH_TOKEN.finditer(text):
            raw = match.group("path").rstrip(".,);]")
            if not raw:
                continue
            if not (_WINDOWS_DRIVE.match(raw) or raw.startswith("/")):
                continue
            try:
                path = Path(raw).expanduser().resolve()
            except OSError:
                continue
            if not path.exists():
                continue
            try:
                self.workspace.resolve(str(path))
                continue  # already inside a root
            except PermissionError:
                pass
            if self.workspace.has_external_read(path):
                continue
            if path not in candidates:
                candidates.append(path)

        for path in candidates:
            decision = await self._request_confirm(
                uuid4().hex,
                "external_read",
                {"path": str(path)},
                f"Read `{path.name}` outside the workspace (read-only)",
            )
            if decision not in {"allow", "allow_turn"}:
                return False
            self.workspace.grant_external_read(path)
        return True

    async def _run_turn(
        self,
        text: str,
        role: ModelRole | None,
        *,
        source: str = "chat",
        language: str = "",
        phone_speak: bool = False,
    ) -> None:
        async with self._turn_lock:
            self._cancel = False
            self._pause = False
            set_paused(False)
            self._last_ask = {"text": text, "role": role, "source": source}
            self.config["_phone_turn"] = source == "mobile"
            self.config["_phone_speak"] = bool(phone_speak)
            self.config["_reply_language"] = language
            stopped_ask = str((self._stopped_ask or {}).get("text") or "")
            self._stopped_ask = None
            chosen, route_reason = self.classify_role(text, role)
            # Sticky hold is for typed research follow-ups so VRAM does not
            # thrash. Conversation must return to fast on small talk — otherwise
            # a mis-heard "text file" keeps research on "how are you tonight".
            # Typed SMS/email/agenda must also leave the hold (wrong Allow args).
            if (
                role != "research"
                and not self.config.get("_speak_replies")
                and not comms_bypasses_sticky(text)
            ):
                apply_sticky = getattr(self.router, "apply_sticky", None)
                if callable(apply_sticky):
                    chosen, route_reason = apply_sticky(chosen, route_reason)
            loop = AgentLoop(
                self.bus,
                self.router,
                self.tools,
                self.memory,
                self.persona,
                self.config,
                request_confirm=self._request_confirm,
                is_cancelled=lambda: self._cancel,
                is_paused=lambda: self._pause,
            )
            self._agent_loop = loop
            task = asyncio.create_task(
                loop.run(
                    text,
                    chosen,
                    source=source,
                    route_reason=route_reason,
                    stopped_ask=stopped_ask,
                )
            )
            self._turn_task = task
            try:
                await task
            except asyncio.CancelledError:
                # Distinguish "the user pressed stop" from "this handler is
                # being torn down". Re-raising the latter keeps shutdown clean;
                # swallowing the former is what makes stop feel instant.
                if not task.cancelled():
                    raise
                # The loop normally closes itself out on the way past, keeping
                # whatever it had already written. Only speak up if it did not
                # get that far, so the turn still ends with one terminal event.
                if not loop.terminal_sent:
                    await self.bus.publish(Event(EventType.THINKING, {"text": "cancelled"}))
                    await self.bus.publish(Event(EventType.ASSISTANT_DONE, {"text": "Stopped."}))
            except Exception as exc:
                # Last line of defence. Anything unhandled here would otherwise
                # end the turn with no terminal event at all.
                #
                # It also runs at the worst moment the app has, which is why the
                # copy matters: this used to publish the exception class into the
                # message field, and the UI put that in the transcript verbatim.
                log.exception("Turn failed")
                chat, detail = turn_failed_notice(exc)
                await self.bus.publish(
                    Event(
                        EventType.ERROR,
                        {"message": chat, "detail": detail},
                    )
                )
            finally:
                self._turn_task = None
                self._agent_loop = None
                self._pause = False
                self.config["_phone_turn"] = False
                self.config["_phone_speak"] = False
                self.config["_reply_language"] = ""
                set_paused(False)

    async def _set_role(self, text: str) -> None:
        parts = text.split(maxsplit=1)
        wanted = parts[1].strip().lower() if len(parts) > 1 else ""
        if wanted in ROLES:
            self.router.default_role = wanted  # type: ignore[assignment]
            if wanted == "fast":
                # Operator escape hatch from H6 sticky hold.
                self.router.clear_sticky()
            elif wanted == "research" and research_needs_vram_swap(self.router):
                # Flip the chip first, then evict conversation so the next
                # research stream does not share a 12GB card with a 30m pin.
                from arelis.llm.vram import free_gpu_neighbors

                await free_gpu_neighbors(self.config, self.bus)
                prepare = getattr(self.router, "prepare_heavy_role", None)
                if callable(prepare):
                    await self.bus.publish(
                        Event(
                            EventType.STATUS,
                            {
                                "message": (
                                    f"Unloading conversation model so `{wanted}` "
                                    "can fit on the GPU…"
                                )
                            },
                        )
                    )
                    try:
                        await prepare(wanted)
                    except Exception as exc:
                        message = (
                            f"Role set to `{wanted}`, but the previous model is "
                            f"still in VRAM: {exc}"
                        )
                        await self.bus.publish(
                            Event(EventType.STATUS, {"message": message})
                        )
                        await self.bus.publish(
                            Event(EventType.ASSISTANT_DONE, {"text": message})
                        )
                        return
            message = f"Role set to `{wanted}`. New messages use it unless you pick another chip."
        else:
            message = f"Unknown role `{wanted}`. Choose one of: fast, research."
        await self.bus.publish(Event(EventType.STATUS, {"message": message}))
        await self.bus.publish(Event(EventType.ASSISTANT_DONE, {"text": message}))

    async def _set_project(self, text: str) -> None:
        """List or switch the active project. Session memory is kept."""
        parts = text.split(maxsplit=1)
        wanted = parts[1].strip() if len(parts) > 1 else ""
        names = self.workspace.names()
        if not wanted:
            lines = [
                (
                    f"- `{name}`"
                    + (" (active)" if name == self.workspace.active else "")
                )
                for name in names
            ]
            message = "Projects:\n" + "\n".join(lines)
            message += "\n\nSwitch with `/project <name>`. Paths: `name:relative/path`."
        else:
            try:
                self.workspace.set_active(wanted)
                message = (
                    f"Active project set to `{wanted}`. "
                    "Session memory is kept; qualify paths when referring to other projects."
                )
            except ValueError as exc:
                message = str(exc)
        await self.bus.publish(Event(EventType.STATUS, {"message": message}))
        await self.bus.publish(Event(EventType.ASSISTANT_DONE, {"text": message}))

    # -- rooms ---------------------------------------------------------------

    async def _room_command(self, text: str) -> None:
        """`/room`, `/rooms`, and the four things you can do to one."""
        parts = text.split(maxsplit=2)
        verb = parts[1].strip().lower() if len(parts) > 1 else ""
        rest = parts[2].strip() if len(parts) > 2 else ""

        if not verb:
            await self._say(self._rooms_overview())
            return
        if verb == "new":
            await self._enter_or_create_room(rest)
            return
        if verb == "set":
            message = self._set_room_field(rest)
            # Repaint before answering. The strip shows the purpose and the
            # folder, so changing either without republishing leaves the banner
            # describing a room that no longer exists in that form — and the
            # banner is the only place either one is visible.
            room = self.rooms.active
            if room is not None:
                await self._publish_room_only(room)
            await self._say(message)
            return
        if verb == "forget":
            await self._say(self._forget_room(rest))
            return
        if verb in {"leave", "general"}:
            await self._leave_room()
            return

        wanted = f"{verb} {rest}".strip()
        await self._enter_or_create_room(wanted)

    def _rooms_overview(self) -> str:
        rooms = self.rooms.all()
        if not rooms:
            return (
                "No rooms yet. A room is a named place to work on one thing — it "
                "keeps its own conversation, points at one project folder, and "
                "remembers what it is for.\n\n"
                "Make one with `/room new <name>`, then `/room set purpose <what "
                "it is for>` and `/room set root <project>`."
            )
        active = self.rooms.active_id
        lines = []
        for room in rooms:
            mark = " (open)" if room.id == active else ""
            detail = room.purpose or room.spec.blurb
            where = f" · `{room.root}`" if room.root else ""
            if room.name and room.name.lower() != room.id:
                ident = f"{room.name} (`{room.id}`)"
            else:
                ident = f"`{room.id}`"
            lines.append(f"- {ident}{mark} — {detail}{where}")
        body = "Rooms:\n" + "\n".join(lines)
        if active:
            body += "\n\nLeave with `/leave`."
        else:
            body += "\n\nEnter one with `/room <name>`."
        return body

    async def _enter_or_create_room(self, wanted: str) -> None:
        """`/room physics` and \"let's work on Reality\" are the same room.

        Find the room. Walk in. If there isn't one and the name is a room
        name, make it and walk in. Already inside: say so, do not start a turn.
        Earth is a zone inside Reality, not a room to create.
        """
        from arelis.rooms import PHYSICS_ALIASES

        name = normalize_room_name(wanted)
        if not name:
            await self._say(
                "Name it: `/room physics`, or say \"let's work on Reality\"."
            )
            return
        folded = name.lower()
        if folded == "earth":
            await self._say(
                "Earth is a zone inside Reality, not a room. "
                "Say \"let's work on Reality\", then enter Earth."
            )
            return
        room = self.rooms.find(name)
        created = False
        if room is None:
            if folded in PHYSICS_ALIASES:
                room = self.rooms.get(PHYSICS_ROOM_ID)
            if room is None and not looks_like_room_name(name):
                await self._say(
                    f"No room called `{name}`. "
                    f"Make one with `/room new {name}`, or `/rooms` to see what exists."
                )
                return
            if room is None:
                display = name if any(ch.isupper() for ch in name) else name.title()
                try:
                    room = self.rooms.create(display)
                except ValueError as exc:
                    await self._say(str(exc))
                    return
                created = True
        if room is None:
            await self._say(f"No room called `{name}`.")
            return
        if room.id == self.rooms.active_id:
            await self._offer_reality_plate(room)
            await self._say(f"Already in {room.name}.")
            return
        preamble = ""
        if created:
            preamble = (
                f"Made the `{room.id}` room and opened it. Tell me what it is for "
                f"with `/room set purpose …`, and point it at a folder with "
                f"`/room set root <project>` — `/project` lists them."
            )
        await self._enter_room(room, preamble=preamble)
        await self._offer_reality_plate(room)

    async def _offer_reality_plate(self, room: Room) -> None:
        """Open Reality's plate when the stage is granted. One room, one thread."""
        if room.id != PHYSICS_ROOM_ID:
            return
        await self.bus.publish(
            Event(
                EventType.PHYSICS_VERB,
                {"verb": "lab", "on": True, "text": "open Reality"},
            )
        )

    def _set_room_field(self, rest: str) -> str:
        room = self.rooms.active
        if room is None:
            return "No room is open. `/room <name>` first, or `/rooms` to see them."
        parts = rest.split(maxsplit=1)
        field = parts[0].strip().lower() if parts else ""
        value = parts[1].strip() if len(parts) > 1 else ""
        if field not in {"purpose", "root", "kind", "name"}:
            return (
                "Set `purpose`, `root`, `kind` or `name`. "
                "For example: `/room set purpose analysing the survey data`."
            )
        if not value:
            return f"Give it a value: `/room set {field} …`."
        if field == "root" and value not in self.workspace.names():
            return (
                f"No project called `{value}`. Existing: "
                + ", ".join(f"`{n}`" for n in self.workspace.names())
                + ". Add a folder in the workspace dock first."
            )
        try:
            updated = self.rooms.update(room.id, **{field: value})
        except ValueError as exc:
            return str(exc)
        if field == "root":
            self._point_workspace_at(updated)
        if field == "kind" and updated.role is not None:
            # Entering a room applies its lean, so setting the kind from inside
            # one would otherwise do nothing until you left and came back —
            # which reads as the command having been ignored.
            self.router.default_role = updated.role  # type: ignore[assignment]
        return f"`{updated.id}`: {field} set to {value}."

    def _forget_room(self, rest: str) -> str:
        wanted = rest.strip()
        room = self.rooms.find(wanted) if wanted else self.rooms.active
        if room is None:
            return f"No room called `{wanted}`." if wanted else "No room is open."
        try:
            self.rooms.remove(room.id)
        except ValueError as exc:
            return str(exc)
        return (
            f"Forgot the `{room.id}` room. Its conversations are still in History "
            "— only the room itself is gone."
        )

    def _point_workspace_at(self, room: Room) -> str:
        """Make the room's folder active. Returns a note if it could not be."""
        if not room.root:
            return ""
        try:
            self.workspace.set_active(room.root)
        except ValueError:
            return (
                f" Its folder `{room.root}` is not a project any more, so paths "
                "still resolve against "
                f"`{self.workspace.active}`."
            )
        return ""

    async def resume_last_room(self) -> bool:
        """Open the room this process last left in, if it still exists.

        Does not create a room. Orbit if they left, or if the room was forgotten.
        Silent: the strip and the thread are the proof, not a launch speech.
        """
        wanted = self.rooms.last_active_id
        room = self.rooms.get(wanted) if wanted else None
        if room is None:
            return False
        await self._enter_room(room, silent=True)
        return True

    async def _enter_room(self, room: Room, *, preamble: str = "", silent: bool = False) -> None:
        """Open a room: its thread, its folder, its role — all three at once.

        Refused mid-turn for the same reason a session load is: the running turn
        owns SessionMemory, and swapping the thread underneath it would answer
        one conversation into another.
        """
        task = self._turn_task
        if task is not None and not task.done():
            await self._say("Finish or stop the current turn first.")
            return
        store = self._memory_store()
        if store is None:
            await self._say("Rooms need the conversation archive, which is not available.")
            return

        if self.rooms.active is None and store.session_id:
            self._general_session = store.session_id

        session_id = store.latest_session_id(room_id=room.id, require_messages=False)
        if session_id is None or not store.open_session(session_id):
            session_id = store.start_session(room_id=room.id)
            rows: list[dict[str, Any]] = []
            summary = ""
        else:
            rows = store.get_messages(session_id)
            summary = store.get_summary(session_id)
        self.memory.hydrate(rows, summary=summary)
        self.rooms.set_active(room.id)

        note = self._point_workspace_at(room)
        if room.role is not None:
            self.router.default_role = room.role  # type: ignore[assignment]

        await self._publish_room(room, session_id, rows, summary)
        if silent:
            return
        opened = "Picking up where we left off." if rows else "New thread."
        lines = [preamble] if preamble else [f"In {room.name}. {opened}"]
        if room.purpose:
            lines.append(room.purpose)
        where = []
        if room.root:
            where.append(f"working in `{room.root}`")
        if room.role:
            where.append(f"`{room.role}` model")
        if where:
            # Only the first letter. str.capitalize() lowercases the rest, which
            # turned the project `Arelis Source` into `arelis source` in the one
            # line whose job is telling you which folder she is about to write to.
            sentence = " · ".join(where)
            lines.append(sentence[0].upper() + sentence[1:] + ".")
        if note:
            lines.append(note.strip())
        await self._say("\n\n".join(part for part in lines if part))

    async def _leave_room(self) -> None:
        """Back to the general conversation, and the thread it was on."""
        room = self.rooms.active
        if room is None:
            await self._say("No room is open.")
            return
        task = self._turn_task
        if task is not None and not task.done():
            await self._say("Finish or stop the current turn first.")
            return
        store = self._memory_store()
        if store is None:
            await self._say("Rooms need the conversation archive, which is not available.")
            return

        self.rooms.leave()
        rows: list[dict[str, Any]] = []
        summary = ""
        target = self._general_session or store.latest_session_id(
            room_id="", require_messages=True
        )
        if target and store.open_session(target):
            rows = store.get_messages(target)
            summary = store.get_summary(target)
        else:
            target = store.start_session()
        self.memory.hydrate(rows, summary=summary)
        self._general_session = ""

        await self._publish_room(None, target, rows, summary)
        await self._say(f"Out of {room.name}. Back to the general conversation.")

    async def _publish_room_only(self, room: Room) -> None:
        """The room's details changed, but the thread did not.

        Separate from _publish_room because that one is followed by
        SESSION_LOADED, and repainting the transcript after `/room set purpose`
        would scroll the conversation to the top for a one-word edit.
        """
        await self.bus.publish(
            Event(
                EventType.ROOM_CHANGED,
                {
                    "room_id": room.id,
                    "name": room.name,
                    "purpose": room.purpose,
                    "root": room.root,
                    "kind": room.kind,
                    "session_id": self._memory_store().session_id
                    if self._memory_store() is not None
                    else "",
                },
            )
        )

    async def _publish_room(
        self,
        room: Room | None,
        session_id: str,
        rows: list[dict[str, Any]],
        summary: str,
    ) -> None:
        """Tell the surfaces the thread moved, then hand them the messages.

        Order matters: ROOM_CHANGED first so the chat knows which room it is
        painting before the transcript lands in it.
        """
        await self.bus.publish(
            Event(
                EventType.ROOM_CHANGED,
                {
                    "room_id": room.id if room else "",
                    "name": room.name if room else "",
                    "purpose": room.purpose if room else "",
                    "root": room.root if room else "",
                    "kind": room.kind if room else "",
                    "session_id": session_id,
                },
            )
        )
        await self.bus.publish(
            Event(
                EventType.SESSION_LOADED,
                {
                    "ok": True,
                    "session_id": session_id,
                    "messages": [
                        {
                            "role": row["role"],
                            "content": row["content"],
                            "note": row.get("note") or "",
                        }
                        for row in rows
                    ],
                    "summary": summary,
                    "room_id": room.id if room else "",
                },
            )
        )

    async def _say(self, message: str) -> None:
        """A command's whole reply. Both events, because the UI needs both.

        STATUS paints the line and ASSISTANT_DONE releases the composer; a
        branch that publishes only the first leaves the box disabled.

        Conversation mode speaks the same line. Slash-command dumps
        (``_emit_help``, fenced tool output) stay on their own publishers
        so a wall of ``/help`` is not read aloud.
        """
        await self.bus.publish(Event(EventType.STATUS, {"message": message}))
        will_speak = bool(self.config.get("_speak_replies")) and bool(
            (message or "").strip()
        )
        await self.bus.publish(
            Event(EventType.ASSISTANT_DONE, {"text": message, "speak": will_speak})
        )
        if will_speak:
            await self.bus.publish(Event(EventType.VOICE_SPEAK, {"text": message}))

    async def _request_confirm(
        self, confirm_id: str, tool: str, args: dict[str, Any], summary: str
    ) -> str:
        """Ask the UI to approve a call and wait for the answer.

        The future is registered before the event is published so a reply that
        arrives immediately, as it does in the CLI and in the e2e probes, cannot
        land before there is anything to resolve.
        """
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[str] = loop.create_future()
        self._confirm_waiters[confirm_id] = fut
        self._confirm_live[confirm_id] = {
            "tool": tool,
            "args": args,
            "summary": summary,
        }
        preview_args = {k: redact_secrets(str(v))[:200] for k, v in args.items()}
        await self.bus.publish(
            Event(
                EventType.TOOL_CONFIRM,
                {
                    "id": confirm_id,
                    "tool": tool,
                    "args": preview_args,
                    # Parked/restarted Allow must send these, not the 200-char
                    # preview. Live turns still execute in-memory full args.
                    "full_args": {str(k): v for k, v in args.items()},
                    "summary": summary,
                    "headline": confirm_headline(tool, args),
                    # Full rendering for the card. summary stays as it was, for
                    # the thinking dock and the CLI, which want one line.
                    "detail": self.tools.describe_call(tool, args),
                    "note": self._confirm_note(tool),
                    "batch_ok": tool not in NEVER_BATCH,
                },
            )
        )
        agent_cfg = self.config.get("agent") or {}
        timeout_s = float(agent_cfg.get("confirm_timeout_s", 300) or 0)
        try:
            if timeout_s > 0:
                # asyncio.wait (not wait_for): do not cancel the Future on timeout.
                done, _pending = await asyncio.wait({fut}, timeout=timeout_s)
                if fut in done:
                    return fut.result()
                # L10: don't leave wall-clock looking like a hung model forever.
                if not fut.done():
                    fut.set_result("skip")
                mins = max(1, int(timeout_s // 60))
                await self.bus.publish(
                    Event(
                        EventType.STATUS,
                        {
                            "message": (
                                f"Confirm timed out after {mins}m — skipped `{tool}`."
                            )
                        },
                    )
                )
                await self.bus.publish(
                    Event(
                        EventType.THINKING,
                        {
                            "text": (
                                f"phase=confirm timeout_skip tool={tool} "
                                f"after_s={int(timeout_s)}"
                            )
                        },
                    )
                )
                await self.bus.publish(
                    Event(
                        EventType.TOOL_CONFIRM_REPLY,
                        {
                            "id": confirm_id,
                            "decision": "skip",
                            "allow_turn": False,
                            "reason": "timeout",
                        },
                    )
                )
                return "skip"
            return await fut
        finally:
            self._confirm_waiters.pop(confirm_id, None)
            self._confirm_live.pop(confirm_id, None)

    def _confirm_note(self, tool: str) -> str:
        """A warning to put on the card, when this particular call deserves one.

        Read straight off the running loop rather than off the bus. This is
        called from inside the agent loop's own coroutine, so the set is exactly
        up to date; a TOOL_RESULT subscriber would race with it.
        """
        used = set()
        loop = self._agent_loop
        if loop is not None:
            used = set(loop.tools_used)
        return confirm_note_after_external(tool, used)

    async def _emit_help(self) -> None:
        tools = ", ".join(t["name"] for t in self.tools.list()) or "(none)"
        msg = (
            "Just talk. Arelis can use tools from natural language "
            "(reads and web run on their own; writes and images ask first).\n\n"
            "Power-user slash commands:\n"
            "  /role fast|research\n"
            "  /project [name]\n"
            "  /rooms                       list rooms\n"
            "  /room <name>                 open one (or say \"let's work on <name>\")\n"
            "  /room new <name>             make one\n"
            "  /room set purpose|root|kind|name <value>\n"
            "  /room forget <name>          drop the room, keep its conversations\n"
            "  /leave                       back to the general conversation\n"
            "  /web_search query=...\n"
            "  /web_fetch url=...\n"
            "  /scrape url=...\n"
            "  /workspace action=list|read|write|edit path=...\n"
            "  /analyze path=... action=summary|head|describe\n"
            "  /image prompt=...\n"
            "Slash commands run the tool directly and skip the confirm card.\n"
            "With multiple projects, paths may be `name:relative/path`.\n"
            f"Tools: {tools}"
        )
        await self.bus.publish(Event(EventType.ASSISTANT_DONE, {"text": msg}))

    async def _run_tool_command(self, tool: str, args: str) -> None:
        kwargs = self._parse_args(args)
        await self.bus.publish(Event(EventType.TOOL_START, {"tool": tool, "args": kwargs}))
        await self.bus.publish(
            Event(EventType.THINKING, {"text": f"slash  Running tool `{tool}`"})
        )
        result = await self.tools.call(tool, **kwargs)
        await self.bus.publish(
            Event(
                EventType.TOOL_RESULT,
                {"tool": tool, "ok": result.ok, "output": result.output, "data": result.data},
            )
        )
        if tool == "image" and result.ok and result.data.get("path"):
            await self.bus.publish(Event(EventType.IMAGE_READY, {"path": result.data["path"]}))
        if tool in {"document", "plot"} and result.ok and result.data.get("abs_path"):
            await self.bus.publish(
                Event(
                    EventType.FILE_READY,
                    {
                        "path": str(result.data.get("path") or ""),
                        "abs_path": str(result.data.get("abs_path") or ""),
                        "format": str(result.data.get("format") or ""),
                        "title": str(result.data.get("title") or ""),
                        "show_card": True,
                        "open": False,
                    },
                )
            )
        prefix = "OK" if result.ok else "Failed"
        # Tool output is data, not prose, so it is fenced. The chat renders
        # markdown now, and an unfenced Python file would come out with *args
        # italicised and its indentation collapsed.
        summary = f"{prefix} `{tool}`\n\n{_as_code_block(redact_secrets(result.output))}"
        # Slash commands skip the agent loop, so the trace note has to be built
        # here too. Without it a "/workspace action=write" followed by "now add
        # a heading to it" has nothing to resolve "it" against.
        resolved = None
        if isinstance(result.data, dict):
            resolved = result.data.get("abs_path") or result.data.get("path")
        self.memory.add(
            "assistant",
            summary,
            note=tool_trace_note(
                [tool_trace_entry(tool, kwargs, result.ok, resolved_path=resolved)]
            ),
        )
        await self.bus.publish(Event(EventType.ASSISTANT_DONE, {"text": summary}))

    def _parse_args(self, args: str) -> dict[str, Any]:
        """Parse slash-command arguments.

        Three accepted forms, in priority order: a JSON object (used by the
        workspace panel's save button, since file content cannot survive shell
        splitting), key=value pairs, and a bare URL or bare prompt text.
        """
        if not args.strip():
            return {}
        if args.strip().startswith("{"):
            try:
                data = json.loads(args)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass
        out: dict[str, Any] = {}
        for token in _tokenize(args):
            if "=" in token:
                k, v = token.split("=", 1)
                out[k] = v
            elif "url" not in out and token.startswith("http"):
                out["url"] = token
        if not out:
            bare = args.strip()
            # "/image prompt a spiral galaxy" is a natural thing to type, and
            # without this the word "prompt" ends up inside the prompt itself.
            if bare.lower().startswith("prompt "):
                bare = bare[len("prompt ") :].strip()
            if bare:
                out["prompt"] = bare
        return out


def _as_code_block(text: str) -> str:
    """Fence text so it renders verbatim.

    The fence is one backtick longer than the longest run already in the text,
    which is what keeps a markdown file that contains its own fences from
    closing this one early and spilling the rest into the chat as prose.
    """
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def _tokenize(args: str) -> list[str]:
    """Split slash-command arguments the way a Windows user would expect.

    Plain shlex.split gets two things wrong here, both silently:

    - POSIX escape rules make a backslash escape the next character, so
      path=C:\\Users\\you\\notes.txt arrives as path=C:Usersyounotes.txt and
      the user is told a file that plainly exists cannot be found.
    - '#' starts a comment, so url=https://host/page#section loses its fragment.

    posix=False fixes the backslashes but stops honouring quotes that begin
    mid-token, which breaks path="C:\\Program Files\\x". So the lexer is
    configured directly: POSIX quoting, no escape character, no comments.
    """
    try:
        lexer = shlex.shlex(args, posix=True)
        lexer.whitespace_split = True
        lexer.escape = ""
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        # Unbalanced quotes. Whitespace splitting still recovers most of it.
        tokens = [_unquote(token) for token in args.split()]
    return tokens


def _unquote(token: str) -> str:
    if "=" in token:
        key, value = token.split("=", 1)
        return f"{key}={_strip_quotes(value)}"
    return _strip_quotes(token)


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
