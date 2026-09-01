"""Voice attach and speech latch. ArelisWindow methods stay as delegates.

The window still owns the widgets and the Qt signals. This module is the
microphone / speaker wiring: build, wake, utterance, and the speak latch
that keeps the mic closed while a reply is in flight. Engines stay in
arelis.voice; this is only the glass side.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QTimer

from arelis.core.events import Event, EventType
from arelis.core.failure_copy import plain_reason
from arelis.paths import outputs_dir
from arelis.ui.audio import SpeechPlayer
from arelis.ui.event_host import SPEECH_WATCHDOG_MS
from arelis.ui.voice_control import VoiceController
from arelis.voice.pcm import write_wav
from arelis.voice.wake import WakeResult, classify_wake, looks_like_wake_attempt


def voice_restart_notices(
    *,
    listen_wanted: bool,
    listen_live: bool,
    speak_wanted: bool,
    speak_live: bool,
) -> list[str]:
    """One line per direction the running voice service cannot follow.

    VoiceService reads both directions once, at construction, and only wires
    itself to the speech events when speak was on at the time. Everything after
    that is a setting the service never sees: Speak turned on later stays
    silent, Speak turned off later still talks, and Listen turned on later
    answers every utterance with "voice input is off". The switch moves, the
    behaviour does not, and until now nothing said so.
    """
    notices: list[str] = []
    for label, wanted, live in (
        ("Listen", listen_wanted, listen_live),
        ("Speak", speak_wanted, speak_live),
    ):
        if wanted == live:
            continue
        state = "on" if wanted else "off"
        notices.append(
            f"Restart Arelis to finish turning {label} {state} — "
            f"the running voice service still has it {'off' if wanted else 'on'}."
        )
    return notices


def build_voice(window) -> None:
    """Attach the microphone and the speaker, if voice is switched on.

    Each direction is independent. With voice off entirely the controls are
    hidden and none of this is constructed, which is what keeps a machine
    with no sound hardware behaving exactly as it does today.
    """
    window.voice_controller: VoiceController | None = None
    window.speech_player: SpeechPlayer | None = None
    window._voice_ear_ready = True
    window._voice_preload_future = None
    # Wake STT is single-flight: ambient clips must not queue on the Whisper
    # lock ahead of conversation/dictate turns.
    window._wake_inflight = False
    window._wake_generation = 0
    # Mid-utterance provisional STT must not hold Whisper past speech-end.
    window._prov_generation = 0
    window._live_stt_active = False
    window._peel_wake_next = False
    # A spoken reply is in flight from the moment the answer lands until
    # synthesis has finished and the player has drained. Both halves are
    # needed. Waiting only for the player reopens the microphone in the gap
    # between two sentences, because clips are rendered one at a time and an
    # empty queue usually means the next one is still in Piper. Waiting only
    # for synthesis reopens it while the last clip is still playing.
    window._speech_expected = False
    window._speech_playing = False
    window._speech_watchdog = QTimer(window)
    window._speech_watchdog.setSingleShot(True)
    window._speech_watchdog.timeout.connect(lambda: on_speech_watchdog(window))
    window.utterance_settled.connect(
        lambda became_turn: on_utterance_settled(window, became_turn)
    )
    window.wake_detected.connect(lambda remainder: on_wake_detected(window, remainder))
    if window.voice is None:
        window.conversation.set_voice_available(False, "")
        return

    if window.voice.stt_enabled:
        controller = VoiceController(window.config, window)
        problem = controller.problem()
        window.conversation.set_voice_available(problem is None, problem or "")
        if problem is None:
            window.voice_controller = controller
            controller.utterance.connect(
                lambda pcm, rate, channels, deliver: on_utterance(
                    window, pcm, rate, channels, deliver
                )
            )
            controller.provisional.connect(
                lambda pcm, rate, channels: on_provisional_pcm(
                    window, pcm, rate, channels
                )
            )
            controller.live_started.connect(lambda: on_live_started(window))
            controller.live_pcm.connect(
                lambda pcm, rate, channels: on_live_pcm(window, pcm, rate, channels)
            )
            controller.status.connect(lambda message: on_voice_status(window, message))
            controller.failed.connect(lambda message: on_capture_failed(window, message))
            controller.mode_changed.connect(lambda mode: on_voice_mode(window, mode))
            controller.barge_in.connect(lambda: on_barge_in(window))
            window._provisional_intent = None
            window.conversation.dictate_toggled.connect(controller.set_dictate)
            window.conversation.conversation_toggled.connect(controller.set_conversation)
            # Do not claim "say hey arelis" until the ear is actually loaded.
            # First wake into a cold Whisper download looks like a dead mic.
            window._voice_ear_ready = False
            _mark_voice_preparing(window, True)
            preload_voice(window)
            if window._voice_preload_future is None:
                # Loop is not running (tests, or a launch that has not
                # started it). Do not leave the glass stuck on getting the ear.
                window._voice_ear_ready = True
                _mark_voice_preparing(window, False)
                controller.start_wake()
    else:
        window.conversation.set_voice_available(False, "")

    if window.voice.tts_enabled:
        player = SpeechPlayer(window)
        if player.available():
            voice_cfg = window.config.get("voice") or {}
            player.set_output_device(str(voice_cfg.get("output_device") or ""))
            try:
                player.set_volume(float(voice_cfg.get("output_volume", 1.0)))
            except (TypeError, ValueError):
                player.set_volume(1.0)
            window.speech_player = player
            player.started.connect(lambda: on_playback(window, True))
            player.finished.connect(lambda: on_playback(window, False))
            player.failed.connect(lambda message: on_playback_failed(window, message))

# ------------------------------------------------------------------ voice

def on_provisional_pcm(window, pcm: bytes, rate: int, channels: int) -> None:
    """Mid-utterance peek: STT for weather/SMS intent only (no turn start)."""
    if window.voice is None or not bool(
        (window.config.get("agent") or {}).get("voice_speculate_preflight", True)
    ):
        return
    target = outputs_dir() / "voice" / f"prov_{uuid4().hex[:8]}.wav"
    try:
        write_wav(target, pcm, sample_rate=rate, channels=channels)
    except OSError:
        return
    generation = window._prov_generation
    future = asyncio.run_coroutine_threadsafe(
        ingest_provisional(window, str(target), generation),
        window.loop,
    )
    future.add_done_callback(
        lambda fut, gen=generation: provisional_resolved(window, fut, gen)
    )

async def ingest_provisional(window, path: str, generation: int) -> str:
    from arelis.voice.speculate import provisional_intents

    if window.voice is None:
        return ""
    text = await window.voice.ingest_audio(
        path,
        deliver="wake",
        proceed=lambda: generation == window._prov_generation,
    )
    if generation != window._prov_generation:
        return ""
    intent = provisional_intents(text or "")
    if intent is None:
        return ""
    window._provisional_intent = intent
    await window.bus.publish(
        Event(EventType.STATUS, {"message": intent.summary})
    )
    return intent.summary

def provisional_resolved(window, future, generation: int) -> None:
    try:
        summary = future.result()
    except Exception:
        return
    if generation != window._prov_generation:
        return
    if summary:
        try:
            window.thinking.append(str(summary), kind="status")
        except RuntimeError:
            pass

def on_utterance(window, pcm: bytes, rate: int, channels: int, deliver: str) -> None:
    """Hand a recorded utterance to the async side.

    The WAV is written here, on the Qt thread, because it is a couple of
    megabytes at most and because the async side must never reach back into
    Qt for the buffer. Everything after this point is the bus's problem:
    the coroutine transcribes off-thread and publishes a transcript, and a
    failure there reports itself rather than stranding a turn.
    """
    if deliver == "wake_oww":
        # Dedicated wake engine already matched — skip Whisper entirely.
        # Remainder of the clip (still in the mic buffer) is the first turn.
        window._peel_wake_next = True
        window.wake_detected.emit("")
        return
    if window.voice is None:
        return
    if window._live_stt_active:
        window._live_stt_active = False
        peel = bool(window._peel_wake_next and deliver == "turn")
        if peel:
            window._peel_wake_next = False
        if deliver != "dictate":
            window.thinking.append("transcribing", kind="status")
        invalidate_wake(window)
        invalidate_provisional(window)
        future = asyncio.run_coroutine_threadsafe(
            window.voice.finish_live_stt(deliver=deliver, strip_wake=peel),
            window.loop,
        )
        future.add_done_callback(lambda fut: utterance_resolved(window, fut))
        return
    target = outputs_dir() / "voice" / f"capture_{uuid4().hex[:8]}.wav"
    try:
        write_wav(target, pcm, sample_rate=rate, channels=channels)
    except OSError as exc:
        window.chat.add_system(
            f"I could not save the recording. {plain_reason(exc)}"
        )
        window.thinking.append(f"capture write failed: {exc!r}", kind="status")
        on_utterance_settled(window, False)
        return
    if deliver == "wake":
        if window._wake_inflight:
            # Drop the clip rather than queue Whisper behind the last one.
            ctrl = window.voice_controller
            if ctrl is not None:
                ctrl.trace.record_wake(
                    "wake_drop",
                    reason="inflight",
                    engine="whisper",
                    **ctrl.debug_state(),
                )
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
            return
        window._wake_inflight = True
        generation = window._wake_generation
        future = asyncio.run_coroutine_threadsafe(
            ingest_wake(window, str(target), generation),
            window.loop,
        )
        future.add_done_callback(
            lambda fut, gen=generation: wake_resolved(window, fut, gen)
        )
        return
    if deliver != "dictate":
        window.thinking.append("transcribing", kind="status")
    # Conversation/dictate take priority: invalidate any wake or provisional
    # peek still queued on the STT lock so Whisper serves the real clip.
    invalidate_wake(window)
    invalidate_provisional(window)
    peel = bool(window._peel_wake_next and deliver == "turn")
    if peel:
        window._peel_wake_next = False
    future = asyncio.run_coroutine_threadsafe(
        window.voice.ingest_audio(
            str(target), deliver=deliver, strip_wake=peel
        ),
        window.loop,
    )
    future.add_done_callback(lambda fut: utterance_resolved(window, fut))

def on_live_started(window) -> None:
    """Conversation/dictate onset: feed Sherpa while they talk, if the pack is ready."""
    if window.voice is None:
        window._live_stt_active = False
        return
    window._live_stt_active = window.voice.start_live_stt()

def on_live_pcm(window, pcm: bytes, rate: int, channels: int) -> None:
    if window.voice is None or not window._live_stt_active or not pcm:
        return
    window.voice.feed_live_stt(pcm, rate, channels)

def invalidate_wake(window) -> None:
    window._wake_generation += 1
    window._wake_inflight = False

def invalidate_provisional(window) -> None:
    window._prov_generation += 1
    window._provisional_intent = None

async def ingest_wake(window, path: str, generation: int) -> WakeResult | None:
    """Transcribe an idle clip; return wake classification (or None if superseded)."""
    if window.voice is None:
        return None
    text = await window.voice.ingest_audio(
        path,
        deliver="wake",
        proceed=lambda: generation == window._wake_generation,
    )
    if generation != window._wake_generation:
        return None
    return classify_wake(text or "")

def wake_resolved(window, future, generation: int) -> None:
    try:
        result = future.result()
    except Exception:
        result = None
    if generation == window._wake_generation:
        window._wake_inflight = False
    if not isinstance(result, WakeResult):
        return
    if generation != window._wake_generation:
        return
    # Trace what Whisper heard so silent misses are diagnosable.
    ctrl = window.voice_controller
    if ctrl is not None:
        ctrl.trace.record_wake(
            "wake_heard",
            matched=result.matched,
            engine="whisper",
            heard=(result.heard or "")[:80],
            remainder=(result.remainder or "")[:80],
            **ctrl.debug_state(),
        )
    try:
        if result.matched:
            window.wake_detected.emit(result.remainder)
        elif _idle_control_heard(window, result.heard):
            asyncio.run_coroutine_threadsafe(
                window.bus.publish(
                    Event(
                        EventType.VOICE_TRANSCRIPT,
                        {"text": result.heard, "deliver": "control"},
                    )
                ),
                window.loop,
            )
        elif result.heard and looks_like_wake_attempt(result.heard):
            # Near-miss: name-ish but regex still failed — tell the operator.
            snippet = result.heard.strip()
            if len(snippet) > 60:
                snippet = snippet[:57] + "…"
            window.thinking.append(
                f'heard “{snippet}” — say “Hey Arelis” to wake',
                kind="status",
            )
    except RuntimeError:
        pass


def _idle_control_heard(window, heard: object) -> bool:
    """True when wake missed but she is mid-turn / armed and this is stop / yes / pause."""
    from arelis.core.confirm_speech import classify_drive_act, classify_voice_act

    text = str(heard or "").strip()
    if not text:
        return False
    if classify_voice_act(text) is None and classify_drive_act(text) is None:
        return False
    if getattr(window, "_turn_busy", False):
        return True
    conv = getattr(window, "conversation", None)
    if conv is not None and conv.confirm_open():
        return True
    return bool(getattr(window, "_drive_session", False))


def on_wake_detected(window, remainder: object) -> None:
    """Wake phrase matched. Enter conversation; send remainder if any."""
    from arelis.ui.idle_host import note_engagement

    note_engagement(window)
    if remainder is None or window.voice_controller is None:
        return
    # Empty string is a valid match (wake-only utterance).
    if not isinstance(remainder, str):
        remainder = str(remainder)
    text = remainder.strip()
    if window.voice is not None:
        window.voice.speak_enabled = True
    window.config["_speak_replies"] = True
    # Sync the two-arcs toggle without re-emitting a false leave.
    btn = window.conversation.conversation_btn
    btn.blockSignals(True)
    btn.setChecked(True)
    btn.blockSignals(False)
    window.conversation.set_conversing(True)
    window.voice_controller.set_conversation(True)
    if window.voice is not None:
        window.voice.speak_enabled = True
    window.conversation.ack_wake()
    window.voice_controller.trace.record_wake(
        "wake_ack",
        engine=getattr(window.voice_controller, "_wake_engine", ""),
        remainder=text[:80],
        **window.voice_controller.debug_state(),
    )
    window.thinking.append("Wake heard — listening.", kind="status")
    if not text:
        return
    # Remainder that is only another wake / punctuation was already peeled.
    asyncio.run_coroutine_threadsafe(
        window.bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": text})),
        window.loop,
    )

def utterance_resolved(window, future) -> None:
    """Report back whether the recording produced anything. Async thread."""
    try:
        became_turn = bool(future.result())
    except Exception:
        became_turn = False
    try:
        window.utterance_settled.emit(became_turn)
    except RuntimeError:
        # The window went away while transcription was still running.
        pass

def on_utterance_settled(window, became_turn: bool) -> None:
    if became_turn or window.voice_controller is None:
        return
    # No turn will start, so no terminal event is coming. Conversation mode
    # has to be told, or it waits for one forever and stops listening.
    window.voice_controller.notify_utterance_dropped()

def _mark_voice_preparing(window, on: bool) -> None:
    idle = getattr(window.conversation.chat, "empty", None)
    if idle is not None and hasattr(idle, "set_voice_preparing"):
        idle.set_voice_preparing(on)
    from arelis.ui.idle_host import sync_idle_voice_mode

    sync_idle_voice_mode(window)


def preload_voice(window) -> None:
    """Warm the ear once the asyncio loop is actually running.

    Wake stays off until this finishes, so the idle line is not still
    promising Hey Arelis while Whisper downloads with no status.
    """
    if window.voice is None or not window.loop.is_running():
        return
    if getattr(window, "_voice_preload_future", None) is not None:
        return
    future = asyncio.run_coroutine_threadsafe(window.voice.preload(), window.loop)
    window._voice_preload_future = future

    def _done(fut) -> None:
        try:
            on_voice_ear_ready(window, fut)
        except RuntimeError:
            pass

    future.add_done_callback(
        lambda fut: QTimer.singleShot(0, lambda: _done(fut))
    )


def on_voice_ear_ready(window, future) -> None:
    """Idle may say Hey Arelis now. Fail-soft: a dead preload still starts wake."""
    window._voice_ear_ready = True
    _mark_voice_preparing(window, False)
    try:
        future.result()
    except Exception as exc:
        window.thinking.append(f"Could not get the ear: {exc}", kind="status")
    if window.voice_controller is not None:
        window.voice_controller.start_wake()
    from arelis.ui.idle_host import sync_idle_voice_mode

    sync_idle_voice_mode(window)

def on_voice_mode(window, mode: str) -> None:
    window.conversation.set_dictating(mode == "dictate")
    window.conversation.set_conversing(mode == "conversation")
    from arelis.ui.idle_host import sync_idle_voice_mode

    sync_idle_voice_mode(window, mode)
    if window.voice is not None:
        window.voice.speak_enabled = mode == "conversation"
    # Agent loop reads this to bias spoken answers toward brevity.
    window.config["_speak_replies"] = mode == "conversation"
    if mode not in {"conversation", "dictate"}:
        window._live_stt_active = False
        window._peel_wake_next = False
        if window.voice is not None:
            window.voice.abort_live_stt()
    if mode in {"dictate", "conversation"}:
        # Drop superseding wake/provisional jobs so they do not hold STT.
        invalidate_wake(window)
        invalidate_provisional(window)
    if mode not in {"off", ""}:
        # Loading Whisper takes tens of seconds the first time. Starting it
        # now means it happens while the user is still talking instead of
        # after they stop.
        preload_voice(window)
    if mode != "conversation":
        stop_speech(window)

def on_voice_status(window, message: str) -> None:
    window.thinking.append(message, kind="status")

def on_capture_failed(window, message: str) -> None:
    """The microphone side failed, so leave the mode rather than fake it.

    Unchecking the buttons alone used to be a lie: the controller stayed in
    conversation mode holding the device open while the composer showed
    voice as off.
    """
    window.chat.add_system(message)
    window.thinking.append(message, kind="status")
    if window.voice is not None:
        window.voice.speak_enabled = False
    if window.voice_controller is not None:
        window.voice_controller.stop_all()
    window.conversation.set_dictating(False)
    window.conversation.set_conversing(False)

def on_playback_failed(window, message: str) -> None:
    """A clip failed to play — abandon speech so conversation can listen again."""
    window.thinking.append(f"playback: {message}", kind="status")
    stop_speech(window)

def on_barge_in(window) -> None:
    """Talking over her. Cut playback now.

    Headset: the same clip is the next turn. Speakers with barge_in_as_turn
    false: control only (stop / allow / deny). This is the interrupt;
    the transcript is not a second one.
    """
    window.thinking.append("interrupted", kind="status")
    stop_speech(window)

def arm_speech(window) -> None:
    """A spoken reply is in flight (or about to be).

    Armed on ASSISTANT_DONE.speak and on the first VOICE_AUDIO_READY.
    Streaming TTS can produce a clip before the turn ends; arming on the
    first clip covers that. Arming on DONE covers the gap where Piper is
    still rendering and nothing is playing yet, which used to read as
    "she has finished" and reopen the microphone in time to record her
    own opening words.
    """
    if window.voice is None or not window.voice.tts_enabled or not window.voice.speak_enabled:
        return
    if window._speech_expected:
        return
    window._speech_expected = True
    trace_voice(window, "speech_armed")
    update_speaking(window)

def on_speech_synthesized(window, clips: int) -> None:
    """VOICE_SPEECH_DONE: no more clips are coming for this reply."""
    window._speech_expected = False
    trace_voice(window, "speech_synthesized", clips=clips)
    update_speaking(window)

def on_playback(window, playing: bool) -> None:
    window._speech_playing = playing
    trace_voice(window, "playback")
    update_speaking(window)

def update_speaking(window) -> None:
    # Include the player queue so VOICE_SPEECH_DONE cannot reopen the mic in
    # the gap between "synthesis finished" and "first clip starts playing".
    player_busy = window._speech_playing or (
        window.speech_player is not None and window.speech_player.has_work()
    )
    speaking = window._speech_expected or player_busy
    if speaking:
        window._speech_watchdog.start(SPEECH_WATCHDOG_MS)
    else:
        window._speech_watchdog.stop()
    window.conversation.set_speaking(speaking)
    if window.voice_controller is not None:
        window.voice_controller.notify_speaking(speaking)
    if not speaking:
        from arelis.ui.sms_host import flush_held_inbound

        flush_held_inbound(window)

def on_speech_watchdog(window) -> None:
    player_busy = window.speech_player is not None and window.speech_player.has_work()
    stuck = window._speech_expected or window._speech_playing or player_busy
    if not stuck:
        # Resync in case speaking was latched from a stale has_work read.
        update_speaking(window)
        return
    window.thinking.append("speech never reported finishing; listening again", kind="status")
    stop_speech(window)

def stop_speech(window) -> None:
    # Cancelling synthesis matters as much as stopping the player. The
    # player drops the clips it holds, but the service would keep rendering
    # the rest of the answer, and conversation mode stays deaf until that
    # loop reaches its terminal event.
    if window.voice is not None:
        window.voice.cancel_speech()
    if window.speech_player is not None:
        window.speech_player.stop()
    window._speech_expected = False
    window._speech_playing = False
    update_speaking(window)

def trace_voice(window, event: str, **fields: Any) -> None:
    if window.voice_controller is None:
        return
    window.voice_controller.trace.record(
        event,
        expect=window._speech_expected,
        playing=window._speech_playing,
        **fields,
        **window.voice_controller.debug_state(),
    )
