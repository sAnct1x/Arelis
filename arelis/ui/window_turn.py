"""Submit, stop, confirm cards, and busy state.

Mixin on ArelisWindow. Same HWND. Not a second QMainWindow.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from arelis.core.events import Event, EventType
from arelis.presence.pending_confirms import (
    PendingConfirm,
)
from arelis.sms_inbound import floor_is_busy
from arelis.ui.confirm_host import emit_restored_confirm
from arelis.ui.event_host import dispatch_event
from arelis.ui.foreground import flash_taskbar, process_owns_foreground
from arelis.ui.idle_host import note_engagement, sync_idle_mode
from arelis.ui.sms_host import flush_held_inbound
from arelis.ui.status_copy import THINKING_STATUS, WARMING_STATUS
from arelis.ui.theme import (
    GLASS,
    SHELL,
    active_theme,
)
from arelis.ui.voice_host import stop_speech
from arelis.ui.workspace_host import refresh_desk

log = logging.getLogger(__name__)

_WINDOW_RADIUS = int(GLASS["radius"])
_BUSY_WATCHDOG_MS = 8000
_THINK_PULSE_MS = 600
_VOICE_HOTKEY_ECHO_S = 0.12

_PANEL_OUTER = SHELL["outer"]
_PANEL_HALF = SHELL["half"]
_PANEL_TOP = SHELL["top"]
_PANEL_BOTTOM = SHELL["bottom"]



class WindowTurn:
    def _run_ui_call(self, fn) -> None:
        if getattr(self, "_disposed", False) or getattr(self, "_force_quit", False):
            return
        if callable(fn):
            fn()

    def queue_pending_confirms(self, items: list[PendingConfirm]) -> None:
        """Show stored send confirms (e.g. from `arelis --core` drafts)."""
        self._pending_queue = list(items)
        for item in items:
            self._restoring_confirm_ids.add(item.id)
        self._show_next_pending_confirm()

    def _show_next_pending_confirm(self) -> None:
        if self._force_quit or self._disposed:
            return
        if not self._pending_queue:
            return
        if str(self.conversation.confirm._confirm_id or ""):
            return
        item = self._pending_queue[0]
        self.conversation.ask_confirm(
            item.id,
            item.tool,
            item.summary,
            detail=item.detail,
            note=item.note
            or "Restored pending send — nothing was sent while you were away.",
            batch_ok=item.batch_ok,
        )
        self._set_confirm_pending(True)
        self.thinking.append(f"confirm  {item.summary}", kind="tool")
        if self.isHidden():
            self.show_from_tray()

    def _on_index_tick(self) -> None:
        if self._force_quit or self._disposed:
            return
        if self.indexer is None or self._turn_busy:
            return
        if getattr(self.router, "reserve_vram_for_heavy", False):
            return
        loop = self.loop
        if loop is None or not loop.is_running():
            return
        asyncio.run_coroutine_threadsafe(self.indexer.run_batch(), loop)

    def _on_attach_errors(self, errors: list) -> None:
        for msg in errors or []:
            text = str(msg).strip()
            if text:
                self.chat.add_system(text)

    def _on_again(self) -> None:
        """Re-submit the last user turn. Same role; composer stays empty."""
        if self._turn_busy:
            self._toast_finish_or_stop(
                "Finish or stop the current turn before asking again."
            )
            return
        text = self.chat._last_user_text
        attachments = list(self.chat._last_user_attachments or [])
        if not text and not attachments:
            return
        role = self._current_role or self.conversation.role.currentText()
        self._on_submit(text, role, attachments)

    def _on_submit(self, text: str, role: str, attachments: list | None = None) -> None:
        note_engagement(self)
        if not attachments and self._try_physics_verb(text):
            return
        if not attachments and self._try_tile_speech(text):
            return
        attachments = list(attachments or [])
        self._current_role = role
        # Grant session read on each original absolute path (attach = consent).
        for item in attachments:
            source = str(item.get("source_path") or "").strip()
            if source:
                try:
                    self.workspace_roots.grant_external_read(source)
                except Exception:
                    pass
        self._set_busy(True)
        self.chat.add_user(text, attachments=attachments)
        sync_idle_mode(self)
        if not (text or "").lstrip().startswith("/"):
            self._show_model_loading(role)
        payload: dict = {"text": text, "role": role}
        if attachments:
            payload["attachments"] = attachments
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.USER_MESSAGE, payload)),
            self.loop,
        )

    def _show_model_loading(self, role: str) -> None:
        """Composer hint while waiting for first token (L1 cold TTFT)."""
        pending = getattr(self.router, "warmup_pending", None)
        if callable(pending) and pending():
            tip = "loading the model — first reply after that is quick"
        else:
            model = str(
                (self.config.get("models") or {}).get(role) or self._current_model or ""
            )
            tip = f"thinking… ({role}" + (f":{model}" if model else "") + ")"
        self.thinking.append(tip, kind="status")
        if self.conversation.confirm_open():
            return
        if self.conversation.input.text().strip():
            return
        self.conversation.input.setPlaceholderText(tip)

    def _clear_model_loading(self) -> None:
        self.conversation._sync_composer_buttons()

    def _publish_bus(self, event: Event) -> None:
        """Best-effort bus publish. Tray Quit must not die if the loop is down."""
        loop = self.loop
        if loop is None or not loop.is_running():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.bus.publish(event), loop)
        except Exception:
            log.debug("bus publish skipped", exc_info=True)

    def _on_stop(self) -> None:
        self._cancel_turn(schedule_next=True)

    def _cancel_turn(self, *, schedule_next: bool) -> None:
        self._apply_stop_ui(publish_confirm_skip=True)
        self._ignore_cancel_echo = True
        self._publish_bus(Event(EventType.TURN_CANCEL, {}))
        if schedule_next and not self._force_quit and not self._disposed:
            self._later(0, self._show_next_pending_confirm)

    def _apply_stop_ui(self, *, publish_confirm_skip: bool) -> None:
        """Cut speech and hide the card. The bus cancel is published separately."""
        open_id = str(self.conversation.confirm._confirm_id or "")
        self.conversation.dismiss_confirm()
        self._set_confirm_pending(False)
        if open_id:
            self._pending_queue = [x for x in self._pending_queue if x.id != open_id]
            self._restoring_confirm_ids.discard(open_id)
            if publish_confirm_skip:
                self._publish_bus(
                    Event(
                        EventType.TOOL_CONFIRM_REPLY,
                        {"id": open_id, "decision": "skip", "allow_turn": False},
                    )
                )
        # Stop means stop. Speech outlives the turn that produced it, so
        # cancelling the turn without cutting playback leaves her talking about
        # something the user has already abandoned.
        stop_speech(self)
        self.thinking.append("stop requested", kind="status")
        from arelis.browser.live import cancel as cancel_watch

        cancel_watch()
        self._drive_session = False
        self.conversation.set_drive(False)
        if not self._force_quit and not self._disposed:
            self._busy_watchdog.start(_BUSY_WATCHDOG_MS)

    def _on_stop_declined(self) -> None:
        """Esc on a turn that has painted nothing. Explain instead of cancelling.

        Three spoken SMS turns died here: the answer is held back until the
        tools have run, so the thread was blank, Esc read as "clear this", and
        the send was cancelled before its Allow card existed.
        """
        message = (
            "Still working — the answer is held back until the tools finish. "
            "Press stop to cancel it."
        )
        self.thinking.append(message, kind="status")
        # With the thinking dock closed that line lands somewhere nobody is
        # looking, and pressing Esc into total silence is what made the app feel
        # hung in the first place.
        if not self.think_dock.isVisible():
            self.chat.add_system(message)

    def _on_drive_pause(self) -> None:
        self.thinking.append("drive paused", kind="status")
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.TURN_PAUSE, {})),
            self.loop,
        )

    def _on_drive_resume(self) -> None:
        self.thinking.append("drive resumed", kind="status")
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(Event(EventType.TURN_RESUME, {})),
            self.loop,
        )

    def _on_busy_watchdog(self) -> None:
        if self._force_quit or self._disposed:
            return
        if self._turn_busy:
            self._assistant_streaming = False
            self._set_busy(False)
            self.chat.add_system("Turn ended without a reply. Input re-enabled.")

    def _on_confirm_decided(self, confirm_id: str, decision: str, allow_turn: bool) -> None:
        note_engagement(self)
        # Clear the voice hold before the reply hits the bus so conversation
        # mode is not stuck deaf for an extra event-loop hop after Allow/Skip.
        self._set_confirm_pending(False)
        restoring = confirm_id in self._restoring_confirm_ids
        stored = self._pending_store.get(confirm_id)
        self._pending_queue = [x for x in self._pending_queue if x.id != confirm_id]
        self._restoring_confirm_ids.discard(confirm_id)
        asyncio.run_coroutine_threadsafe(
            self.bus.publish(
                Event(
                    EventType.TOOL_CONFIRM_REPLY,
                    {"id": confirm_id, "decision": decision, "allow_turn": allow_turn},
                )
            ),
            self.loop,
        )
        # When attached to a detached core, also notify its bus (no silent send —
        # this only carries the human decision).
        if self.ipc_client is not None:
            asyncio.run_coroutine_threadsafe(
                self.ipc_client.send_confirm_reply(confirm_id, decision),
                self.loop,
            )
        # Restored / core-parked cards have no live waiter — Allow must send here.
        if restoring and decision in {"allow", "allow_turn", "allow_always"} and stored is not None:
            asyncio.run_coroutine_threadsafe(
                self._execute_restored_confirm(stored),
                self.loop,
            )
        elif restoring and decision not in {"allow", "allow_turn", "allow_always"}:
            self.thinking.append("pending send skipped", kind="status")
        self._later(0, self._show_next_pending_confirm)

    async def _execute_restored_confirm(self, item: PendingConfirm) -> None:
        await emit_restored_confirm(self.bus, item, self.config)

    def _set_confirm_pending(self, pending: bool) -> None:
        self._confirm_waiting = bool(pending)
        self.readiness_strip.set_confirm_waiting(pending)
        if self.voice_controller is not None:
            self.voice_controller.notify_confirm_pending(pending)
        if not pending:
            flush_held_inbound(self)
        if active_theme() == "filament":
            self._place_filament_floats(reshape=False)

    def _busy_status_line(self) -> str:
        """Shimmer copy for an in-flight turn with no named tool yet."""
        pending = getattr(self.router, "warmup_pending", None)
        if callable(pending) and pending():
            return WARMING_STATUS
        return THINKING_STATUS

    def _set_busy(self, busy: bool) -> None:
        self._turn_busy = busy
        self.conversation.set_busy(busy)
        self.history.set_switch_enabled(not busy)
        # Every turn status hangs off this one flag, so no shimmer can outlive the
        # turn that started it — including the turns that end at the watchdog
        # rather than at an answer.
        if busy:
            self.chat.show_progress(self._busy_status_line())
        else:
            self.chat.clear_progress()
        if not busy:
            self._busy_watchdog.stop()
            self._clear_model_loading()
            from arelis.browser.live import is_watching

            if is_watching():
                self._drive_session = True
                self.conversation.set_drive(True, "Watching")
            elif self._drive_session:
                if not self.conversation.drive.is_paused():
                    self.conversation.set_drive_status("page stays")
            else:
                self.conversation.set_drive(False)
        if self.voice_controller is not None:
            if busy:
                self.voice_controller.notify_turn_started()
            else:
                self.voice_controller.notify_turn_finished()
        if not busy:
            flush_held_inbound(self)
        sync_idle_mode(self)

    def _on_project_changed(self, name: str) -> None:
        """Update the shared active project from the dock switcher (Qt thread)."""
        try:
            self.workspace_roots.set_active(name)
        except ValueError as exc:
            self.chat.add_system(str(exc))
            self.workspace.set_active_project(self.workspace_roots.active)
            return
        self.thinking.append(f"project  active → {name}", kind="status")
        refresh_desk(self)

    def _keep_file_on_desk(self, path: str) -> None:
        from arelis.ui.workspace_host import record_artifact

        record_artifact(self, path, source="open", pin=True)
        self.workspace.show_desk()
        self._reveal_dock(self.work_dock, self.act_workspace)
        self.chat.add_system(f"On the desk: {Path(path).name}")

    def _on_event(self, event: Event) -> None:
        dispatch_event(self, event)

    def _alert_if_background(self) -> None:
        """Flash the Arelis taskbar button when another app is in front."""
        if self._force_quit or self._disposed:
            return
        if process_owns_foreground():
            return
        flash_taskbar(self)

    def _floor_busy(self) -> bool:
        speaking = self._speech_expected or self._speech_playing or (
            self.speech_player is not None and self.speech_player.has_work()
        )
        return floor_is_busy(
            turn_busy=self._turn_busy,
            confirm_open=self.conversation.confirm_open(),
            speaking=speaking,
        )
