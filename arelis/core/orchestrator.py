from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from arelis.browser.hold import set_paused
from arelis.config import load_persona
from arelis.core.agent_loop import AgentLoop
from arelis.core.bus import EventBus
from arelis.core.confirm_speech import (
    apply_confirm_edit,
    classify_drive_act,
    classify_hangup,
    classify_voice_act,
)
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator_confirm import OrchestratorConfirm
from arelis.core.orchestrator_rooms import (
    advance_room_setup,
    apply_room_fields,
    begin_room_setup,
    enter_or_create_room,
    enter_room,
    field_ack,
    finish_room_setup,
    forget_room,
    handle_room_talk,
    leave_room,
    offer_reality_plate,
    point_workspace_at,
    publish_room,
    publish_room_only,
    room_command,
    rooms_overview,
    set_room_field,
    setup_closing,
    take_setup_answer,
)
from arelis.core.orchestrator_rooms import (
    resume_last_room as resume_last_room_impl,
)
from arelis.core.orchestrator_slash import (  # noqa: F401
    OrchestratorSlash,
    _as_code_block,
    _tokenize,
)
from arelis.core.orchestrator_turns import OrchestratorTurns
from arelis.core.route_hints import (
    FILE_LOOP_HINT,
    RESEARCH_HINTS,
    TOOL_LOOP_HINT,
)
from arelis.desk import DeskStore
from arelis.llm.router import ModelRole, ModelRouter
from arelis.memory.store import MemoryStore
from arelis.rooms import (
    Room,
    RoomSetup,
    RoomStore,
)
from arelis.spatial import PHYSICS_ROOM_ID
from arelis.spatial.verbs import classify_physics_act, speech_body_names
from arelis.tools.base import NEVER_BATCH, ToolRegistry
from arelis.tools.confirm_copy import confirm_headline
from arelis.tools.safety import redact_secrets
from arelis.workspace import WorkspaceRoots

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


