from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arelis.config import PROJECT_ROOT
from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.turn_telemetry import log_span, turn_telemetry_enabled
from arelis.voice.speech_text import (
    next_speakable_units,
    prepare_spoken_text,
    split_sentences,
)
from arelis.voice.stt import SpeechToText
from arelis.voice.tts import TextToSpeech
from arelis.voice.wake import match_wake

log = logging.getLogger(__name__)

# Synthesized clips accumulate one per sentence, so the directory is pruned
# rather than left to grow for the life of the install.
_KEEP_CLIPS = 24


def stt_enabled(config: dict[str, Any]) -> bool:
    """True when speech input should be offered at all.

    voice.enabled is the master switch and each direction has its own toggle
    under it, so the mic can work with playback off and the other way round.
    Both sub-toggles default to true: turning voice on and getting neither
    direction would be the more surprising default.
    """
    voice = config.get("voice", {})
    return bool(voice.get("enabled")) and bool(voice.get("stt", {}).get("enabled", True))


def tts_enabled(config: dict[str, Any]) -> bool:
    voice = config.get("voice", {})
    return bool(voice.get("enabled")) and bool(voice.get("tts", {}).get("enabled", True))


class VoiceService:
    """Wires STT and TTS to the event bus.

    Both directions are event driven and neither touches an audio device. The
    device side lives on the Qt thread in arelis.ui.audio, hands a recorded WAV
    to ingest_audio, and plays whatever VOICE_AUDIO_READY points at. That split
    is deliberate: Qt owns audio, the bus owns coordination.

    Spoken replies stream from ASSISTANT_DELTA: each completed sentence is
    synthesized as soon as it is stable, so audio can start while the answer is
    still growing. VOICE_SPEAK remains the terminal hand-off (flush +
    VOICE_SPEECH_DONE) and the path for non-stream producers such as SMS cues.
    """

    def __init__(self, bus: EventBus, config: dict[str, Any]) -> None:
        self.bus = bus
        self.config = config
        self.enabled = bool(config.get("voice", {}).get("enabled"))
        self.stt_enabled = stt_enabled(config)
        self.tts_enabled = tts_enabled(config)
        self.stt = SpeechToText(config)
        self.tts = TextToSpeech(config)
        tts_cfg = config.get("voice", {}).get("tts", {})
        # 0 means no limit. Length is handled by letting the user interrupt,
        # not by cutting the answer; this stays as a runaway guard only.
        self.max_spoken_chars = int(tts_cfg.get("max_chars", 0) or 0)
        self.keep_recordings = bool(config.get("voice", {}).get("keep_recordings", False))
        # Spoken replies are for conversation mode only. Typed chat and
        # dictation stay text-only; the window flips this when the two-arcs
        # toggle (or the wake word) enters conversation.
        self.speak_enabled = False
        self._speak_seq = 0
        self._speak_cancelled = 0
        self._speak_lock = asyncio.Lock()
        # The bus dispatches handlers concurrently, so delta/retract/speak must
        # not race on the stream buffer even though Piper itself is serialized
        # under _speak_lock.
        self._stream_lock = asyncio.Lock()
        self._out_dir = PROJECT_ROOT / "outputs" / "voice"
        # Live answer buffer for streaming TTS. Cleared on retract / speak done.
        self._stream_raw = ""
        self._spoken_count = 0
        self._stream_utterance = 0
        self._stream_clips = 0
        self._stream_open = False
        self._pending: list[tuple[str, bool]] = []
        self._drain_task: asyncio.Task[None] | None = None
        if self.tts_enabled:
            bus.subscribe(EventType.ASSISTANT_DELTA, self.on_delta)
            bus.subscribe(EventType.ASSISTANT_RETRACT, self.on_retract)
            bus.subscribe(EventType.VOICE_SPEAK, self.on_speak)
            bus.subscribe(EventType.ERROR, self.on_turn_error)

    # ---------------------------------------------------------------- output

    def cancel_speech(self) -> None:
        """Abandon the reply being synthesized, at the next sentence boundary.

        Cutting playback alone is not enough. The player drops the clips it
        already holds, but this loop keeps rendering the rest of the answer, and
        every one of those sentences delays the terminal event conversation mode
        is waiting on before it reopens the microphone. On a ten sentence answer
        that is the difference between resuming now and resuming in ten seconds.

        Safe to call from the Qt thread: it stores an int the coroutine reads
        between sentences, so there is nothing to await and no lock to take.
        """
        self._speak_cancelled = self._speak_seq
        self._pending.clear()

    async def on_delta(self, event: Event) -> None:
        """Queue completed sentences from a live answer for synthesis.

        Returns after only a short critical section. Piper runs on a background
        drain task so a slow sentence does not stall later deltas (or the chat
        paint that shares the bus dispatch).
        """
        if not self.tts_enabled or not self.speak_enabled:
            return
        chunk = event.payload.get("text") or ""
        if not chunk:
            return
        async with self._stream_lock:
            self._stream_raw += chunk
            self._queue_from_buffer(finalize=False)
            self._ensure_drain()

    async def on_retract(self, event: Event) -> None:
        """Drop streamed speech when the painted answer was only a preamble."""
        async with self._stream_lock:
            if not self.tts_enabled or not self.speak_enabled:
                self._reset_stream(keep_cancel=False)
                return
            was_open = self._stream_open
            utterance = self._stream_utterance
            clips = self._stream_clips
            self.cancel_speech()
        await self._await_drain()
        async with self._stream_lock:
            self._reset_stream(keep_cancel=True)
        if was_open:
            # Conversation mode may already have armed on the first clip. Close
            # the speak cycle even when cancel left nothing more to render.
            self.bus.publish_nowait(
                Event(
                    EventType.VOICE_SPEECH_DONE,
                    {"utterance": utterance, "clips": clips},
                )
            )

    async def on_turn_error(self, event: Event) -> None:
        """A failed turn never reaches VOICE_SPEAK; close any open speak cycle."""
        if event.payload.get("scope") == "voice":
            return
        async with self._stream_lock:
            open_stream = self._stream_open
        if not open_stream:
            async with self._stream_lock:
                self._reset_stream(keep_cancel=False)
            return
        await self.on_retract(event)

    async def on_speak(self, event: Event) -> None:
        """Finish (or fully speak) an answer, then publish VOICE_SPEECH_DONE.

        When deltas already streamed some sentences, this flushes the remainder
        from the authoritative final text and closes the cycle. When nothing
        was streamed (SMS cues, one-sentence answers held until the end), this
        is the whole speak path — same contract as before.
        """
        if not self.tts_enabled or not self.speak_enabled:
            return
        clips = 0
        utterance = 0
        try:
            final_text = event.payload.get("text") or ""
            spoken = prepare_spoken_text(final_text, max_chars=self.max_spoken_chars)
            async with self._stream_lock:
                stream_open = self._stream_open
            if not spoken and not stream_open:
                return
            problem = self.tts.problem()
            if problem:
                await self._status(f"Voice output unavailable: {problem}")
                return

            if stream_open:
                # Authoritative final text may differ slightly from the delta
                # buffer (Sources list, citation append). Rebase on it and only
                # synthesize units not already spoken.
                async with self._stream_lock:
                    self._stream_raw = final_text
                    self._queue_from_buffer(finalize=True)
                    self._ensure_drain()
                    utterance = self._stream_utterance
                await self._await_drain()
                async with self._stream_lock:
                    clips = self._stream_clips
                    utterance = self._stream_utterance or utterance
                return

            async with self._speak_lock:
                self._speak_seq += 1
                utterance = self._speak_seq
                sentences = split_sentences(spoken) or [spoken]
                self._prune_clips()
                for index, sentence in enumerate(sentences):
                    if self._speak_cancelled >= utterance:
                        break
                    out = self._out_dir / f"reply_{utterance:04d}_{index:03d}.wav"
                    try:
                        path = await self.tts.synthesize(sentence, out)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        log.exception("Synthesis failed")
                        await self._status(f"Voice output failed: {exc}")
                        return
                    clips += 1
                    await self.bus.publish(
                        Event(
                            EventType.VOICE_AUDIO_READY,
                            {
                                "path": str(path),
                                "utterance": utterance,
                                "index": index,
                                "final": index == len(sentences) - 1,
                                "text": sentence,
                            },
                        )
                    )
        finally:
            async with self._stream_lock:
                self._reset_stream(keep_cancel=False)
            # publish_nowait, not await publish: this also has to run when the
            # task is being cancelled, and an await in a finally during
            # cancellation is not guaranteed to reach the other side.
            self.bus.publish_nowait(
                Event(
                    EventType.VOICE_SPEECH_DONE,
                    {"utterance": utterance, "clips": clips},
                )
            )

    def _queue_from_buffer(self, *, finalize: bool) -> None:
        prepared = prepare_spoken_text(
            self._stream_raw, max_chars=self.max_spoken_chars
        )
        units = next_speakable_units(prepared, self._spoken_count, finalize=finalize)
        if not units:
            return
        if not self._stream_open:
            self._speak_seq += 1
            self._stream_utterance = self._speak_seq
            self._stream_open = True
            self._stream_clips = 0
        last_i = self._spoken_count + len(units) - 1
        for offset, sentence in enumerate(units):
            index = self._spoken_count + offset
            is_final = finalize and index == last_i
            self._pending.append((sentence, is_final))
        self._spoken_count += len(units)

    def _ensure_drain(self) -> None:
        task = self._drain_task
        if task is None or task.done():
            self._drain_task = asyncio.create_task(
                self._drain_pending(), name="arelis-voice-tts-drain"
            )

    async def _await_drain(self) -> None:
        task = self._drain_task
        if task is not None and not task.done():
            try:
                await task
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Voice TTS drain failed")

    async def _drain_pending(self) -> None:
        """Synthesize queued sentences without holding the bus dispatch."""
        async with self._speak_lock:
            # Keep prune on the loop: a background to_thread here has deadlocked
            # under pytest's asyncio runner (executor wait with no worker
            # progress), and the directory walk is cheap compared to Piper.
            self._prune_clips()
            while self._pending:
                sentence, is_final = self._pending.pop(0)
                utterance = self._stream_utterance
                if not utterance or self._speak_cancelled >= utterance:
                    self._pending.clear()
                    return
                index = self._stream_clips
                out = self._out_dir / f"reply_{utterance:04d}_{index:03d}.wav"
                try:
                    path = await self.tts.synthesize(sentence, out)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.exception("Synthesis failed")
                    self._pending.clear()
                    await self._status(f"Voice output failed: {exc}")
                    return
                if self._speak_cancelled >= utterance:
                    return
                self._stream_clips += 1
                await self.bus.publish(
                    Event(
                        EventType.VOICE_AUDIO_READY,
                        {
                            "path": str(path),
                            "utterance": utterance,
                            "index": index,
                            "final": is_final,
                            "text": sentence,
                        },
                    )
                )

    def _reset_stream(self, *, keep_cancel: bool) -> None:
        self._stream_raw = ""
        self._spoken_count = 0
        self._stream_utterance = 0
        self._stream_clips = 0
        self._stream_open = False
        self._pending.clear()
        if not keep_cancel:
            # Allow the next reply to speak; leave cancel sticky only across a
            # retract that shares the same speak_seq until reset here.
            pass

    # ----------------------------------------------------------------- input

    async def ingest_audio(
        self,
        audio_path: str | Path,
        *,
        deliver: str = "turn",
        proceed: Callable[[], bool] | None = None,
    ) -> str:
        """Transcribe a recorded clip and put it into the pipeline.

        deliver is "turn" for speech that should become a message, which
        publishes VOICE_TRANSCRIPT and lets the orchestrator start a normal
        turn; "dictate" for speech that should only land in the composer; or
        "wake" for always-listen clips that are transcribed but not published
        (the window decides whether the wake phrase matched).

        proceed aborts after the STT lock is taken when a wake clip has been
        superseded (conversation took the mic). Without that, ambient wake
        jobs pile up on the lock and conversation hears nothing for minutes.

        Nothing here can leave a turn hanging: the transcript is what starts
        one, so every failure path returns before the orchestrator is involved
        and reports itself as an ERROR or a STATUS instead.
        """
        path = Path(audio_path)
        if not self.stt_enabled:
            await self._status("Voice input is off. Set voice.enabled and voice.stt.enabled.")
            return ""
        if not self.stt.available():
            await self._error(
                "Speech recognition is not available. "
                'Install the voice extra: pip install -e ".[voice]"'
            )
            return ""
        if not await asyncio.to_thread(path.exists):
            await self._status(f"Nothing to transcribe: {path} is missing.")
            return ""

        if not self.stt.loaded():
            await self._status(
                "Loading the speech model. The first run downloads it, which takes a minute."
            )
        try:
            stt_t0 = time.perf_counter()
            text = (
                await self.stt.transcribe(path, proceed=proceed, purpose=deliver)
            ).strip()
            stt_ms = int((time.perf_counter() - stt_t0) * 1000)
            if turn_telemetry_enabled(self.config):
                log_span(
                    "stt",
                    ms=stt_ms,
                    chars=len(text),
                    deliver=deliver,
                    loaded=self.stt.loaded(),
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("Transcription failed")
            await self._error(f"Could not transcribe that: {exc}")
            return ""
        finally:
            # The clip has served its purpose either way, and these are the only
            # recordings of the user's voice the app ever writes to disk, so
            # they go unless the user asked to keep them for debugging.
            if not self.keep_recordings:
                await asyncio.to_thread(_remove, path)

        if not text:
            if deliver != "wake":
                await self._status("No speech detected.")
            return ""

        if deliver == "wake":
            return text
        if deliver == "dictate":
            await self.bus.publish(
                Event(EventType.VOICE_TRANSCRIPT, {"text": text, "deliver": "dictate"})
            )
        else:
            await self.bus.publish(Event(EventType.VOICE_TRANSCRIPT, {"text": text}))
        return text

    async def preload(self) -> None:
        """Warm the speech model and TTS so the first exchange is not the slow one."""
        was_loaded = self.stt.loaded()
        if self.stt_enabled and self.stt.available():
            if not was_loaded:
                await self._status(
                    "Loading the speech model. The first run downloads it, which takes a minute."
                )
            try:
                await self.stt.preload()
            except Exception as exc:
                log.warning("Speech model preload failed: %s", exc)
                await self._status(f"Speech model preload failed: {exc}")
            else:
                if self.stt.loaded() and not was_loaded:
                    await self._status("Speech model ready.")

        if not self.tts_enabled:
            return
        problem = self.tts.problem()
        if problem:
            return
        warm = self._out_dir / "_tts_warm.wav"
        try:
            await self.tts.synthesize("Ready.", warm)
        except Exception as exc:
            log.warning("TTS warm-up failed: %s", exc)
        finally:
            await asyncio.to_thread(_remove, warm)

    # ----------------------------------------------------------------- misc

    def input_device_hint(self) -> str:
        return str(self.config.get("voice", {}).get("input_device") or "")

    async def _status(self, message: str) -> None:
        await self.bus.publish(Event(EventType.STATUS, {"message": message}))

    async def _error(self, message: str) -> None:
        # scope marks this as a failure of the voice pipeline rather than of a
        # turn. Voice ingest runs before any turn exists and can fail while an
        # unrelated typed turn is mid-flight, so the UI must not read it as
        # that turn's terminal event. See EventType.ERROR.
        await self.bus.publish(
            Event(EventType.ERROR, {"message": message, "scope": "voice"})
        )

    def _prune_clips(self) -> None:
        try:
            clips = sorted(
                self._out_dir.glob("reply_*.wav"), key=lambda p: p.stat().st_mtime
            )
        except OSError:
            return
        for stale in clips[:-_KEEP_CLIPS]:
            try:
                stale.unlink()
            except OSError:
                # Still held by the player, most likely. It will go next time.
                pass


def _remove(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


__all__ = [
    "VoiceService",
    "match_wake",
    "next_speakable_units",
    "prepare_spoken_text",
    "split_sentences",
    "stt_enabled",
    "tts_enabled",
]
