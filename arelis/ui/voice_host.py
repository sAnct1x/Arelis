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
    window._speech_watchdog.timeout.connect(window._on_speech_watchdog)
    window.utterance_settled.connect(window._on_utterance_settled)
    window.wake_detected.connect(window._on_wake_detected)
    if window.voice is None:
        window.conversation.set_voice_available(False, "")
        return

    if window.voice.stt_enabled:
        controller = VoiceController(window.config, window)
        problem = controller.problem()
        window.conversation.set_voice_available(problem is None, problem or "")
        if problem is None:
            window.voice_controller = controller
            controller.utterance.connect(window._on_utterance)
            controller.provisional.connect(window._on_provisional_pcm)
            controller.live_started.connect(window._on_live_started)
            controller.live_pcm.connect(window._on_live_pcm)
            controller.status.connect(window._on_voice_status)
            controller.failed.connect(window._on_capture_failed)
            controller.mode_changed.connect(window._on_voice_mode)
            controller.barge_in.connect(window._on_barge_in)
            window._provisional_intent = None
            window.conversation.dictate_toggled.connect(controller.set_dictate)
            window.conversation.conversation_toggled.connect(controller.set_conversation)
            # Always-listen for Hey Arelis until dictate or conversation takes the mic.
            controller.start_wake()
            window._preload_voice()
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
            player.started.connect(lambda: window._on_playback(True))
            player.finished.connect(lambda: window._on_playback(False))
            player.failed.connect(window._on_playback_failed)

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
        lambda fut, gen=generation: window._provisional_resolved(fut, gen)
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
        window._invalidate_wake()
        window._invalidate_provisional()
        future = asyncio.run_coroutine_threadsafe(
            window.voice.finish_live_stt(deliver=deliver, strip_wake=peel),
            window.loop,
        )
        future.add_done_callback(window._utterance_resolved)
        return
    target = outputs_dir() / "voice" / f"capture_{uuid4().hex[:8]}.wav"
    try:
        write_wav(target, pcm, sample_rate=rate, channels=channels)
    except OSError as exc:
        window.chat.add_system(
            f"I could not save the recording. {plain_reason(exc)}"
        )
        window.thinking.append(f"capture write failed: {exc!r}", kind="status")
        window._on_utterance_settled(False)
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
            lambda fut, gen=generation: window._wake_resolved(fut, gen)
        )
        return
    if deliver != "dictate":
        window.thinking.append("transcribing", kind="status")
    # Conversation/dictate take priority: invalidate any wake or provisional
    # peek still queued on the STT lock so Whisper serves the real clip.
    window._invalidate_wake()
    window._invalidate_provisional()
    peel = bool(window._peel_wake_next and deliver == "turn")
    if peel:
        window._peel_wake_next = False
    future = asyncio.run_coroutine_threadsafe(
        window.voice.ingest_audio(
            str(target), deliver=deliver, strip_wake=peel
        ),
        window.loop,
    )
    future.add_done_callback(window._utterance_resolved)

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

def on_wake_detected(window, remainder: object) -> None:
    """Wake phrase matched. Enter conversation; send remainder if any."""
    window._note_engagement()
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

def preload_voice(window) -> None:
    """Warm Whisper once the asyncio loop is actually running."""
    if window.voice is None or not window.loop.is_running():
        return
    asyncio.run_coroutine_threadsafe(window.voice.preload(), window.loop)

def on_voice_mode(window, mode: str) -> None:
    window.conversation.set_dictating(mode == "dictate")
    window.conversation.set_conversing(mode == "conversation")
    window._sync_idle_voice_mode(mode)
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
        window._invalidate_wake()
        window._invalidate_provisional()
    if mode not in {"off", ""}:
        # Loading Whisper takes tens of seconds the first time. Starting it
        # now means it happens while the user is still talking instead of
        # after they stop.
        window._preload_voice()
    if mode != "conversation":
        window._stop_speech()

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
    window._stop_speech()

def on_barge_in(window) -> None:
    """Talking over her. Cut playback now.

    Headset: the same clip is the next turn. Speakers with barge_in_as_turn
    false: control only (stop / allow / deny). This is the interrupt;
    the transcript is not a second one.
    """
    window.thinking.append("interrupted", kind="status")
    window._stop_speech()

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
    window._trace_voice("speech_armed")
    window._update_speaking()

def on_speech_synthesized(window, clips: int) -> None:
    """VOICE_SPEECH_DONE: no more clips are coming for this reply."""
    window._speech_expected = False
    window._trace_voice("speech_synthesized", clips=clips)
    window._update_speaking()

def on_playback(window, playing: bool) -> None:
    window._speech_playing = playing
    window._trace_voice("playback")
    window._update_speaking()

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
        window._flush_held_inbound()

def on_speech_watchdog(window) -> None:
    player_busy = window.speech_player is not None and window.speech_player.has_work()
    stuck = window._speech_expected or window._speech_playing or player_busy
    if not stuck:
        # Resync in case speaking was latched from a stale has_work read.
        window._update_speaking()
        return
    window.thinking.append("speech never reported finishing; listening again", kind="status")
    window._stop_speech()

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
    window._update_speaking()

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