class Orchestrator(OrchestratorTurns, OrchestratorSlash, OrchestratorConfirm):
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
        shared_desk = config.get("_desk")
        self.desk: DeskStore = shared_desk if isinstance(shared_desk, DeskStore) else DeskStore()
        self.config["_desk"] = self.desk
        # Explicit None: RoomStore has __len__, so `or` would replace a shared
        # store that merely happens to be empty — which is every first launch.
        # The tool and the loop would then be looking at a different object.
        shared_rooms = config.get("_rooms")
        self.rooms: RoomStore = shared_rooms if shared_rooms is not None else RoomStore()
        self.config["_rooms"] = self.rooms
        # The general thread to come back to when a room closes. Empty until a
        # room is entered from one.
        self._general_session = ""
        # First-entry room interview. In-process; answers are ordinary
        # USER_MESSAGE lines (typed or spoken). Not a model turn.
        self._room_setup: RoomSetup | None = None
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
        # Fast is the default chip, not a pin. "deeply research" must still
        # route — there is no way to tell "they chose fast" from "nothing".
        # Deep research-shaped asks before tool/file loops: "write a report"
        # must not lose to the bare "write" file hint.
        for pattern in RESEARCH_HINTS:
            if pattern.search(text):
                return "research", "research_hint"
        if explicit == "fast":
            return "fast", "chip"
        if TOOL_LOOP_HINT.search(text):
            if FILE_LOOP_HINT.search(text):
                return "fast", "file_loop"
            return "fast", "tool_loop"
        return (explicit or self.router.default_role), "default"

    async def on_voice_transcript(self, event: Event) -> None:
        """Turn speech into a message, unless it was only dictation.

        Dictated text is destined for the composer so the user can edit it
        before sending. Starting a turn from it would take the decision away
        from them, which is the difference between the two voice modes.

        Conversation mode (or a wake remainder, which sets the same flag):
        goodbye hangs up the call, stop cancels the turn, a card hears
        allow / deny / rest-of-ask, and any other sentence on a send card
        rewrites the draft. Stop / allow / deny / pause / go also land
        while she is mid-turn or a card is armed — conversation does not
        have to be latched (filament one-shot yes, dictate while she
        drives). After a stop, the next line is a normal turn with a
        one-line note — the model decides. Headset barge-in arrives as a
        normal turn and cancels the running one first. Speakers with
        barge_in_as_turn false still send deliver ``control`` so only stop /
        allow / deny / pause / go land — soup does not start a turn.
        """
        text = (event.payload.get("text") or "").strip()
        if not text:
            return
        deliver = str(event.payload.get("deliver") or "")
        control_only = deliver == "control"
        conversing = bool(self.config.get("_speak_replies"))
        if await self._voice_control(text, deliver=deliver):
            return
        if deliver == "dictate":
            return
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
        act = classify_physics_act(text, names=speech_body_names())
        if act and (
            self.rooms.active_id == PHYSICS_ROOM_ID or act.verb == "goto_earth"
        ):
            payload = dict(act.payload())
            payload["text"] = text
            await self.bus.publish(Event(EventType.PHYSICS_VERB, payload))
            return
        if not conversing and not control_only:
            await self.bus.publish(
                Event(EventType.USER_MESSAGE, {"text": text, "source": "voice"})
            )
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

    def _turn_live(self) -> bool:
        task = self._turn_task
        return task is not None and not task.done()

    def _drive_held(self) -> bool:
        from arelis.browser.hold import is_paused

        return bool(self._pause or is_paused())

    async def _voice_control(self, text: str, *, deliver: str) -> bool:
        """Stop / allow / deny / pause / go from any listen path. True = handled."""
        from arelis.browser.hold import is_paused

        conversing = bool(self.config.get("_speak_replies"))
        control_only = deliver == "control"
        act = classify_voice_act(text)
        drive = classify_drive_act(text)
        waiting = bool(self._confirm_waiters)
        live = self._turn_live()
        held = bool(self._pause or is_paused())
        in_physics = self.rooms.active_id == PHYSICS_ROOM_ID

        if act == "stop":
            if live or waiting or held or conversing or control_only:
                await self.bus.publish(
                    Event(EventType.TURN_CANCEL, {"reason": "voice"})
                )
                return True
            return False

        if waiting and act in {"allow", "skip", "allow_turn"}:
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
            return True

        if waiting and conversing and deliver not in {"control", "dictate"}:
            if await self._apply_voice_confirm_edit(text):
                return True
            return True

        if drive == "pause" and (held or (live and not in_physics)):
            await self.bus.publish(Event(EventType.TURN_PAUSE, {}))
            return True
        if held and (drive == "resume" or act == "allow"):
            await self.bus.publish(Event(EventType.TURN_RESUME, {}))
            return True

        return False

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


    def _memory_store(self) -> MemoryStore | None:
        sink = self.memory.sink
        return sink if isinstance(sink, MemoryStore) else None








    # -- rooms ---------------------------------------------------------------

    async def _room_command(self, text: str) -> None:
        return await room_command(self, text)

    def _rooms_overview(self) -> str:
        return rooms_overview(self)

    async def _enter_or_create_room(self, wanted: str) -> None:
        return await enter_or_create_room(self, wanted)

    async def _offer_reality_plate(self, room: Room) -> None:
        return await offer_reality_plate(self, room)

    async def _handle_room_talk(self, text: str) -> bool:
        return await handle_room_talk(self, text)

    async def _begin_room_setup(self, room: Room, *, restart: bool = False) -> None:
        return await begin_room_setup(self, room, restart=restart)

    async def _take_setup_answer(self, text: str) -> bool:
        return await take_setup_answer(self, text)

    async def _advance_room_setup(self, *, user_text: str = "") -> None:
        return await advance_room_setup(self, user_text=user_text)

    async def _finish_room_setup(
        self, *, skipped: bool, user_text: str = ""
    ) -> None:
        return await finish_room_setup(self, skipped=skipped, user_text=user_text)

    def _setup_closing(self, room: Room, skipped: bool) -> str:
        return setup_closing(self, room, skipped)

    async def _apply_room_fields(
        self,
        fields: dict[str, Any],
        *,
        user_text: str = "",
        quiet: bool = False,
        closing: str = "",
    ) -> None:
        return await apply_room_fields(
            self, fields, user_text=user_text, quiet=quiet, closing=closing
        )

    def _field_ack(self, room: Room, fields: dict[str, Any]) -> str:
        return field_ack(self, room, fields)

    def _set_room_field(self, rest: str) -> str:
        return set_room_field(self, rest)

    def _forget_room(self, rest: str) -> str:
        return forget_room(self, rest)

    def _point_workspace_at(self, room: Room) -> str:
        return point_workspace_at(self, room)

    async def resume_last_room(self) -> bool:
        return await resume_last_room_impl(self)

    async def _enter_room(self, room: Room, *, preamble: str = "", silent: bool = False) -> None:
        return await enter_room(self, room, preamble=preamble, silent=silent)

    async def _leave_room(self) -> None:
        return await leave_room(self)

    async def _publish_room_only(self, room: Room) -> None:
        return await publish_room_only(self, room)

    async def _publish_room(
        self,
        room: Room | None,
        session_id: str,
        rows: list[dict[str, Any]],
        summary: str,
    ) -> None:
        return await publish_room(self, room, session_id, rows, summary)

    async def _say(self, message: str, *, status: bool = True) -> None:
        """A command's whole reply. Both events, because the UI needs both.

        STATUS paints the line and ASSISTANT_DONE releases the composer; a
        branch that publishes only the first leaves the box disabled.
        Setup questions stay off STATUS — that line is the thinking-dock
        footer, not her voice.

        Conversation mode speaks the same line. Slash-command dumps
        (``_emit_help``, fenced tool output) stay on their own publishers
        so a wall of ``/help`` is not read aloud.
        """
        if status:
            await self.bus.publish(Event(EventType.STATUS, {"message": message}))
        will_speak = bool(self.config.get("_speak_replies")) and bool(
            (message or "").strip()
        )
        await self.bus.publish(
            Event(EventType.ASSISTANT_DONE, {"text": message, "speak": will_speak})
        )
        if will_speak:
            await self.bus.publish(Event(EventType.VOICE_SPEAK, {"text": message}))













