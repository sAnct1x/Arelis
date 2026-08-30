"""Bus-event presentation. ArelisWindow._on_event is a thin delegate.

Each EventType branch paints the glass. The window still owns widgets
and turn flags; this module is the table of what a bus event does to
them. Confirm execution stays in confirm_host; the plate stays in
world_host.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arelis.browser.hold import format_drive_status
from arelis.browser.walls import your_turn_status
from arelis.core.events import Event, EventType
from arelis.core.failure_copy import plain_reason, tool_failure_notice
from arelis.llm.startup import WARMUP_READY
from arelis.local_open import open_local_file, reveal_local_file
from arelis.spatial import PHYSICS_ROOM_ID
from arelis.ui.layout_store import push_recent_workspace_file
from arelis.ui.panels.workspace import is_workspace_listing, status_for_tool_result
from arelis.ui.status_copy import THINKING_STATUS, WAITING_STATUS, tool_status_line
from arelis.ui.world_host import should_offer_world

# A spoken reply holds the microphone closed. This is the backstop, sized
# for one very long sentence synthesizing while the previous one plays.
# Every clip and playback transition restarts it.
SPEECH_WATCHDOG_MS = 45000


def parse_role_set_message(message: str) -> str | None:
    """Extract role name from orchestrator `/role` STATUS text, else None."""
    marker = "Role set to `"
    if marker not in message:
        return None
    rest = message.split(marker, 1)[1]
    role, _, _ = rest.partition("`")
    role = role.strip().lower()
    if role in {"fast", "research"}:
        return role
    return None


def dispatch_event(window: Any, event: Event) -> None:
    """Render one bus event. Runs on the Qt thread via BusBridge.

    ASSISTANT_DONE and ERROR are the only two events that clear the busy
    state, so the orchestrator guarantees one of them per turn. Everything
    else here is presentation.
    """
    t = event.type
    p = event.payload
    if t == EventType.USER_MESSAGE:
        # Typed messages are already on screen: _on_submit paints them
        # before publishing. A spoken one has no such moment, so this is
        # where the user first sees what she heard, and where the turn is
        # marked busy. Busy is set here rather than at the end of the
        # recording on purpose: if transcription fails there is no turn, so
        # there would be no terminal event to release the composer.
        # Phone talk uses the same path: the companion is not the glass.
        if p.get("source") in {"voice", "mobile"}:
            text = p.get("text") or ""
            attachments = p.get("attachments") if p.get("source") == "mobile" else None
            window._mobile_foreign = p.get("source") == "mobile" and bool(
                p.get("foreign")
            )
            if not window._mobile_foreign:
                window.chat.add_user(text, attachments=list(attachments or []) or None)
                window.thinking.append(text, kind="trace")
            window._set_busy(True)
            if p.get("source") == "voice":
                prov = getattr(window, "_provisional_intent", None)
                if prov is not None:
                    from arelis.voice.speculate import speculation_matches_final

                    if not speculation_matches_final(prov, text):
                        window.thinking.append(
                            "Provisional hear cancelled (final transcript differed).",
                            kind="status",
                        )
                    window._provisional_intent = None
    elif t == EventType.VOICE_TRANSCRIPT:
        # Dictation never becomes a turn. It lands in the composer for the
        # user to edit and send themselves.
        if p.get("deliver") == "dictate":
            window.conversation.insert_dictation(p.get("text") or "")
    elif t == EventType.PHYSICS_VERB:
        # Closed verbs never publish USER_MESSAGE, so conversation would
        # wait for a turn that does not exist. Drop the awaiting latch
        # the same way an empty transcript does, then mutate the scene.
        if window.voice_controller is not None:
            window.voice_controller.notify_utterance_dropped()
        on_val = p.get("on")
        window._apply_physics_verb(
            str(p.get("verb") or ""),
            name=str(p.get("name") or ""),
            flag=str(p.get("flag") or ""),
            on=on_val if isinstance(on_val, bool) else None,
            page=str(p.get("page") or ""),
        )
    elif t == EventType.CONVERSATION_END:
        # Spoken hangup. Same latch as Ctrl+Shift+M off: the two-arcs
        # button, speak_replies, and wake listen. No turn starts.
        if window.voice_controller is not None:
            window.voice_controller.notify_utterance_dropped()
        window._hang_up_conversation()
    elif t == EventType.VOICE_AUDIO_READY:
        # Streaming TTS can deliver the first clip before ASSISTANT_DONE.
        # Arm here so the mic stays deaf across that early Piper work too.
        if not window._speech_expected:
            window._arm_speech()
        # Each clip is proof that synthesis is still making progress, which
        # is what keeps the speech watchdog from firing during a long answer.
        if window._speech_expected:
            window._speech_watchdog.start(SPEECH_WATCHDOG_MS)
        if window.speech_player is not None:
            window.speech_player.enqueue(
                str(p.get("path") or ""), int(p.get("utterance") or 0)
            )
    elif t == EventType.VOICE_SPEECH_DONE:
        window._on_speech_synthesized(int(p.get("clips") or 0))
    elif t == EventType.ASSISTANT_DELTA:
        if window._mobile_foreign:
            return
        window._clear_model_loading()
        # Keep the status line until the answer is finished. Clearing it on
        # the first token made tool turns flash: a preamble hid "thinking…",
        # then retract put it back. Tool copy still replaces this line.
        window.conversation.set_turn_visible(True)
        if not window._assistant_streaming:
            window.chat.begin_assistant()
            window._assistant_streaming = True
        window.chat.append_delta(p.get("text", ""))
    elif t == EventType.ASSISTANT_RETRACT:
        if window._mobile_foreign:
            return
        # The round turned out to be a tool call, so what was on screen was
        # a preamble. The agent loop mirrors it into the thinking dock.
        # Drop any speech that streamed from that preamble.
        window.chat.discard_stream()
        # This is the moment the thread empties itself, and the one that made
        # three spoken SMS turns look dead. Something has to remain.
        if window._turn_busy:
            window.chat.show_progress(window._busy_status_line())
        window._assistant_streaming = False
        window._stop_speech()
    elif t == EventType.ASSISTANT_DONE:
        if window._mobile_foreign:
            window._assistant_streaming = False
            window._mobile_foreign = False
            window._set_busy(False)
            window._refresh_history()
            return
        # Repaint from the payload rather than the accumulated deltas: it is
        # the authoritative answer, and it is the version that has the
        # Sources list appended. finish_assistant is idempotent when the
        # same body was already finalized (voice race with _close_stream).
        window._clear_model_loading()
        text = p.get("text") or ""
        if window._assistant_streaming:
            window.chat.finish_assistant(text)
        elif text:
            window.chat.finish_assistant(text)
        window._assistant_streaming = False
        # Do not dismiss an SMS auto-reply card just because a chat turn
        # finished: those confirms live outside the agent loop.
        confirm_id = window.conversation.confirm._confirm_id
        if not str(confirm_id).startswith("sms-auto-"):
            window.conversation.dismiss_confirm()
            window._set_confirm_pending(False)
        # Arm speech before clearing busy, not after. Both feed the same
        # decision in the voice controller, and clearing busy first leaves a
        # window where the turn is over and no reply is pending, which is
        # exactly the state that means "start listening again".
        if p.get("speak"):
            window._arm_speech()
        window._set_busy(False)
        window._refresh_history()
    elif t == EventType.MOBILE_SYNC:
        sid = str(p.get("session_id") or "")
        current = str(getattr(window.store, "session_id", "") or "")
        if sid and current and sid != current:
            return
        rows = p.get("messages") or []
        if isinstance(rows, list) and rows:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                role = str(row.get("role") or "")
                text = str(row.get("text") or "")
                if role == "user" and text:
                    window.chat.add_user(text)
                elif role == "assistant" and text:
                    window.chat.finish_assistant(text)
    elif t == EventType.SESSION_LOADED:
        if p.get("silent"):
            return
        if not p.get("ok"):
            window.chat.add_system(str(p.get("error") or "Could not load that conversation."))
            return
        window._assistant_streaming = False
        window.conversation.dismiss_confirm()
        window._set_confirm_pending(False)
        window.thinking.clear()
        messages = p.get("messages") or []
        if isinstance(messages, list):
            window.chat.load_messages(
                [
                    {
                        "role": str(m.get("role") or ""),
                        "content": str(m.get("content") or ""),
                        "note": str(m.get("note") or ""),
                    }
                    for m in messages
                    if isinstance(m, dict)
                ]
            )
        else:
            window.chat.clear()
        sid = str(p.get("session_id") or "")
        window._refresh_history()
        if sid:
            window.history.set_active(sid)
        window._drive_session = False
        window.conversation.set_drive(False)
        if p.get("new"):
            window.thinking.append("new conversation", kind="status")
        elif sid:
            window.thinking.append(f"loaded conversation {sid[:8]}", kind="status")
        # Re-surface in thinking after clear/load. This line is not a
        # conversation; painting it into chat used to hide the orbit.
        if window._inbound_banner:
            window.thinking.append(window._inbound_banner, kind="status")
        window._sync_idle_mode()
    elif t == EventType.ROOM_CHANGED:
        room_id = str(p.get("room_id") or "")
        window.conversation.room.set_room(
            room_id,
            name=str(p.get("name") or ""),
            purpose=str(p.get("purpose") or ""),
            root=str(p.get("root") or ""),
        )
        # The room owns a project, so the dock's switcher has to follow or
        # the two disagree about where a bare path lands.
        window.workspace.set_active_project(window.workspace_roots.active)
        window.camera.set_spatial_available(should_offer_world(room_id))
        window.spatial.set_room(room_id)
        if room_id != PHYSICS_ROOM_ID:
            window._hide_world()
        shown = str(p.get("name") or "").strip() or room_id or "general"
        window.thinking.append(f"room  {shown}", kind="status")
        window._sync_idle_mode()
    elif t == EventType.CALENDAR_CHANGED:
        if not window.calendar_window.isHidden():
            window.calendar.reload()
    elif t == EventType.TASKS_CHANGED:
        if not window.calendar_window.isHidden():
            window.calendar.reload_tasks()
    elif t == EventType.JOBS_CHANGED:
        if not window.calendar_window.isHidden():
            window.calendar.reload_jobs(select_id=str(p.get("id") or ""))
    elif t == EventType.THINKING:
        text = str(p.get("text") or "")
        if p.get("stream"):
            window.thinking.extend_stream(text)
        else:
            window.thinking.append(text, kind="trace")
        window._reveal_dock(window.think_dock, window.act_thinking)
    elif t == EventType.STATUS:
        msg = p.get("message", "")
        window.thinking.append(msg, kind="status")
        # Inbound listen/token belongs in thinking, not chat. A system
        # line here used to mark the thread as started and hide the orbit
        # on a cold launch the operator never typed into.
        if str(msg).startswith(("Inbound notify", "Phone notifications")):
            window._inbound_banner = str(msg)
        if msg.startswith("Active project set to"):
            window.workspace.set_active_project(window.workspace_roots.active)
        # /role ack: keep the composer pill in sync with the default role.
        role_set = parse_role_set_message(str(msg))
        if role_set:
            window._current_role = role_set
            window.conversation.role.blockSignals(True)
            window.conversation.role.setCurrentText(role_set)
            window.conversation.role.blockSignals(False)
        # Prefix seed just finished. A first message that was waiting on
        # it should stop claiming the model is still loading.
        if str(msg) == WARMUP_READY and window._turn_busy:
            window.chat.show_progress(THINKING_STATUS)
        window._schedule_readiness_probe()
    elif t == EventType.MODEL_SWITCH:
        window._current_model = p.get("to") or window._current_model
        window._current_role = p.get("role") or window._current_role
        window.thinking.append(
            f"{p.get('from')} → {p.get('to')} ({p.get('role')})",
            kind="model",
        )
        window._schedule_readiness_probe()
    elif t == EventType.TOOL_CONFIRM:
        if window._mobile_foreign:
            return
        window.conversation.ask_confirm(
            str(p.get("id") or ""),
            str(p.get("tool") or ""),
            str(p.get("summary") or ""),
            detail=str(p.get("detail") or ""),
            note=str(p.get("note") or ""),
            batch_ok=bool(p.get("batch_ok", True)),
            headline=str(p.get("headline") or ""),
        )
        window._set_confirm_pending(True)
        # The turn is blocked on a person, not working. Shimmering "writing
        # the text…" over an Allow card describes the wrong side of the wait.
        if window._turn_busy:
            window.chat.show_progress(WAITING_STATUS)
        window.conversation.set_turn_visible(True)
        window._reveal_dock(window.think_dock, window.act_thinking)
        window.thinking.append(f"allow  {p.get('headline') or p.get('summary')}", kind="tool")
    elif t == EventType.TOOL_CONFIRM_REPLY:
        # Timeout / remote skip — dismiss the open card if it matches.
        cid = str(p.get("id") or "")
        open_id = str(window.conversation.confirm._confirm_id or "")
        if cid and cid == open_id:
            window.conversation.dismiss_confirm()
            window._set_confirm_pending(False)
            if p.get("reason") == "timeout":
                window.thinking.append("confirm timed out — denied", kind="status")
            elif p.get("reason") == "voice":
                said = "allow" if p.get("decision") == "allow" else "deny"
                window.thinking.append(f"voice {said}", kind="status")
    elif t == EventType.TOOL_START:
        tool = p.get("tool")
        args = p.get("args") or {}
        # Short args for thinking — never dump file bodies
        brief = {k: (str(v)[:60] + "…" if len(str(v)) > 60 else v) for k, v in args.items()}
        window.thinking.append(f"{tool} {brief}", kind="tool")
        if str(tool or "") == "workspace" and isinstance(args, dict):
            window._workspace_tool_args = dict(args)
        # Said in the transcript, in the user's words, whether or not the
        # Thinking dock is open. `weather {'days': 2}` is for me; "checking
        # the weather" is for her.
        window.chat.show_progress(tool_status_line(str(tool or ""), args))
        window.conversation.set_turn_visible(True)
        window._reveal_dock(window.think_dock, window.act_thinking)
        # File / image work surfaces the workspace band (Pass C).
        if str(tool or "") in {
            "workspace",
            "analyze",
            "image",
            "research_report",
            "doc_extract",
            "ocr",
        }:
            window._reveal_dock(window.work_dock, window.act_workspace)
        # The shimmer is set for every tool now, so image needs no special
        # case beyond its own Thinking line.
        if str(tool or "") == "image":
            window.thinking.append("Generating image…", kind="status")
        if str(tool or "") in {"image", "research_report"}:
            window._begin_job(str(tool))
        if str(tool or "") == "browser":
            action = str(args.get("action") or "")
            window._drive_session = True
            window.conversation.set_drive(True, format_drive_status(action, args))
    elif t == EventType.TOOL_RESULT:
        window.thinking.append(f"ok={p.get('ok')} {p.get('tool')}", kind="tool")
        # Back to the bare waiting state: the errand is over but the turn is
        # not, and leaving "checking the weather…" up would be a small lie
        # that runs for the rest of the round.
        if window._turn_busy:
            window.chat.show_progress(window._busy_status_line())
        data = p.get("data") or {}
        intro = str(data.get("intro") or "").strip()
        if p.get("tool") == "agenda" and p.get("ok") and data.get("open"):
            window.act_calendar.setChecked(True)
            window._toggle_calendar(True)
        if p.get("tool") == "agenda" and p.get("ok") and data.get("close"):
            window.act_calendar.setChecked(False)
            window._toggle_calendar(False)
        if p.get("tool") == "schedule" and p.get("ok"):
            window._reveal_calendar_jobs()
            job_id = str(data.get("id") or "")
            if job_id:
                window.calendar.reload_jobs(select_id=job_id)
        if p.get("tool") == "tile" and p.get("ok"):
            window._apply_tile(
                str(data.get("name") or ""),
                show=bool(data.get("open")) and not data.get("close"),
                page=str(data.get("page") or ""),
            )
        if p.get("tool") == "browser":
            if intro:
                window.chat.add_system(intro)
            code = str(data.get("code") or "")
            wall = str(data.get("wall") or "")
            if code in {"YOUR_TURN", "SECRET_FIELD"}:
                kind = wall or ("login" if code == "SECRET_FIELD" else "")
                line = your_turn_status(kind)
                window.conversation.set_drive_your_turn(line)
                note = ""
                for raw in str(p.get("output") or "").splitlines():
                    if raw.strip().lower().startswith("your turn"):
                        note = raw.strip()
                        break
                window.chat.add_system(note or "Your turn — the page stays.")
                window.thinking.append(f"your turn  {kind or code}", kind="status")
            else:
                out = str(p.get("output") or "").strip()
                if out:
                    window.conversation.set_drive_status(out.splitlines()[0][:80])
        if p.get("tool") in {"image", "image_edit"}:
            if p.get("ok"):
                window.chat.add_system("Image ready — open in Workspace")
            else:
                window.chat.add_system(
                    tool_failure_notice("image", str(p.get("output") or ""))
                )
        if str(p.get("tool") or "") in {"image", "research_report"}:
            window._finish_job(
                str(p.get("tool") or "job"),
                ok=bool(p.get("ok")),
                output=str(p.get("output") or ""),
            )
        if p.get("tool") == "send_sms" and p.get("ok"):
            window.sms_chats.append_outbound(
                body=str(data.get("body") or ""),
                alias=str(data.get("alias") or ""),
                phone=str(data.get("phone") or ""),
            )
        if p.get("tool") in {"workspace", "analyze"}:
            payload_args = p.get("args") if isinstance(p.get("args"), dict) else {}
            action = str(
                payload_args.get("action")
                or window._workspace_tool_args.get("action")
                or ""
            )
            out = str(p.get("output") or "")
            status = status_for_tool_result(
                str(p.get("tool") or ""),
                ok=bool(p.get("ok")),
                action=action,
                output=out,
            )
            if status:
                window.workspace.append_output(status)
            if not p.get("ok") and out:
                # Wrong/empty path used to look like a silent Open no-op, so
                # the failure still reaches chat. It goes through the copy
                # boundary first: "Not a file: C:/typo.csv" is the whole
                # answer and passes through, while analyze's own advice to
                # the model — "Call vision(path=…) for an image" — does not.
                window.chat.add_system(
                    tool_failure_notice(str(p.get("tool") or ""), str(out))
                )
                window._reveal_dock(window.work_dock, window.act_workspace)
        if p.get("tool") == "workspace" and p.get("ok"):
            payload_args = p.get("args") if isinstance(p.get("args"), dict) else {}
            action = str(
                payload_args.get("action")
                or window._workspace_tool_args.get("action")
                or ""
            )
            display = str(data.get("path") or "")
            abs_path = str(data.get("abs_path") or "")
            root_name = str(data.get("root_name") or "")
            if is_workspace_listing(action, str(p.get("output") or ""), abs_path):
                window.workspace.browse_to(abs_path, root_name=root_name)
                window._reveal_dock(window.work_dock, window.act_workspace)
            elif display:
                read_from = abs_path or display
                target = Path(read_from)
                if target.is_dir():
                    window.workspace.browse_to(read_from, root_name=root_name)
                    window._reveal_dock(window.work_dock, window.act_workspace)
                elif target.is_file():
                    try:
                        content = Path(read_from).read_text(
                            encoding="utf-8", errors="replace"
                        )
                        placed = window.workspace.set_file(
                            display, content, root_name=root_name, abs_path=abs_path
                        )
                        if placed:
                            window.workspace.set_recent(
                                push_recent_workspace_file(display)
                            )
                        else:
                            window.chat.add_system(
                                f"I wrote {display}, but you have unsaved edits open in the "
                                "editor, so I left them alone. Open the file again to see my "
                                "version — that replaces what is in the editor."
                            )
                        window._reveal_dock(window.work_dock, window.act_workspace)
                    except Exception as exc:
                        # The write landed; only the editor refresh did not. Saying
                        # nothing leaves the same impression the clobber bug did —
                        # that the file on screen is the file on disk.
                        window.chat.add_system(
                            f"I wrote {display}, but could not read it back into the "
                            f"editor: {plain_reason(exc)}. The version on disk is mine; "
                            "open the file again to see it."
                        )
                        window.thinking.append(
                            f"workspace read-back failed: {exc}", kind="status"
                        )
                else:
                    # ok=True naming a path that is neither a file nor a
                    # directory. The editor cannot move, and staying quiet
                    # reads the same way the clobber bug did: whatever is on
                    # screen looks like what is on disk.
                    window.chat.add_system(
                        f"I reported writing {display}, but could not read it "
                        "back — nothing is at that path now. Treat the write as "
                        "failed and check the file before relying on it."
                    )
                    window.thinking.append(
                        f"workspace read-back failed: {read_from} is not on disk",
                        kind="status",
                    )
        if p.get("tool") == "workspace":
            window._workspace_tool_args = {}
    elif t == EventType.IMAGE_READY:
        path = p.get("path")
        if path:
            window.workspace.show_image(path)
            window.workspace.append_output(f"Image ready — {Path(str(path)).name}")
            window._reveal_dock(window.work_dock, window.act_workspace)
    elif t == EventType.FILE_READY:
        abs_path = str(p.get("abs_path") or p.get("path") or "").strip()
        name = str(p.get("title") or "").strip()
        if not name and abs_path:
            name = Path(abs_path).name
        if abs_path and p.get("show_card", True):
            window.chat.add_file_card(name or Path(abs_path).name, abs_path)
        if abs_path and p.get("open"):
            try:
                open_local_file(abs_path)
            except OSError as exc:
                leaf = Path(abs_path).name or "that file"
                window.chat.add_system(
                    f"I could not open {leaf}. {plain_reason(exc)}"
                )
        if abs_path and p.get("reveal"):
            try:
                reveal_local_file(abs_path)
            except OSError as exc:
                leaf = Path(abs_path).name or "that file"
                window.chat.add_system(
                    f"I could not show {leaf}. {plain_reason(exc)}"
                )
    elif t == EventType.SMS_RECEIVED:
        window._on_sms_received(p)
    elif t == EventType.TURN_CANCEL:
        # Voice stop publishes cancel from the orchestrator. The stop
        # button publishes it too — skip the echo so we do not double-cut.
        if window._ignore_cancel_echo:
            window._ignore_cancel_echo = False
        else:
            window._apply_stop_ui(publish_confirm_skip=False)
            if not window._force_quit and not window._disposed:
                window._later(0, window._show_next_pending_confirm)
    elif t == EventType.TURN_PAUSE:
        if str(p.get("reason") or "") == "your_turn":
            kind = str(p.get("kind") or "")
            window.conversation.set_drive_your_turn(your_turn_status(kind))
    elif t == EventType.TURN_RESUME:
        if str(p.get("reason") or "") == "wall_cleared":
            window.conversation.set_drive_paused(False)
            window.conversation.set_drive_status("continuing…")
            window.thinking.append("wall gone — continuing", kind="status")
    elif t == EventType.ERROR:
        if window._mobile_foreign:
            window._mobile_foreign = False
            if p.get("scope") != "voice":
                window._assistant_streaming = False
                window._set_busy(False)
            return
        message = p.get("message", "Error")
        # The publisher's own split: `message` is for the person, `detail` is
        # the exception. Thinking used to get the chat line twice over and the
        # detail nowhere, so the one place with room for it showed the least.
        detail = str(p.get("detail") or "").strip()
        window.chat.add_system(message)
        window.thinking.append(message, kind="status")
        if detail and detail != message:
            window.thinking.append(detail, kind="status")
        # A voice failure happens outside any turn. Ending the turn on it
        # would re-enable the composer and dismiss a confirm card that the
        # agent loop is still waiting on, stranding the turn for good.
        if p.get("scope") != "voice":
            window._assistant_streaming = False
            window.conversation.dismiss_confirm()
            window._set_confirm_pending(False)
            window._stop_speech()
            window._set_busy(False)

