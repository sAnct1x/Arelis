"""User message, session load, and turn start. Voice stays on Orchestrator."""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from uuid import uuid4

from arelis.attachments import (
    continue_prior_attachment_ask,
    continue_prior_image_describe,
    format_attachments_block,
)
from arelis.browser.hold import set_paused
from arelis.core.agent_loop import AgentLoop
from arelis.core.events import Event, EventType
from arelis.core.failure_copy import turn_failed_notice
from arelis.desk import match_keep_last, match_keep_note, write_note
from arelis.llm.router import ModelRole
from arelis.rooms import (
    match_enter_intent,
    match_leave_intent,
    match_list_rooms_intent,
    match_make_room_intent,
    match_set_kind_intent,
    match_set_root_intent,
)
from arelis.workspace import _WINDOWS_DRIVE

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


class OrchestratorTurns:
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

            if await self._keep_from_speech(text):
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
            # "work in notes" is also an enter phrasing. If a room is already
            # open and the words name a project, that is the folder, not a
            # new room.
            if self.rooms.active is not None:
                pointed = match_set_root_intent(text, self.workspace.names())
                if pointed:
                    await self._apply_room_fields({"root": pointed}, user_text=text)
                    if (
                        self._room_setup is not None
                        and self._room_setup.step == "root"
                    ):
                        await self._advance_room_setup()
                    return
                lean = match_set_kind_intent(text)
                if lean:
                    await self._apply_room_fields({"kind": lean}, user_text=text)
                    return
            spoken = match_enter_intent(text) or match_make_room_intent(text)
            if spoken:
                await self._enter_or_create_room(spoken)
                return
            if await self._handle_room_talk(text):
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

    async def _keep_from_speech(self, text: str) -> bool:
        """Handle /keep, 'keep this: …', and a bare 'pin that'. True if consumed."""
        body = match_keep_note(text)
        if body:
            room = self.rooms.active
            room_id = room.id if room is not None else ""
            try:
                item = write_note(
                    self.workspace, body, room_id=room_id, store=self.desk
                )
            except Exception as exc:
                await self._say(f"I could not keep that. {exc}")
                return True
            await self.bus.publish(
                Event(
                    EventType.FILE_READY,
                    {
                        "path": item.abs_path,
                        "abs_path": item.abs_path,
                        "title": item.label,
                        "format": "md",
                        "kind": "note",
                        "show_card": True,
                        "open": False,
                    },
                )
            )
            self.memory.add(
                "assistant",
                f"On the desk: {item.label}",
                note=f"[tools used this turn: workspace {item.abs_path}]",
            )
            await self._say(f"On the desk: {item.label}")
            return True
        if not match_keep_last(text):
            return False
        from arelis.core.document_refs import latest_openable_path

        path = latest_openable_path(self.memory.messages)
        if not path:
            items = self.desk.list_for(
                root_name=self.workspace.active,
                include_orbit=True,
            )
            path = items[0].abs_path if items else ""
        if not path:
            await self._say(
                "There isn't a file to pin. Say keep this: and what to write down."
            )
            return True
        room = self.rooms.active
        root_name = ""
        try:
            hit = self.workspace.resolve_read(path)
            root_name = hit.root_name
            path = str(hit.path)
        except Exception:
            pass
        item = self.desk.record(
            path,
            source="pin",
            root_name=root_name,
            room_id=room.id if room is not None else "",
            pin=True,
        )
        name = (item.label if item else Path(path).name) or "that file"
        await self.bus.publish(
            Event(
                EventType.FILE_READY,
                {
                    "path": path,
                    "abs_path": path,
                    "title": name,
                    "show_card": True,
                    "open": False,
                    "kind": item.kind if item else "",
                },
            )
        )
        await self._say(f"Pinned on the desk: {name}")
        return True

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
