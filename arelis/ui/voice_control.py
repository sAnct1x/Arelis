"""Voice modes as a state machine on the Qt thread.

Three modes share one microphone:

- Wake (idle): always listening for "Hey Arelis". Clips are transcribed but not
  sent until the wake phrase matches; the window then enters conversation.
- Dictation: manual. Mic stays open through pauses; text accumulates in the
  composer; nothing is sent.
- Conversation: hands-free. Stop talking and she sends, answers, speaks, and
  listens again. Talking over her cuts her off.

This object never touches the bus or the widgets. It emits utterances and asks
questions; the window does the plumbing.

Listening is derived, not latched. Conversation mode is deaf while any of four
things is true -- a turn is running, an utterance is waiting to become one, a
spoken reply is in flight, or a confirm card is waiting on the user -- and
listening again is simply the moment all four go false. An earlier version kept
a separate "resume when she is done" flag, which is the same fact stored twice,
and the two disagreed constantly: the flag was consumed when the turn ended,
roughly a second before Piper produced the first clip, so the microphone
reopened while she was still about to talk. Her own voice then came back through
the speakers as the next question. Deriving the answer from the inputs makes
that state unrepresentable.

The microphone is not closed while she talks, because barge-in needs to hear the
user interrupt. Barge-in is the interrupt: talking over her cuts playback.
That same clip is not a new turn (it is still her voice mixed into the mic).
It is transcribed as deliver "control" so a spoken stop / allow / deny on
that clip is not thrown away. Soup is dropped after STT. The next clean
utterance is a normal turn — same as before.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from arelis.ui.audio import MicRecorder
from arelis.voice.pcm import duration_seconds, trim_trailing_silence
from arelis.voice.telemetry import VoiceTrace, trace_enabled
from arelis.voice.vad import (
    ENDED,
    STARTED,
    TIMEOUT,
    DetectorConfig,
    EnergyUtteranceDetector,
    make_utterance_detector,
)

log = logging.getLogger(__name__)

OFF = "off"
WAKE = "wake"
DICTATE = "dictate"
CONVERSATION = "conversation"

# Shorter than this and it was a click on the button, a cough, or a bump on the
# desk. Sending it costs a model turn and produces "you" or "thank you", which
# is what Whisper hallucinates from a fraction of a second of noise.
_MIN_UTTERANCE_S = 0.3
# Wake clips need a bit more body so room noise does not monopolise Whisper.
_MIN_WAKE_UTTERANCE_S = 0.55

# An utterance is handed to the window and the window is expected to report back
# whether it became a turn. Everything in that path is bounded -- a Whisper run,
# possibly queued behind one other -- but a lost callback used to leave
# conversation mode deaf for the rest of the session with no way out but
# toggling it off and on. Generous enough that a cold model load does not trip
# it, short enough that the user has not given up by the time it recovers.
_AWAITING_TURN_TIMEOUT_MS = 30000


class VoiceController(QObject):
    """Owns the microphone and decides what each recorded utterance is for."""

    # pcm, sample_rate, channels, deliver ("turn", "dictate", "wake", or "control")
    utterance = Signal(bytes, int, int, str)
    # Mid-utterance snapshot for provisional STT (conversation only).
    provisional = Signal(bytes, int, int)
    status = Signal(str)
    failed = Signal(str)
    mode_changed = Signal(str)
    # True while the user is being listened to, for the level indicator.
    listening_changed = Signal(bool)
    barge_in = Signal()

    def __init__(self, config: dict[str, Any], parent: QObject | None = None) -> None:
        super().__init__(parent)
        voice = config.get("voice", {})
        conversation = voice.get("conversation", {})
        wake_cfg = voice.get("wake") or {}
        self._wake_enabled = bool(wake_cfg.get("enabled", True))
        self._barge_in_enabled = bool(conversation.get("barge_in", True))
        silence_ms = int(conversation.get("silence_ms", 900))
        agent = config.get("agent") or {}
        self._speculate_preflight = bool(agent.get("voice_speculate_preflight", True))
        vad_cfg = voice.get("vad") or {}
        self._vad_backend = str(vad_cfg.get("backend") or "silero").strip().lower()
        self._vad_threshold = float(vad_cfg.get("threshold", 0.5))
        self._vad_end_threshold = float(vad_cfg.get("end_threshold", 0.0) or 0.0)
        self._vad_onset_ms = int(vad_cfg.get("onset_ms", 160))
        self._silero_model_path = str(vad_cfg.get("model_path") or "").strip()
        self._vad_allow_download = bool(vad_cfg.get("allow_download", True))
        # openWakeWord idle engine (M2). whisper = legacy energy+STT wake clips.
        # auto → openwakeword when models/wake/hey_arelis.onnx exists.
        raw_engine = str(wake_cfg.get("engine") or "auto").strip().lower()
        self._wake_threshold = float(wake_cfg.get("threshold", 0.5))
        self._wake_model_path = str(wake_cfg.get("model_path") or "").strip()
        self._wake_cooldown_ms = int(wake_cfg.get("cooldown_ms", 1500))
        self._openwake = None
        if raw_engine == "auto":
            from arelis.voice.openwake import openwake_available

            self._wake_engine = (
                "openwakeword"
                if openwake_available(self._wake_model_path or None)
                else "whisper"
            )
        else:
            self._wake_engine = raw_engine
        self._detector_defaults = {
            "silence_ms": silence_ms,
            # Adaptive end-point: short commands end sooner; long thoughts keep
            # silence_ms. Wake disables this by setting short == silence.
            "short_silence_ms": int(conversation.get("short_silence_ms", 550)),
            "short_utterance_ms": int(conversation.get("short_utterance_ms", 2800)),
            "speech_level": float(conversation.get("speech_level", 0.02)),
            "max_utterance_s": int(conversation.get("max_utterance_s", 60)),
            "speech_threshold": self._vad_threshold,
            "end_threshold": self._vad_end_threshold,
            "onset_ms": self._vad_onset_ms,
            "silero_model_path": self._silero_model_path,
        }
        # Wake listen is pickier: ambient noise must not queue Whisper ahead of
        # real conversation turns (STT is single-threaded under a lock).
        # Cap wake clips short — a stuck VAD used to dump multi-minute buffers
        # into Whisper, which hallucinated junk and never matched the wake.
        wake_silence = int(wake_cfg.get("silence_ms", 900))
        self._wake_detector_defaults = {
            **self._detector_defaults,
            "silence_ms": wake_silence,
            "short_silence_ms": wake_silence,
            "speech_level": float(wake_cfg.get("speech_level", 0.03)),
            "max_utterance_s": int(wake_cfg.get("max_utterance_s", 8)),
        }
        self.trace = VoiceTrace(trace_enabled(config))
        self.recorder = MicRecorder(
            sample_rate=int(voice.get("stt", {}).get("sample_rate", 16000)),
            device_hint=str(voice.get("input_device") or ""),
            parent=self,
        )
        self.recorder.frames.connect(self._on_frames)
        self.recorder.failed.connect(self.failed)

        self._mode = OFF
        self._detector = EnergyUtteranceDetector()
        self._ensure_openwake()
        self._vad_fallback_announced = False
        # The inputs that decide whether conversation mode is listening.
        # All are reported by the window; none is inferred here.
        self._turn_busy = False
        self._speaking = False
        self._awaiting_turn = False
        self._confirm_pending = False
        # One-shot: the clip that cut her off is TTS+mic soup. Trash it.
        self._discard_barge_clip = False
        # Derived from the gates above. Cached only so the transition can be
        # detected and the signal emitted once per change.
        self._listening = False
        # Hard stop (failure / teardown): do not auto-resume wake listen.
        self._wake_suspended = False
        self._mic_retries = 0

        self._turn_watchdog = QTimer(self)
        self._turn_watchdog.setSingleShot(True)
        self._turn_watchdog.timeout.connect(self._on_turn_watchdog)
        # One mid-utterance peek for provisional weather/SMS intent (Phase E).
        self._speculate_timer = QTimer(self)
        self._speculate_timer.setSingleShot(True)
        self._speculate_timer.timeout.connect(self._on_speculate_tick)
        self._speculate_armed = False

    # ------------------------------------------------------------- readiness

    def problem(self) -> str | None:
        return self.recorder.problem()

    def available(self) -> bool:
        return self.recorder.problem() is None

    def device_name(self) -> str:
        return self.recorder.device_name()

    def set_input_device(self, hint: str) -> None:
        """Change mic device without tearing down voice modes."""
        self.recorder.set_device_hint(hint or "")

    def mode(self) -> str:
        return self._mode

    def listening(self) -> bool:
        return self._listening

    def debug_state(self) -> dict[str, Any]:
        """The whole state vector, for the trace and for tests."""
        return {
            "mode": self._mode,
            "listening": self._listening,
            "turn_busy": self._turn_busy,
            "awaiting": self._awaiting_turn,
            "speaking": self._speaking,
            "confirm_pending": self._confirm_pending,
            "discard_barge": self._discard_barge_clip,
            "mic": self.recorder.is_recording(),
            "vad": self._detector.speaking,
            "vad_backend": getattr(self._detector, "backend", "energy"),
            "wake_engine": self._wake_engine,
        }

    # ------------------------------------------------------------ mode entry

    def start_wake(self) -> None:
        """Begin always-listen for the wake phrase (app open / leave converse)."""
        if not self._wake_enabled or self._wake_suspended:
            return
        if self._mode in {DICTATE, CONVERSATION}:
            return
        if self._mode == WAKE and self.recorder.is_recording():
            return
        self._enter(WAKE)

    def set_dictate(self, on: bool) -> None:
        if on:
            self._enter(DICTATE)
        elif self._mode == DICTATE:
            self._leave(flush=True, resume_wake=True)

    def set_conversation(self, on: bool) -> None:
        if on:
            self._enter(CONVERSATION)
        elif self._mode == CONVERSATION:
            self._leave(flush=False, resume_wake=True)

    def stop_all(self) -> None:
        """Hard stop: mic off, no wake resume (failure or teardown)."""
        self._wake_suspended = True
        if self._mode != OFF:
            self._leave(flush=False, resume_wake=False, announce_off=True)

    def resume_wake(self) -> None:
        """Clear a hard stop and return to Hey Arelis listen when idle."""
        self._wake_suspended = False
        self.start_wake()

    def _enter(self, mode: str) -> None:
        if self._mode == mode:
            return
        prev = self._mode
        # Wake ↔ conversation ↔ dictate: keep the mic open. Tearing it down and
        # recalibrating right after "Hey Arelis" often raises the VAD floor so
        # the next utterance never crosses threshold (listening=1, no speech_start).
        if prev != OFF and self.recorder.is_recording():
            self._mode = mode
            self._clear_awaiting()
            self._discard_barge_clip = False
            if mode != WAKE:
                self._wake_suspended = False
            self._apply_detector_for_mode()
            # Wake → conversation: the buffer is the command after "Hey Arelis".
            # take() here was throwing away "what's the weather" while Whisper
            # was still finishing the wake clip.
            if not (prev == WAKE and mode == CONVERSATION):
                self.recorder.take()
            if mode == WAKE and self._openwake is not None:
                self._openwake.reset()
                self._openwake.set_device_rate(self.recorder.sample_rate)
            self.trace.record("enter", hot_swap=1, **self.debug_state())
            self.mode_changed.emit(self._mode)
            self._announce_mode(mode)
            self._sync_listening(announce=False)
            return
        if prev != OFF:
            self._leave(flush=False, resume_wake=False)
        problem = self.recorder.problem()
        if problem:
            self.failed.emit(problem)
            return
        self._mode = mode
        self._clear_awaiting()
        self._discard_barge_clip = False
        if mode != WAKE:
            self._wake_suspended = False
        if not self._open_mic():
            self._mode = OFF
            self._sync_listening()
            self.mode_changed.emit(self._mode)
            return
        self.trace.record("enter", **self.debug_state())
        self.mode_changed.emit(self._mode)
        self._announce_mode(mode)
        self._sync_listening(announce=False)

    def _announce_mode(self, mode: str) -> None:
        if mode == DICTATE:
            self.status.emit("Dictating. Talk as long as you like, then toggle the mic off.")
        elif mode == CONVERSATION:
            self.status.emit(
                "Conversation mode on. Start talking whenever you are ready."
            )
        else:
            self.status.emit("Listening for Hey Arelis.")

    def _leave(self, *, flush: bool, resume_wake: bool, announce_off: bool = False) -> None:
        mode = self._mode
        self._mode = OFF
        self._clear_awaiting()
        self._discard_barge_clip = False
        pcm = self.recorder.stop()
        self._sync_listening()
        self.trace.record("leave", from_mode=mode, **self.debug_state())
        if flush and mode == DICTATE:
            self._emit_utterance(pcm, DICTATE)
        self.mode_changed.emit(OFF)
        if resume_wake and self._wake_enabled and not self._wake_suspended:
            # Defer so mode_changed handlers see OFF before wake re-enters.
            QTimer.singleShot(0, self.start_wake)
        elif announce_off:
            self.status.emit("Voice input off.")

    def _apply_detector_for_mode(self) -> None:
        defaults = (
            self._wake_detector_defaults if self._mode == WAKE else self._detector_defaults
        )
        cfg = DetectorConfig(
            sample_rate=self.recorder.sample_rate or self.recorder.requested_rate,
            channels=max(1, self.recorder.channels),
            **defaults,
        )
        # openWakeWord owns idle wake triggering; keep energy/Silero for
        # conversation and dictate (and for whisper-engine wake clips).
        backend = self._vad_backend
        if self._mode == WAKE and self._wake_engine == "openwakeword" and self._openwake:
            backend = "energy"
        detector = make_utterance_detector(
            backend,
            cfg,
            model_path=self._silero_model_path or None,
            allow_download=self._vad_allow_download,
        )
        if (
            backend == "silero"
            and getattr(detector, "backend", "") == "energy"
            and not self._vad_fallback_announced
        ):
            self._vad_fallback_announced = True
            self.status.emit(
                "Silero VAD unavailable — using energy onset (see models/silero)."
            )
        self._detector = detector
        self.trace.record(
            "vad_ready",
            requested=backend,
            **self.debug_state(),
        )

    def _ensure_openwake(self) -> None:
        """Load openWakeWord when configured; leave None to keep Whisper wake."""
        self._openwake = None
        if self._wake_engine != "openwakeword":
            return
        try:
            from arelis.voice.openwake import OpenWakeListener, openwake_available

            if not openwake_available(self._wake_model_path or None):
                log.warning(
                    "openWakeWord engine requested but model/deps missing; "
                    "falling back to whisper wake"
                )
                self._wake_engine = "whisper"
                return
            self._openwake = OpenWakeListener(
                model_path=self._wake_model_path or None,
                threshold=self._wake_threshold,
                cooldown_ms=self._wake_cooldown_ms,
                sample_rate=int(
                    (self.recorder.sample_rate if self.recorder else 0)
                    or 16000
                ),
            )
        except Exception as exc:
            log.warning("openWakeWord failed to load (%s); using whisper wake", exc)
            self._wake_engine = "whisper"
            self._openwake = None

    def _open_mic(self) -> bool:
        if not self.recorder.start():
            return False
        # The recorder settles on the device's real format only after it opens,
        # so the detector is configured from what was actually granted.
        self._apply_detector_for_mode()
        if self._openwake is not None:
            self._openwake.set_device_rate(self.recorder.sample_rate)
        return True

    # --------------------------------------------------------- turn feedback

    def notify_turn_started(self) -> None:
        """A USER_MESSAGE was published, so a turn now exists."""
        self._turn_busy = True
        self._clear_awaiting()
        self.trace.record("turn_started", **self.debug_state())
        self._sync_listening()

    def notify_turn_finished(self) -> None:
        """The turn produced its terminal event.

        Not the same as her being finished. When the answer is spoken, the
        window latches speech before calling this, so listening does not resume
        here; it resumes when the spoken reply also completes.
        """
        self._turn_busy = False
        self._clear_awaiting()
        self.trace.record("turn_finished", **self.debug_state())
        self._sync_listening()

    def notify_utterance_dropped(self) -> None:
        """An utterance was handed off but never became a turn.

        Transcription can come back empty, the dependency can be missing, or
        the clip can fail to reach disk. In every one of those cases no
        USER_MESSAGE is published, so notify_turn_started and
        notify_turn_finished never fire, and conversation mode would sit
        waiting for a turn that does not exist: deaf, dropping every later
        pause as "still working on the last one", until the user toggled it off
        and on again.
        """
        if self._mode != CONVERSATION:
            return
        self._clear_awaiting()
        self.trace.record("utterance_dropped", **self.debug_state())
        self._sync_listening()

    def notify_speaking(self, speaking: bool) -> None:
        """Whether a spoken reply is in flight.

        In flight, not audible. The window raises this when the answer lands and
        lowers it only once synthesis has finished and the player has drained,
        because clips are rendered a sentence at a time and an empty queue
        usually means the next sentence is still in Piper rather than that she
        has stopped talking.
        """
        if speaking == self._speaking:
            return
        self._speaking = speaking
        self.trace.record("speaking", **self.debug_state())
        self._sync_listening()

    def notify_confirm_pending(self, pending: bool) -> None:
        """A confirm card is open (tool write, send, or auto-reply draft).

        Holds conversation listening the same way a busy turn does when the
        card is not in conversation mode, so the mic does not treat a spoken
        "allow" as the next question. Conversation mode keeps the mic on so
        you can allow or deny out loud. Cleared as soon as the card is decided
        or dismissed.
        """
        pending = bool(pending)
        if pending == self._confirm_pending:
            return
        self._confirm_pending = pending
        self.trace.record("confirm_pending", **self.debug_state())
        self._sync_listening(announce=not pending)
        if pending and self._mode == CONVERSATION:
            self.status.emit("Waiting for your confirmation.")

    # ------------------------------------------------------------- listening

    def _wants_listening(self) -> bool:
        if self._mode == OFF:
            return False
        if self._mode != CONVERSATION:
            # Wake and dictation are never held: neither one waits on a turn.
            return True
        if self._speaking:
            return False
        # A card in conversation mode is her asking you — keep the mic on.
        if self._confirm_pending:
            return True
        return not (self._turn_busy or self._awaiting_turn)

    def _sync_listening(self, *, announce: bool = True) -> None:
        """Bring the microphone and the indicator in line with the state."""
        want = self._wants_listening()
        if want == self._listening:
            return
        self._listening = want
        if want and not self._resume_capture():
            # Device went away while we were deaf. Stay in conversation if that
            # toggle is latched — dropping to whisper wake is what "Stopped"
            # felt like after a confirm skip. Wake/dictate can still fall back.
            self._listening = False
            self.listening_changed.emit(False)
            self.trace.record("mic_resume_failed", **self.debug_state())
            if self._mode == CONVERSATION:
                self._mic_retries += 1
                if self._mic_retries <= 3:
                    self.status.emit(
                        "Microphone dropped. Conversation is still on — retrying."
                    )
                    QTimer.singleShot(400, self._retry_conversation_mic)
                else:
                    self.status.emit(
                        "Microphone still unavailable. Toggle conversation to recover."
                    )
                return
            self._mode = OFF
            self.mode_changed.emit(OFF)
            self.start_wake()
            return
        self._mic_retries = 0
        self.trace.record("listening" if want else "held", **self.debug_state())
        self.listening_changed.emit(want)
        if want and announce and self._mode == CONVERSATION:
            self.status.emit("Listening again.")

    def _retry_conversation_mic(self) -> None:
        if self._mode != CONVERSATION:
            return
        self._sync_listening()

    def _resume_capture(self) -> bool:
        """Make the open microphone usable again, or reopen it. False if it failed."""
        if not self.recorder.is_recording():
            return self._open_mic()
        if self._detector.speaking:
            # Mid-utterance (including barge-in). Hold the buffer until
            # speech_ended so a discard flag can trash the whole mixed clip.
            return True
        # Everything captured while deaf is her own voice or room noise, and
        # sending it as the next question is the failure this whole path exists
        # to prevent.
        self.recorder.take()
        self._detector.reset_soft()
        return True

    def _clear_awaiting(self) -> None:
        self._awaiting_turn = False
        self._turn_watchdog.stop()

    def _on_turn_watchdog(self) -> None:
        if not self._awaiting_turn:
            return
        log.warning("Voice: no turn reported for a handed-off utterance; resuming listen")
        self._awaiting_turn = False
        self.trace.record("turn_watchdog", **self.debug_state())
        self._sync_listening()

    # ---------------------------------------------------------- audio blocks

    def _on_frames(self, block: bytes) -> None:
        if self._mode == OFF:
            return
        # Idle openWakeWord: score continuously; never queue Whisper on ambient.
        if (
            self._mode == WAKE
            and self._wake_engine == "openwakeword"
            and self._openwake is not None
        ):
            try:
                hit = self._openwake.feed(block, channels=self.recorder.channels)
            except Exception:
                log.exception("openWakeWord feed failed")
                hit = False
            if hit:
                self.trace.record_wake(
                    "wake_heard",
                    matched=True,
                    engine="openwakeword",
                    score=getattr(self._openwake, "last_score", None),
                    **self.debug_state(),
                )
                self.recorder.take()
                self._detector.reset_soft()
                self.utterance.emit(
                    b"",
                    self.recorder.sample_rate,
                    self.recorder.channels,
                    "wake_oww",
                )
            return
        event = self._detector.feed(block)
        if event is None:
            return
        if event == STARTED:
            self._on_speech_started()
        elif event in (ENDED, TIMEOUT):
            self._on_speech_ended(timed_out=event == TIMEOUT)

    def _on_speech_started(self) -> None:
        # Wake only: drop pre-onset silence so Whisper is not fed minutes of
        # ambient buffer. Conversation keeps full onset (hot-swap already
        # cleared the buffer on mode enter).
        if self._mode == WAKE:
            self.recorder.keep_last_ms(350)
        prob = getattr(self._detector, "last_speech_prob", None)
        self.trace.record(
            "speech_start",
            prob=None if prob is None else round(float(prob), 3),
            **self.debug_state(),
        )
        if self._mode == CONVERSATION and self._speaking and self._barge_in_enabled:
            # Existing barge-in: she stops talking now. The window cuts
            # playback. This clip is still soup (her voice in the mic), so it
            # must not become a turn — mark it so speech_ended hears stop /
            # allow / deny only.
            self._discard_barge_clip = True
            self.barge_in.emit()
        if (
            self._speculate_preflight
            and self._mode == CONVERSATION
            and self._listening
            and not self._speculate_armed
        ):
            self._speculate_armed = True
            self._speculate_timer.start(1600)

    def _on_speculate_tick(self) -> None:
        """Peek the live buffer once; UI may STT it without ending the utterance."""
        if self._mode != CONVERSATION or not self._listening:
            return
        if not self._detector.speaking:
            return
        pcm = self.recorder.peek()
        if self._too_short(pcm, 0.8):
            return
        self.trace.record("speculate_peek", seconds=self._seconds(pcm), **self.debug_state())
        self.provisional.emit(pcm, self.recorder.sample_rate, self.recorder.channels)

    def _on_speech_ended(self, *, timed_out: bool) -> None:
        self._speculate_timer.stop()
        self._speculate_armed = False
        pcm = self.recorder.take()
        self._detector.reset()
        # Trailing end-point silence is useful for VAD. Keep enough pad that
        # Whisper still sees the last consonant (keep_ms=80 ate "hobbies").
        pcm = trim_trailing_silence(
            pcm,
            sample_rate=self.recorder.sample_rate,
            channels=self.recorder.channels,
            keep_ms=400,
        )
        mode = self._mode
        prob = getattr(self._detector, "last_speech_prob", None)
        self.trace.record(
            "speech_end",
            timed_out=timed_out,
            seconds=self._seconds(pcm),
            prob=None if prob is None else round(float(prob), 3),
            silence_ms=self._detector.required_silence_ms(),
            **self.debug_state(),
        )
        if timed_out and mode != WAKE:
            self.status.emit("That was a long one. Sending what I have.")

        if mode in (DICTATE, WAKE):
            # Keep listening. For dictation the pause was a breath, not the end;
            # for wake, clips are filtered after transcription.
            self._emit_utterance(pcm, mode)
            return
        if mode != CONVERSATION:
            return

        if self._discard_barge_clip:
            self._discard_barge_clip = False
            if self._speaking:
                # Speech started while she was talking, but playback was never
                # cut. That is her own voice coming back through the speakers,
                # not someone talking over her. STT on it would hear her "yes"
                # or "stop" as a decision.
                self.trace.record("echo_discarded", **self.debug_state())
                return
            # Same barge-in utterance. She is already cut. Hear a speech act
            # on this clip; do not start a question from the mix.
            self.trace.record("barge_control", **self.debug_state())
            self._emit_control(pcm)
            return

        if not self._listening:
            if self._speaking:
                # Her own voice arriving back through the speakers. Silent: the
                # user did nothing and does not need telling about it.
                self.trace.record("echo_discarded", **self.debug_state())
            else:
                # Mid-turn: hear stop / allow / deny. Anything else is dropped
                # after STT so Discord bleed does not queue a second ask.
                self.trace.record("mid_turn_control", **self.debug_state())
                self._emit_control(pcm)
            return

        if self._too_short(pcm, _MIN_UTTERANCE_S):
            return
        self._awaiting_turn = True
        self._turn_watchdog.start(_AWAITING_TURN_TIMEOUT_MS)
        self._sync_listening()
        self.utterance.emit(pcm, self.recorder.sample_rate, self.recorder.channels, "turn")

    def _emit_utterance(self, pcm: bytes, mode: str) -> None:
        minimum = _MIN_WAKE_UTTERANCE_S if mode == WAKE else _MIN_UTTERANCE_S
        if self._too_short(pcm, minimum):
            return
        deliver = "wake" if mode == WAKE else "dictate"
        self.utterance.emit(pcm, self.recorder.sample_rate, self.recorder.channels, deliver)

    def _emit_control(self, pcm: bytes) -> None:
        """STT for a barge-in or mid-turn clip. Not a new ask.

        Barge-in already cut her. This only lets stop / allow / deny on that
        same clip reach the orchestrator. Mid-turn (she is working, not
        talking) uses the same deliver so spoken stop still lands.
        """
        if self._too_short(pcm, _MIN_UTTERANCE_S):
            return
        self.utterance.emit(pcm, self.recorder.sample_rate, self.recorder.channels, "control")

    def _too_short(self, pcm: bytes, minimum: float) -> bool:
        return self._seconds(pcm) < minimum

    def _seconds(self, pcm: bytes) -> float:
        return duration_seconds(
            pcm, sample_rate=self.recorder.sample_rate, channels=self.recorder.channels
        )
