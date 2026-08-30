"""Voice tests that need neither a microphone nor a model.

Everything the audio hardware would supply is synthesized here: PCM is
generated arithmetically, transcription is a stub, and synthesis writes a byte
to a file. What is actually under test is the wiring — that speech becomes a
turn, that a missing dependency explains itself instead of crashing, that the
event loop keeps turning while Whisper works, and that what reaches the
synthesizer is speech rather than markup.
"""
from __future__ import annotations

import asyncio
import math
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.core.memory import SessionMemory
from arelis.core.orchestrator import Orchestrator
from arelis.tools.base import ToolRegistry
from arelis.voice import VoiceService, stt_enabled, tts_enabled
from arelis.voice.pcm import (
    duration_seconds,
    peak_level,
    rms_level,
    trim_trailing_silence,
    write_wav,
)
from arelis.voice.speech_text import (
    next_speakable_units,
    prepare_spoken_text,
    split_sentences,
)
from arelis.voice.vad import ENDED, STARTED, DetectorConfig, UtteranceDetector

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _config(**overrides: Any) -> dict[str, Any]:
    voice: dict[str, Any] = {
        "enabled": True,
        "keep_recordings": False,
        "stt": {"enabled": True, "model_size": "base"},
        "tts": {"enabled": True, "backend": "piper", "voice_model": "", "max_chars": 0},
        "conversation": {},
        # Synthetic sine tones are not speech to Silero; controller tests use energy.
        "vad": {"backend": "energy", "allow_download": False},
        "wake": {"engine": "whisper", "enabled": True},
    }
    conv = {"smart_turn": False}
    extra_conv = overrides.pop("conversation", None)
    if extra_conv:
        conv.update(extra_conv)
    voice["conversation"] = conv
    voice.update(overrides)
    return {"voice": voice, "agent": {}, "_persona_path": "does-not-exist.md"}


def _tone(seconds: float, *, rate: int = 16000, amplitude: float = 0.3) -> bytes:
    """A 220 Hz sine, which reads as speech to a level-based detector."""
    frames = int(rate * seconds)
    peak = int(amplitude * 32767)
    return b"".join(
        struct.pack("<h", int(peak * math.sin(2 * math.pi * 220 * i / rate)))
        for i in range(frames)
    )


def _silence(seconds: float, *, rate: int = 16000) -> bytes:
    return b"\x00\x00" * int(rate * seconds)


def _fake_clip(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF")
    return path


async def _collect(bus: EventBus, coro) -> list[Event]:
    events: list[Event] = []

    async def capture(event: Event) -> None:
        events.append(event)

    bus.subscribe(None, capture)
    task = asyncio.create_task(bus.run())
    await coro
    await bus.drain()
    bus.stop()
    task.cancel()
    return events


class _FakeSTT:
    def __init__(self, text: str = "hello there", *, ready: bool = True) -> None:
        self.text = text
        self.ready = ready
        self.calls: list[str] = []

    def available(self) -> bool:
        return self.ready

    def loaded(self) -> bool:
        return True

    def resolved_backend(self, *, purpose: str = "turn") -> str | None:
        return "whisper" if self.ready else None

    async def transcribe(self, path, *, proceed=None, purpose: str = "turn") -> str:
        if proceed is not None and not proceed():
            return ""
        self.calls.append(str(path))
        return self.text

    async def preload(self) -> None:
        return None


# --------------------------------------------------------------------------
# Spoken text: what she reads aloud is not what is on screen
# --------------------------------------------------------------------------


def test_arelis_name_is_phonetic_for_piper() -> None:
    spoken = prepare_spoken_text("I am Arelis, your local assistant.")
    assert "Arelis" not in spoken
    assert "Uh-rell-iss" in spoken
    mangled = prepare_spoken_text("Hi, I am Airelyse.")
    assert "Airelyse" not in mangled
    assert "Uh-rell-iss" in mangled


def test_leaked_cjk_is_scrubbed_from_speech() -> None:
    from arelis.voice.speech_text import scrub_cjk_runs

    spoken = prepare_spoken_text("That went smoothly 顺畅 for you.")
    assert "顺畅" not in spoken
    assert "smoothly" in spoken
    assert scrub_cjk_runs("ok 顺畅 now") == "ok now"


def test_sources_list_is_never_spoken() -> None:
    """The worst possible thing to synthesize: a URL, letter by letter."""
    answer = "Vega is 25 light years away.\n\n**Sources:**\n\n1. Example (https://example.com)"
    spoken = prepare_spoken_text(answer)
    assert spoken == "Vega is 25 light years away."
    assert "http" not in spoken


def test_code_blocks_are_dropped_not_read() -> None:
    answer = "Here is the fix:\n\n```python\nx = [1, 2]\nprint(x)\n```\n\nRun it and see."
    spoken = prepare_spoken_text(answer)
    assert "print" not in spoken
    assert spoken.startswith("Here is the fix:")
    assert spoken.endswith("Run it and see.")


def test_markdown_marks_do_not_survive_into_speech() -> None:
    spoken = prepare_spoken_text("## Heading\n\n**bold** and *italic* and `code`.")
    assert "#" not in spoken
    assert "*" not in spoken
    assert "`" not in spoken
    assert "bold and italic and code." in spoken


def test_identifiers_keep_their_underscores() -> None:
    """Underscore emphasis and snake_case look identical to a naive stripper,
    and this assistant writes snake_case constantly."""
    spoken = prepare_spoken_text("Check tool_output_chars before max_rounds.")
    assert "tool_output_chars" in spoken
    assert "max_rounds" in spoken


def test_links_are_spoken_as_their_text() -> None:
    spoken = prepare_spoken_text("See [the paper](https://arxiv.org/abs/1234) for detail.")
    assert "the paper" in spoken
    assert "arxiv" not in spoken


def test_bullets_gain_the_punctuation_they_lack() -> None:
    """Without it every bullet runs into the next as one breathless sentence."""
    spoken = prepare_spoken_text("- first point\n- second point")
    assert spoken == "first point. second point."


def test_tables_become_readable_rows() -> None:
    spoken = prepare_spoken_text("| role | model |\n| --- | --- |\n| fast | qwen |")
    assert "|" not in spoken
    assert "role, model" in spoken
    assert "fast, qwen" in spoken


def test_an_answer_with_nothing_speakable_produces_nothing() -> None:
    """A reply that is only a code block must not synthesize a clip of silence
    and then be announced as speech."""
    assert prepare_spoken_text("```\nx = 1\n```") == ""
    assert prepare_spoken_text("") == ""


def test_long_answers_are_not_truncated_by_default() -> None:
    """The decision on record: length is handled by being able to interrupt
    her, not by cutting the answer short."""
    long_answer = " ".join(f"Sentence number {i} says something." for i in range(200))
    assert len(prepare_spoken_text(long_answer)) > 5000


def test_the_runaway_guard_still_cuts_on_a_sentence() -> None:
    text = "One two three. Four five six. Seven eight nine."
    capped = prepare_spoken_text(text, max_chars=30)
    assert capped == "One two three. Four five six."


def test_sentences_split_for_the_playback_queue() -> None:
    parts = split_sentences("First one. Second one! Third one?")
    assert parts == ["First one.", "Second one!", "Third one?"]


def test_next_speakable_units_holds_the_trailing_sentence_until_finalize() -> None:
    prepared = "First one. Second one. Third growing"
    assert next_speakable_units(prepared, 0, finalize=False) == [
        "First one.",
        "Second one.",
    ]
    assert next_speakable_units(prepared, 2, finalize=False) == []
    assert next_speakable_units(prepared, 2, finalize=True) == ["Third growing"]
    # A finished sentence can start audio before ASSISTANT_DONE.
    assert next_speakable_units("Only one.", 0, finalize=False) == ["Only one."]
    assert next_speakable_units("Only one.", 1, finalize=True) == []
    assert next_speakable_units("Only one.", 0, finalize=True) == ["Only one."]
    # Growing fragment without terminal punctuation is still held.
    assert next_speakable_units("Hello there", 0, finalize=False) == []
    assert next_speakable_units("Hello there", 0, finalize=True) == ["Hello there"]


def test_abbreviations_do_not_split_a_sentence() -> None:
    """A split here drops a full stop's worth of silence mid-clause."""
    assert split_sentences("Dr. Vega measured 25 l.y. exactly.") == [
        "Dr. Vega measured 25 l.y. exactly."
    ]


# --------------------------------------------------------------------------
# Config gating: one switch per direction
# --------------------------------------------------------------------------


def test_master_switch_turns_off_both_directions() -> None:
    config = _config()
    config["voice"]["enabled"] = False
    assert not stt_enabled(config)
    assert not tts_enabled(config)


def test_each_direction_toggles_on_its_own() -> None:
    """The mic has to be usable with playback off, which one boolean could not
    express."""
    config = _config()
    config["voice"]["tts"]["enabled"] = False
    assert stt_enabled(config)
    assert not tts_enabled(config)

    config = _config()
    config["voice"]["stt"]["enabled"] = False
    assert not stt_enabled(config)
    assert tts_enabled(config)


def test_directions_default_on_under_the_master_switch() -> None:
    config = {"voice": {"enabled": True}}
    assert stt_enabled(config)
    assert tts_enabled(config)


@pytest.mark.asyncio
async def test_speak_is_not_subscribed_when_output_is_off() -> None:
    config = _config()
    config["voice"]["tts"]["enabled"] = False
    bus = EventBus()
    VoiceService(bus, config)
    events = await _collect(
        bus, bus.publish(Event(EventType.VOICE_SPEAK, {"text": "say something"}))
    )
    assert EventType.VOICE_AUDIO_READY not in [e.type for e in events]


# --------------------------------------------------------------------------
# Degradation: a missing dependency explains itself
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_whisper_is_an_explanation_not_a_crash(tmp_path) -> None:
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.stt = _FakeSTT(ready=False)
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"")
    events = await _collect(bus, service.ingest_audio(clip))
    errors = [e for e in events if e.type == EventType.ERROR]
    assert errors, "a missing dependency must be reported, not swallowed"
    assert "pip install" in errors[0].payload["message"]
    assert EventType.VOICE_TRANSCRIPT not in [e.type for e in events]


@pytest.mark.asyncio
async def test_unconfigured_piper_reports_where_to_get_it() -> None:
    """The old failure was a RuntimeError naming a config key and nothing else.
    The two things a user needs are the binary and the voice pair."""
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.speak_enabled = True
    events = await _collect(
        bus, bus.publish(Event(EventType.VOICE_SPEAK, {"text": "hello"}))
    )
    statuses = [e.payload["message"] for e in events if e.type == EventType.STATUS]
    assert any("voice_model" in m or "Piper" in m for m in statuses)
    assert EventType.VOICE_AUDIO_READY not in [e.type for e in events]


@pytest.mark.asyncio
async def test_speak_is_silent_outside_conversation_mode() -> None:
    """Typed chat and dictation must not trigger playback."""
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.speak_enabled = False

    class _FakeTTS:
        def problem(self) -> None:
            return None

        async def synthesize(self, text: str, out) -> Path:
            raise AssertionError("TTS must not run when speak_enabled is false")

    service.tts = _FakeTTS()
    events = await _collect(
        bus, bus.publish(Event(EventType.VOICE_SPEAK, {"text": "hello"}))
    )
    assert EventType.VOICE_AUDIO_READY not in [e.type for e in events]


@pytest.mark.asyncio
async def test_a_failing_transcription_does_not_raise_into_the_loop(tmp_path) -> None:
    class _Broken(_FakeSTT):
        async def transcribe(self, path, *, proceed=None, purpose: str = "turn") -> str:
            raise RuntimeError("cuda is on fire")

    bus = EventBus()
    service = VoiceService(bus, _config())
    service.stt = _Broken()
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"")
    events = await _collect(bus, service.ingest_audio(clip))
    errors = [e for e in events if e.type == EventType.ERROR]
    assert errors and "cuda is on fire" in errors[0].payload["message"]


@pytest.mark.asyncio
async def test_silence_is_reported_and_starts_no_turn(tmp_path) -> None:
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.stt = _FakeSTT("   ")
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"")
    events = await _collect(bus, service.ingest_audio(clip))
    assert EventType.VOICE_TRANSCRIPT not in [e.type for e in events]
    assert any(
        "No speech" in e.payload.get("message", "")
        for e in events
        if e.type == EventType.STATUS
    )


@pytest.mark.asyncio
async def test_the_recording_is_deleted_once_transcribed(tmp_path) -> None:
    """These are the only recordings of the user's voice the app ever writes."""
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.stt = _FakeSTT()
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"x")
    await _collect(bus, service.ingest_audio(clip))
    assert not clip.exists()


@pytest.mark.asyncio
async def test_recordings_are_kept_when_asked(tmp_path) -> None:
    config = _config()
    config["voice"]["keep_recordings"] = True
    bus = EventBus()
    service = VoiceService(bus, config)
    service.stt = _FakeSTT()
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"x")
    await _collect(bus, service.ingest_audio(clip))
    assert clip.exists()


# --------------------------------------------------------------------------
# The integration seam: a transcript becomes a turn
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_speech_becomes_a_user_message(tmp_path) -> None:
    """The whole point of the wiring. Everything downstream of USER_MESSAGE is
    the ordinary turn pipeline and is already covered elsewhere."""
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.stt = _FakeSTT("how far away is Vega")
    Orchestrator(bus, _StubRouter(), ToolRegistry(), _config(), SessionMemory())
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"x")

    events = await _collect(bus, service.ingest_audio(clip))
    spoken = [
        e for e in events
        if e.type == EventType.USER_MESSAGE and e.payload.get("source") == "voice"
    ]
    assert len(spoken) == 1
    assert spoken[0].payload["text"] == "how far away is Vega"


@pytest.mark.asyncio
async def test_dictation_never_starts_a_turn(tmp_path) -> None:
    """Dictated text is for the composer. Sending it would take the decision
    away from the user, which is the difference between the two modes."""
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.stt = _FakeSTT("a half formed idea")
    Orchestrator(bus, _StubRouter(), ToolRegistry(), _config(), SessionMemory())
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"x")

    events = await _collect(bus, service.ingest_audio(clip, deliver="dictate"))
    transcripts = [e for e in events if e.type == EventType.VOICE_TRANSCRIPT]
    assert len(transcripts) == 1
    assert transcripts[0].payload["deliver"] == "dictate"
    assert EventType.USER_MESSAGE not in [e.type for e in events]


class _StubRouter:
    default_role = "fast"
    models = {"fast": "mock", "research": "mock", "code": "mock"}
    active_model = None

    def model_for(self, role=None):
        return "mock"

    async def ensure_role(self, role, *, force: bool = False):
        del force
        return "mock"

    def mark_sticky(self, role) -> None:
        return None

    async def stream(self, role, messages, **kwargs):
        yield ("token", "an answer")


# --------------------------------------------------------------------------
# The blocking bug: transcription must not stall the event loop
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcription_leaves_the_event_loop_running() -> None:
    """model.transcribe used to run inline in an async function. The loop it
    blocked also carries event delivery, the stop button, and the confirm card,
    so the whole app froze for the length of the transcription.

    The test does not inspect the implementation: it starts a transcription
    that will not return until the loop has made progress, and deadlocks if
    that progress is impossible.
    """
    from arelis.voice.stt import SpeechToText

    released = asyncio.Event()
    ticks = 0

    class _SlowModel:
        def transcribe(self, path, **kwargs):
            # Blocks in whatever thread it is called on until the loop has run.
            while not released.is_set():
                pass
            return ([_Segment("done")], None)

    class _Segment:
        def __init__(self, text: str) -> None:
            self.text = text

    # Whisper by configuration, not by accident. This used to pass on a bare
    # config because a loaded model was enough to pick the backend, which was
    # the bug that quietly retired Sherpa for a whole session.
    stt = SpeechToText({"voice": {"stt": {"backend": "whisper"}}})
    stt.available = lambda: True  # type: ignore[method-assign]
    stt._model = _SlowModel()

    async def keep_ticking() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1
        released.set()

    result, _ = await asyncio.wait_for(
        asyncio.gather(stt.transcribe("clip.wav"), keep_ticking()), timeout=10
    )
    assert result == "done"
    assert ticks == 5, "the loop stopped while the model was working"


@pytest.mark.asyncio
async def test_the_model_is_built_off_the_loop_too() -> None:
    """Constructing WhisperModel downloads weights on first run. Doing that
    inline froze the app for a minute before the first word was transcribed."""
    from arelis.voice.stt import SpeechToText

    built_in: list[str] = []

    class _Model:
        def transcribe(self, path, **kwargs):
            return ([], None)

    stt = SpeechToText({"voice": {"stt": {"backend": "faster-whisper"}}})
    stt.available = lambda: True  # type: ignore[method-assign]

    import threading

    def build():
        built_in.append(threading.current_thread().name)
        return _Model()

    stt._ensure_model = build  # type: ignore[method-assign]
    await stt.transcribe("clip.wav")
    assert built_in and built_in[0] != threading.main_thread().name


def test_missing_sherpa_files_fall_back_to_whisper(tmp_path, monkeypatch) -> None:
    from arelis.voice.stt import SpeechToText

    stt = SpeechToText(
        {
            "voice": {
                "stt": {
                    "backend": "sherpa",
                    "model_dir": str(tmp_path / "empty"),
                    "allow_download": False,
                }
            }
        }
    )
    monkeypatch.setattr(stt, "_whisper_installed", lambda: True)
    monkeypatch.setattr(
        "arelis.voice.sherpa_stt.sherpa_package_available", lambda: True
    )
    assert stt.resolved_backend() == "faster-whisper"
    assert stt.available()


def test_neither_stt_backend_is_a_clear_miss(tmp_path, monkeypatch) -> None:
    from arelis.voice.stt import SpeechToText

    stt = SpeechToText(
        {
            "voice": {
                "stt": {
                    "backend": "sherpa",
                    "model_dir": str(tmp_path / "empty"),
                    "allow_download": False,
                }
            }
        }
    )
    monkeypatch.setattr(stt, "_whisper_installed", lambda: False)
    monkeypatch.setattr(
        "arelis.voice.sherpa_stt.sherpa_package_available", lambda: False
    )
    assert stt.resolved_backend() is None
    assert not stt.available()


def test_sherpa_is_chosen_when_the_pack_is_on_disk(tmp_path, monkeypatch) -> None:
    from arelis.voice.stt import SpeechToText

    pack = tmp_path / "sherpa-onnx-streaming-zipformer-en-2023-06-26"
    pack.mkdir()
    (pack / "tokens.txt").write_text("a\n", encoding="utf-8")
    (pack / "encoder-epoch-99-avg-1-chunk-16-left-128.onnx").write_bytes(b"x")
    (pack / "decoder-epoch-99-avg-1-chunk-16-left-128.onnx").write_bytes(b"x")
    (pack / "joiner-epoch-99-avg-1-chunk-16-left-128.onnx").write_bytes(b"x")

    stt = SpeechToText(
        {
            "voice": {
                "stt": {
                    "backend": "sherpa",
                    "model_dir": str(tmp_path),
                    "allow_download": False,
                }
            }
        }
    )
    monkeypatch.setattr(
        "arelis.voice.sherpa_stt.sherpa_package_available", lambda: True
    )
    monkeypatch.setattr(stt, "_whisper_installed", lambda: True)
    assert stt.resolved_backend() == "sherpa"


def test_sherpa_finds_transducer_files_in_a_pack_folder(tmp_path) -> None:
    from arelis.voice.sherpa_stt import find_transducer_files, sherpa_files_present

    pack = tmp_path / "sherpa-onnx-streaming-zipformer-en-2023-06-26"
    pack.mkdir()
    (pack / "tokens.txt").write_text("a\n", encoding="utf-8")
    (pack / "encoder-epoch-99-avg-1-chunk-16-left-128.onnx").write_bytes(b"x")
    (pack / "decoder-epoch-99-avg-1-chunk-16-left-128.onnx").write_bytes(b"x")
    (pack / "joiner-epoch-99-avg-1-chunk-16-left-128.onnx").write_bytes(b"x")
    found = find_transducer_files(tmp_path)
    assert found is not None
    assert found["tokens"].name == "tokens.txt"
    assert sherpa_files_present(tmp_path)


def test_sherpa_prefers_kroko_pack_over_2023(tmp_path) -> None:
    from arelis.voice.sherpa_stt import find_transducer_files

    def _pack(name: str) -> None:
        folder = tmp_path / name
        folder.mkdir()
        (folder / "tokens.txt").write_text("a\n", encoding="utf-8")
        (folder / "encoder.onnx").write_bytes(b"x")
        (folder / "decoder.onnx").write_bytes(b"x")
        (folder / "joiner.onnx").write_bytes(b"x")

    _pack("sherpa-onnx-streaming-zipformer-en-2023-06-26")
    _pack("sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06")
    found = find_transducer_files(tmp_path)
    assert found is not None
    assert found["pack"] == "sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06"


def test_sherpa_does_not_download_when_asked_not_to(tmp_path) -> None:
    from arelis.voice.sherpa_stt import SherpaUnavailableError, ensure_sherpa_files

    with pytest.raises(SherpaUnavailableError, match="not found"):
        ensure_sherpa_files(tmp_path / "empty", allow_download=False)


@pytest.mark.asyncio
async def test_sherpa_transcribe_runs_off_the_loop(tmp_path) -> None:
    from arelis.voice.stt import SpeechToText

    released = asyncio.Event()
    ticks = 0

    class _SlowSherpa:
        def transcribe(self, path):
            while not released.is_set():
                pass
            return "seventeen times nineteen"

        def loaded(self) -> bool:
            return True

        def ensure_loaded(self):
            return None

    stt = SpeechToText({"voice": {"stt": {"backend": "sherpa"}}})
    stt.available = lambda: True  # type: ignore[method-assign]
    stt.resolved_backend = lambda **_: "sherpa"  # type: ignore[method-assign]
    stt._sherpa = _SlowSherpa()

    async def keep_ticking() -> None:
        nonlocal ticks
        for _ in range(5):
            await asyncio.sleep(0.01)
            ticks += 1
        released.set()

    result, _ = await asyncio.wait_for(
        asyncio.gather(stt.transcribe("clip.wav"), keep_ticking()), timeout=10
    )
    assert result == "seventeen times nineteen"
    assert ticks == 5


@pytest.mark.asyncio
async def test_sherpa_error_falls_back_to_whisper_without_crashing() -> None:
    from arelis.voice.sherpa_stt import SherpaUnavailableError
    from arelis.voice.stt import SpeechToText

    class _Boom:
        def transcribe(self, path):
            raise SherpaUnavailableError("model files missing")

        def loaded(self) -> bool:
            return False

    class _Whisper:
        def transcribe(self, path, **kwargs):
            return ([type("Seg", (), {"text": "hello"})()], None)

    stt = SpeechToText({"voice": {"stt": {"backend": "sherpa"}}})
    stt.available = lambda: True  # type: ignore[method-assign]
    stt.resolved_backend = lambda **_: "sherpa"  # type: ignore[method-assign]
    stt._sherpa = _Boom()
    stt._whisper_installed = lambda: True  # type: ignore[method-assign]
    stt._ensure_model = lambda: _Whisper()  # type: ignore[method-assign]

    assert await stt.transcribe("clip.wav") == "hello"
    assert stt._sherpa_failed


# --------------------------------------------------------------------------
# PCM and WAV
# --------------------------------------------------------------------------


def test_captured_pcm_becomes_a_readable_wav(tmp_path) -> None:
    pcm = _tone(0.25)
    path = write_wav(tmp_path / "nested" / "c.wav", pcm, sample_rate=16000)
    with wave.open(str(path), "rb") as fh:
        assert fh.getnchannels() == 1
        assert fh.getsampwidth() == 2
        assert fh.getframerate() == 16000
        assert fh.getnframes() == 4000


def test_level_readings_separate_speech_from_silence() -> None:
    assert rms_level(_silence(0.1)) == 0.0
    assert rms_level(_tone(0.1, amplitude=0.3)) > 0.15
    assert peak_level(_tone(0.1, amplitude=0.5)) > 0.45
    assert rms_level(b"") == 0.0
    # An odd trailing byte is a partial frame, not a crash.
    assert rms_level(b"\x01") == 0.0


def test_duration_matches_the_frames_written() -> None:
    assert duration_seconds(_tone(1.5), sample_rate=16000) == pytest.approx(1.5)
    assert duration_seconds(_tone(1.0), sample_rate=16000, channels=2) == pytest.approx(0.5)


# --------------------------------------------------------------------------
# Utterance detection, which is what makes conversation mode hands free
# --------------------------------------------------------------------------


def _feed(detector: UtteranceDetector, pcm: bytes, *, block_ms: int = 100) -> list[str]:
    """Feed audio in realistic block sizes and collect what fired."""
    block = int(16000 * block_ms / 1000) * 2
    events = []
    for start in range(0, len(pcm), block):
        event = detector.feed(pcm[start : start + block])
        if event:
            events.append(event)
    return events


def test_a_pause_ends_an_utterance() -> None:
    detector = UtteranceDetector(DetectorConfig(silence_ms=800, short_silence_ms=800))
    events = _feed(detector, _silence(0.5) + _tone(1.0) + _silence(1.2))
    assert events == [STARTED, ENDED]


def test_a_short_pause_mid_sentence_does_not_end_it() -> None:
    """People breathe. Ending on the first gap turns one thought into three
    messages and three model turns."""
    detector = UtteranceDetector(
        DetectorConfig(silence_ms=1200, short_silence_ms=1200)
    )
    events = _feed(
        detector, _silence(0.5) + _tone(0.8) + _silence(0.4) + _tone(0.8) + _silence(0.3)
    )
    assert events == [STARTED]


def test_short_commands_end_on_tighter_silence() -> None:
    """Adaptive end-point: a short ask should not wait the full silence_ms."""
    detector = UtteranceDetector(
        DetectorConfig(
            silence_ms=1200,
            short_silence_ms=500,
            short_utterance_ms=2800,
        )
    )
    # ~1s of speech then 0.7s quiet: under short window, over short silence.
    events = _feed(detector, _silence(0.4) + _tone(1.0) + _silence(0.7))
    assert events == [STARTED, ENDED]


def test_long_speech_keeps_full_silence_window() -> None:
    """Longer thoughts still need the full pause so mid-clause gaps survive."""
    detector = UtteranceDetector(
        DetectorConfig(
            silence_ms=1200,
            short_silence_ms=500,
            short_utterance_ms=2000,
        )
    )
    # 2.5s voiced (> short_utterance) then only 0.7s quiet — must stay open.
    events = _feed(detector, _silence(0.3) + _tone(2.5) + _silence(0.7))
    assert events == [STARTED]
    events2 = _feed(detector, _silence(0.7))
    assert events2 == [ENDED]


def test_a_click_is_not_speech() -> None:
    """A keyboard clack or a chair creak must not open an utterance."""
    detector = UtteranceDetector(DetectorConfig(silence_ms=600))
    events = _feed(detector, _silence(0.5) + _tone(0.05) + _silence(1.0), block_ms=20)
    assert events == []


def test_the_floor_is_measured_from_the_room() -> None:
    """A fixed threshold is wrong in every room but one. A noisy background
    raises the bar rather than triggering on itself."""
    quiet = UtteranceDetector(DetectorConfig())
    _feed(quiet, _silence(0.5))
    noisy = UtteranceDetector(DetectorConfig())
    _feed(noisy, _tone(0.5, amplitude=0.02))
    assert noisy.threshold > quiet.threshold


def test_talking_immediately_still_registers() -> None:
    """Calibration cannot assume half a second of silence to start with: the
    user may already be talking when the mic opens."""
    detector = UtteranceDetector(DetectorConfig(silence_ms=600))
    events = _feed(detector, _tone(1.0) + _silence(0.9))
    assert events == [STARTED, ENDED]


def test_a_runaway_capture_is_cut() -> None:
    detector = UtteranceDetector(DetectorConfig(max_utterance_s=1, silence_ms=5000))
    events = _feed(detector, _silence(0.5) + _tone(2.0))
    assert events[0] == STARTED
    assert events[-1] == "timeout"


def test_nothing_fires_after_an_utterance_closes() -> None:
    """The controller resets the detector between utterances. Until it does,
    a closed detector must stay quiet rather than emitting a second ENDED."""
    detector = UtteranceDetector(DetectorConfig(silence_ms=400, short_silence_ms=400))
    _feed(detector, _silence(0.5) + _tone(0.5) + _silence(0.6))
    assert _feed(detector, _tone(0.5) + _silence(0.6)) == []
    detector.reset()
    assert _feed(detector, _tone(0.5) + _silence(0.6)) == [STARTED, ENDED]


def test_trim_trailing_silence_keeps_speech_pad() -> None:
    pcm = _tone(0.4) + _silence(0.9)
    trimmed = trim_trailing_silence(pcm, sample_rate=16000, channels=1, keep_ms=80)
    # Dropped most of the 0.9s pad; kept speech + small keep_ms.
    assert len(trimmed) < len(pcm) * 0.7
    assert len(trimmed) > len(_tone(0.3))


class _FakeSileroEngine:
    """Return high speech prob when the 512-frame has energy."""

    def __init__(self) -> None:
        self.resets = 0
        import numpy as np

        self._pending = np.zeros(0, dtype=np.float32)

    def reset(self) -> None:
        import numpy as np

        self.resets += 1
        self._pending = np.zeros(0, dtype=np.float32)

    def push(self, samples_f32):
        import numpy as np

        from arelis.voice.silero_vad import FRAME_SAMPLES

        flat = np.asarray(samples_f32, dtype=np.float32).reshape(-1)
        if self._pending.size:
            flat = np.concatenate([self._pending, flat])
        probs = []
        offset = 0
        while offset + FRAME_SAMPLES <= flat.size:
            chunk = flat[offset : offset + FRAME_SAMPLES]
            probs.append(0.9 if float(np.mean(np.abs(chunk))) > 0.02 else 0.05)
            offset += FRAME_SAMPLES
        self._pending = flat[offset:].copy()
        return probs


def test_silero_detector_ends_on_silence() -> None:
    from arelis.voice.vad import SileroUtteranceDetector

    detector = SileroUtteranceDetector(
        DetectorConfig(
            silence_ms=800,
            short_silence_ms=800,
            speech_threshold=0.5,
            onset_ms=160,
        ),
        engine=_FakeSileroEngine(),
    )
    events = _feed(detector, _silence(0.5) + _tone(1.0) + _silence(1.2))
    assert events == [STARTED, ENDED]


def test_silero_end_hysteresis_keeps_mid_prob_voiced() -> None:
    """While speaking, probs between end_threshold and speech_threshold stay voiced."""
    from arelis.voice.silero_vad import FRAME_SAMPLES
    from arelis.voice.vad import SileroUtteranceDetector

    class _ScriptedEngine:
        def __init__(self) -> None:
            # Onset (>=0.5), then mid-band (0.4 — below speech, above end=0.35),
            # then true silence. Mid-band must not start the silence clock.
            self._queue = [0.9] * 8 + [0.4] * 20 + [0.05] * 40
            self.resets = 0

        def reset(self) -> None:
            self.resets += 1

        def push(self, samples_f32):
            import numpy as np

            n = int(np.asarray(samples_f32).size // FRAME_SAMPLES)
            out = []
            for _ in range(n):
                out.append(self._queue.pop(0) if self._queue else 0.05)
            return out

    detector = SileroUtteranceDetector(
        DetectorConfig(
            silence_ms=400,
            short_silence_ms=400,
            speech_threshold=0.5,
            end_threshold=0.35,
            onset_ms=100,
        ),
        engine=_ScriptedEngine(),
    )
    # Enough PCM for scripted frames (~32ms each at 16k / 512).
    events = _feed(detector, _tone(2.2))
    assert STARTED in events
    assert ENDED in events


def test_silero_reset_soft_clears_neural_state() -> None:
    from arelis.voice.vad import SileroUtteranceDetector

    engine = _FakeSileroEngine()
    detector = SileroUtteranceDetector(
        DetectorConfig(silence_ms=600, short_silence_ms=600),
        engine=engine,
    )
    _feed(detector, _tone(0.5))
    before = engine.resets
    detector.reset_soft()
    assert engine.resets == before + 1
    assert not detector.speaking


def test_make_utterance_detector_energy_backend() -> None:
    from arelis.voice.vad import EnergyUtteranceDetector, make_utterance_detector

    det = make_utterance_detector("energy", DetectorConfig())
    assert isinstance(det, EnergyUtteranceDetector)
    assert det.backend == "energy"


def test_silero_onnx_loads_when_model_present() -> None:
    from arelis.voice.silero_vad import default_model_path, silero_available
    from arelis.voice.vad import DetectorConfig, make_utterance_detector

    if not silero_available():
        pytest.skip("Silero ONNX / onnxruntime not available")
    det = make_utterance_detector(
        "silero",
        DetectorConfig(),
        model_path=default_model_path(),
        allow_download=False,
    )
    assert det.backend == "silero"
    # Pure tones are not speech; just prove feed is safe and returns probs.
    det.feed(_silence(0.2))
    det.feed(_tone(0.5))
    assert det.last_speech_prob is not None


def test_make_utterance_detector_falls_back_without_model(tmp_path) -> None:
    from arelis.voice.vad import EnergyUtteranceDetector, make_utterance_detector

    missing = tmp_path / "nope.onnx"
    det = make_utterance_detector(
        "silero",
        DetectorConfig(),
        model_path=missing,
        allow_download=False,
    )
    assert isinstance(det, EnergyUtteranceDetector)


def test_openwake_max_score_helper() -> None:
    from arelis.voice.openwake import _max_score

    assert _max_score({"hey_arelis": 0.8}, ["hey_arelis"]) == pytest.approx(0.8)
    assert _max_score({"a": 0.1, "b": 0.9}, ["a", "b"]) == pytest.approx(0.9)


def test_wake_oww_utterance_skips_wav(qt_app) -> None:
    """openWakeWord deliver path must not require PCM or STT."""
    from arelis.ui.voice_control import VoiceController

    cfg = {
        "voice": {
            "enabled": True,
            "wake": {"engine": "whisper"},
            "vad": {"backend": "energy", "allow_download": False},
            "conversation": {"smart_turn": False},
        }
    }
    ctrl = VoiceController(cfg)
    holds: list[str] = []
    ctrl.utterance.connect(lambda pcm, rate, ch, deliver: holds.append(deliver))
    ctrl.utterance.emit(b"", 16000, 1, "wake_oww")
    assert holds == ["wake_oww"]


# --------------------------------------------------------------------------
# Piper adapter: the failure message is the feature
# --------------------------------------------------------------------------


def test_a_voice_without_its_json_sidecar_is_named_exactly(tmp_path) -> None:
    """Downloading the .onnx and missing the .onnx.json is the most common way
    to get Piper wrong, and piper's own error for it is a stack trace."""
    from arelis.voice.tts import TextToSpeech

    model = tmp_path / "en_GB-jenny_dioco-medium.onnx"
    model.write_bytes(b"not really a model")
    tts = TextToSpeech({"voice": {"tts": {"voice_model": str(model)}}})
    problem = tts.problem() or ""
    assert "en_GB-jenny_dioco-medium.onnx.json" in problem
    assert not tts.available()


def test_a_missing_voice_points_at_the_readme() -> None:
    from arelis.voice.tts import TextToSpeech

    tts = TextToSpeech({"voice": {"tts": {"voice_model": ""}}})
    problem = tts.problem() or ""
    assert "voice_model" in problem
    assert "README" in problem


def test_a_missing_piper_names_the_install_command(tmp_path) -> None:
    from arelis.voice.tts import TextToSpeech

    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    (tmp_path / "v.onnx.json").write_text("{}", encoding="utf-8")
    tts = TextToSpeech({"voice": {"tts": {"voice_model": str(model)}}})
    tts.command = []
    assert "pip install piper-tts" in (tts.problem() or "")


def test_both_piper_command_line_generations_are_tried(tmp_path, monkeypatch) -> None:
    """The maintained pip package takes the text as an argument after --; the
    archived 2023 binary reads it from stdin. Guessing wrong produces no audio
    and no obvious reason why."""
    from arelis.voice import tts as tts_module

    tts = tts_module.TextToSpeech({"voice": {"tts": {"voice_model": "v.onnx"}}})
    tts.command = ["piper"]
    seen: list[tuple[list[str], bytes]] = []

    def fake_run(argv, input=b"", **kwargs):
        seen.append((list(argv), input))
        return subprocess.CompletedProcess(argv, 1, b"", b"nope")

    monkeypatch.setattr(tts_module.subprocess, "run", fake_run)
    tts._run_piper("hello", tmp_path / "o.wav", "modern")
    tts._run_piper("hello", tmp_path / "o.wav", "legacy")

    assert seen[0][0][-2:] == ["--", "hello"]
    assert seen[0][1] == b""
    assert "--output_file" in seen[1][0]
    assert seen[1][1] == b"hello"


@pytest.mark.asyncio
async def test_the_working_argument_style_is_remembered(tmp_path, monkeypatch) -> None:
    """Otherwise every sentence pays for a failed process spawn first."""
    from arelis.voice import tts as tts_module

    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    (tmp_path / "v.onnx.json").write_text("{}", encoding="utf-8")
    tts = tts_module.TextToSpeech({"voice": {"tts": {"voice_model": str(model)}}})
    tts.command = ["piper"]
    attempts: list[str] = []

    def fake_run(argv, input=b"", **kwargs):
        style = "modern" if "--" in argv else "legacy"
        attempts.append(style)
        if style == "legacy":
            Path(argv[argv.index("--output_file") + 1]).write_bytes(b"RIFF")
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        return subprocess.CompletedProcess(argv, 2, b"", b"unrecognized arguments")

    monkeypatch.setattr(tts_module.subprocess, "run", fake_run)
    await tts.synthesize("one", tmp_path / "a.wav")
    await tts.synthesize("two", tmp_path / "b.wav")
    assert attempts == ["modern", "legacy", "legacy"]


def test_relative_voice_paths_resolve_against_the_data_root() -> None:
    """Arelis is launched from the Start menu as often as from a terminal, so a
    relative path cannot mean "wherever the shell happened to be".

    The data root and not the install directory, which used to be the same assertion: in a
    checkout both are the repository, so nothing distinguished them. They differ once
    Arelis is installed, and only one answer survives that. Voices are downloaded after
    install, into a per-user directory; resolving them under the program instead would
    point at a directory the installer owns and a standard user cannot write to.
    """
    from arelis.paths import user_data_dir
    from arelis.voice.tts import TextToSpeech

    tts = TextToSpeech({"voice": {"tts": {"voice_model": "models/piper/x.onnx"}}})
    assert Path(tts.voice_model).is_absolute()
    assert Path(tts.voice_model).is_relative_to(user_data_dir())


@pytest.mark.asyncio
async def test_each_sentence_is_announced_as_its_own_clip(tmp_path) -> None:
    """Sentence at a time is what lets her start talking a second after the
    answer lands, and what makes interrupting her cheap."""
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.speak_enabled = True
    written: list[str] = []

    class _FakeTTS:
        def problem(self) -> None:
            return None

        async def synthesize(self, text: str, out) -> Path:
            written.append(text)
            return _fake_clip(Path(out))

    service.tts = _FakeTTS()
    service._out_dir = tmp_path
    events = await _collect(
        bus,
        bus.publish(
            Event(EventType.VOICE_SPEAK, {"text": "First sentence. Second sentence."})
        ),
    )
    clips = [e for e in events if e.type == EventType.VOICE_AUDIO_READY]
    assert written == ["First sentence.", "Second sentence."]
    assert len(clips) == 2
    assert clips[0].payload["final"] is False
    assert clips[-1].payload["final"] is True
    # One utterance id across the reply, so cancelling drops the whole thing.
    assert len({c.payload["utterance"] for c in clips}) == 1


# --------------------------------------------------------------------------
# The composer: two toggles, and speech that can be interrupted
# --------------------------------------------------------------------------


def test_ack_wake_says_listening_on_the_composer(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    try:
        stage.set_voice_available(True)
        stage.set_idle_mode(False)
        stage.ack_wake()
        assert stage.conversation_btn.isChecked()
        assert stage.input.placeholderText() == "listening"
        assert stage._wake_acking
        stage._end_wake_ack()
        # Still in the call: the box says listening, not the typed-chat prompt.
        assert stage.input.placeholderText() == "listening"
        assert not stage._wake_acking
    finally:
        stage.deleteLater()


def test_composer_says_listening_while_conversing(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    try:
        stage.set_voice_available(True)
        stage.set_idle_mode(False)
        stage.set_conversing(True)
        assert stage.input.placeholderText() == "listening"
        stage.set_speaking(True)
        assert "talking" in stage.input.placeholderText()
        stage.set_speaking(False)
        stage.set_conversing(False)
        assert stage.input.placeholderText() == "message Arelis…"
    finally:
        stage.deleteLater()


def test_ack_wake_says_listening_on_the_orbit(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    try:
        stage.set_voice_available(True)
        stage.set_idle_mode(True)
        stage.ack_wake()
        assert stage.chat.empty.listen_word.text() == "listening"
        stage._end_wake_ack()
        assert "talking" in stage.chat.empty.listen_word.text()
    finally:
        stage.deleteLater()


def test_voice_trace_wake_lines_write_when_debug_is_off(tmp_path) -> None:
    from arelis.voice.telemetry import VoiceTrace

    trace = VoiceTrace(False, log_dir=tmp_path)
    trace.record("enter", mode="wake")
    trace.record_wake("wake_heard", matched=True, engine="whisper", heard="hey arelis")
    assert trace.recent()
    assert any("wake_heard" in line for line in trace.recent())
    assert not any("enter" in line and "wake_heard" not in line for line in trace.recent())
    log_file = tmp_path / "voice.log"
    assert log_file.is_file()
    text = log_file.read_text(encoding="utf-8")
    assert "wake_heard" in text
    assert "matched=1" in text
    trace.record_always("barge_in", as_turn=1)
    assert any("barge_in" in line for line in trace.recent())
    assert "barge_in" in log_file.read_text(encoding="utf-8")


def test_voice_controls_are_hidden_when_voice_is_off(qt_app) -> None:
    """An affordance for a switched-off feature is noise."""
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    stage.show()
    assert not stage.mic_btn.isVisible()
    assert not stage.conversation_btn.isVisible()


def test_missing_hardware_is_shown_and_explained(qt_app) -> None:
    """Voice on but unusable is different from voice off: the user asked for
    this and is owed a reason, so the button stays visible and disabled."""
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    stage.show()
    stage.set_idle_mode(False)
    stage.set_voice_available(False, "No microphone was found.")
    assert stage.mic_btn.isVisible()
    assert not stage.mic_btn.isEnabled()
    assert "microphone" in stage.mic_btn.toolTip()


def test_the_explanation_survives_leaving_idle(qt_app) -> None:
    """The order above is the reverse of the application's own.

    ArelisWindow reports the hardware while it wires voice up, and leaves idle afterwards.
    In that order set_idle_mode rebuilt the composer last, and it decided the buttons'
    visibility from availability alone -- so a machine with no microphone showed the
    disabled control with its reason for exactly as long as the window stayed idle, then
    hid it. Only a machine without a microphone can see that, which is why CI found it and
    months of use did not.
    """
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    stage.show()
    stage.set_voice_available(False, "No microphone was found.")
    stage.set_idle_mode(False)
    assert stage.mic_btn.isVisible()
    assert not stage.mic_btn.isEnabled()
    assert "microphone" in stage.mic_btn.toolTip()


def test_only_one_voice_mode_can_be_on(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    stage.set_voice_available(True)
    modes: list[tuple[str, bool]] = []
    stage.dictate_toggled.connect(lambda on: modes.append(("dictate", on)))
    stage.conversation_toggled.connect(lambda on: modes.append(("conversation", on)))

    stage.mic_btn.click()
    stage.conversation_btn.click()
    assert not stage.mic_btn.isChecked()
    assert stage.conversation_btn.isChecked()
    assert modes == [("dictate", True), ("dictate", False), ("conversation", True)]


def test_dictation_lands_in_the_composer_unsent(qt_app) -> None:
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    sent: list[str] = []
    stage.submitted.connect(lambda text, role, attachments=None: sent.append(text))
    stage.insert_dictation("the first half of an idea")
    stage.insert_dictation("and the second half")
    assert stage.input.text() == "the first half of an idea and the second half"
    assert sent == []


def test_escape_reaches_playback_after_the_turn_has_ended(qt_app) -> None:
    """ASSISTANT_DONE clears busy while she is still talking. Gating stop on
    busy alone left no way to shut her up."""
    from arelis.ui.panels.conversation import ConversationStage

    stage = ConversationStage()
    stops: list[int] = []
    stage.stop_requested.connect(lambda: stops.append(1))

    stage.set_busy(False)
    stage._stop()
    assert stops == []

    stage.set_speaking(True)
    stage._stop()
    assert stops == [1]


def test_a_cancelled_utterance_drops_the_clips_still_being_made(qt_app, tmp_path) -> None:
    """Synthesis of sentence four lands after the user has already cut off
    sentence two. Playing it would restart speech they just stopped."""
    from arelis.ui.audio import SpeechPlayer

    player = SpeechPlayer()
    if not player.available():
        pytest.skip("QtMultimedia has no playback backend here")
    clip = _fake_clip(tmp_path / "s.wav")
    advanced: list[int] = []
    player._advance = lambda: advanced.append(1)  # type: ignore[method-assign]

    player.enqueue(clip, 5)
    assert advanced == [1]
    player.stop()
    player.enqueue(clip, 5)
    assert advanced == [1], "a clip from a cancelled reply must not be played"


# --------------------------------------------------------------------------
# Conversation mode, driven by synthetic audio instead of a microphone
# --------------------------------------------------------------------------


class _FakeRecorder(QObject):
    """Stands in for MicRecorder without touching an audio device."""

    level = Signal(float)
    frames = Signal(bytes)
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.requested_rate = 16000
        self.sample_rate = 16000
        self.channels = 1
        self.started = 0
        self._buffer = bytearray()
        self._recording = False

    def problem(self):
        return None

    def device_name(self) -> str:
        return "fake"

    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> bool:
        self._recording = True
        self.started += 1
        return True

    def stop(self) -> bytes:
        self._recording = False
        return self.take()

    def take(self) -> bytes:
        pcm = bytes(self._buffer)
        self._buffer.clear()
        return pcm

    def keep_last_ms(self, ms: int) -> None:
        if ms <= 0:
            self._buffer.clear()
            return
        keep = max(0, int(self.sample_rate * (ms / 1000.0)) * 2)
        if len(self._buffer) > keep:
            self._buffer[:] = self._buffer[-keep:]

    def peek(self) -> bytes:
        return bytes(self._buffer)

    def push(self, pcm: bytes, *, block_ms: int = 100) -> None:
        block = int(self.sample_rate * block_ms / 1000) * 2
        for start in range(0, len(pcm), block):
            chunk = pcm[start : start + block]
            self._buffer.extend(chunk)
            self.frames.emit(chunk)


def _controller(qt_app):
    from arelis.ui.voice_control import VoiceController

    controller = VoiceController(_config())
    recorder = _FakeRecorder(controller)
    controller.recorder = recorder
    recorder.frames.connect(controller._on_frames)
    return controller, recorder


def test_a_pause_sends_the_utterance_hands_free(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    sent: list[tuple[bytes, str]] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append((pcm, deliver)))

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert len(sent) == 1
    assert sent[0][1] == "turn"
    assert len(sent[0][0]) > 0


def test_dictation_keeps_listening_through_a_pause(qt_app) -> None:
    """The whole reason dictation exists: pauses are thinking, not the end."""
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_dictate(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    recorder.push(_tone(1.0) + _silence(1.4))
    assert sent == ["dictate", "dictate"]
    assert controller.mode() == "dictate"
    assert recorder.is_recording()


def test_a_second_utterance_is_not_stacked_on_a_running_turn(qt_app) -> None:
    """One turn at a time is an orchestrator invariant. Queueing speech the
    user has already forgotten saying is worse than dropping it. Mid-turn
    speech is control so stop can land; it is not a second ask.
    """
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    controller.notify_turn_started()
    recorder.push(_tone(1.0) + _silence(1.4))
    assert sent == ["turn", "control"]


def test_listening_resumes_only_after_she_stops_talking(qt_app) -> None:
    """Reopening the mic while the speaker is still going would capture her own
    voice as the next question."""
    controller, recorder = _controller(qt_app)
    listening: list[bool] = []
    controller.listening_changed.connect(listening.append)

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert listening[-1] is False

    controller.notify_turn_started()
    controller.notify_speaking(True)
    controller.notify_turn_finished()
    assert listening[-1] is False, "she is still speaking"

    controller.notify_speaking(False)
    assert listening[-1] is True


def test_talking_over_her_cuts_her_off(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    interrupts: list[int] = []
    controller.barge_in.connect(lambda: interrupts.append(1))

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    controller.notify_speaking(True)
    recorder.push(_tone(0.6))
    assert interrupts == [1]


def test_barge_in_can_be_turned_off_for_speakers(qt_app) -> None:
    """Without a headset her own voice comes back through the microphone and
    she interrupts herself."""
    from arelis.ui.voice_control import VoiceController

    config = _config(conversation={"barge_in": False})
    controller = VoiceController(config)
    recorder = _FakeRecorder(controller)
    controller.recorder = recorder
    recorder.frames.connect(controller._on_frames)
    interrupts: list[int] = []
    controller.barge_in.connect(lambda: interrupts.append(1))

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    controller.notify_speaking(True)
    recorder.push(_tone(0.6))
    assert interrupts == []


def test_a_misclick_is_not_sent(qt_app) -> None:
    """A fraction of a second of noise makes Whisper hallucinate "thank you",
    which then costs a model turn."""
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_dictate(True)
    recorder.push(_tone(0.1))
    controller.set_dictate(False)
    assert sent == []


def test_turning_dictation_off_flushes_what_was_said(qt_app) -> None:
    from PySide6.QtCore import QCoreApplication

    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_dictate(True)
    recorder.push(_tone(1.0))
    controller.set_dictate(False)
    assert sent == ["dictate"]
    # Leaving dictate resumes always-listen wake mode.
    QCoreApplication.processEvents()
    assert controller.mode() == "wake"


def test_switching_modes_closes_the_previous_one(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    controller.set_dictate(True)
    assert controller.mode() == "dictate"
    controller.set_conversation(True)
    assert controller.mode() == "conversation"
    controller.stop_all()
    assert controller.mode() == "off"
    assert not recorder.is_recording()


# --------------------------------------------------------------------------
# The window: spoken words have to appear as a message
# --------------------------------------------------------------------------


def test_a_spoken_message_is_shown_and_holds_the_composer(qt_app) -> None:
    """A typed message is painted by the submit handler before it is published.
    A spoken one has no such moment, and the turn it starts must still disable
    the composer until a terminal event arrives."""
    from arelis.ui.app import ArelisWindow, BusBridge

    config = {
        "ui": {"window_title": "Arelis", "default_width": 800, "default_height": 600},
        "router": {"default_role": "fast"},
        "models": {"fast": "mock"},
        "voice": {"enabled": False},
    }
    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), EventBus())
    try:
        window._on_event(
            Event(EventType.USER_MESSAGE, {"text": "how far is Vega", "source": "voice"})
        )
        assert "how far is Vega" in window.chat.view.toPlainText()
        assert window._turn_busy

        window._on_event(Event(EventType.ASSISTANT_DONE, {"text": "About 25 light years."}))
        assert not window._turn_busy
    finally:
        window.loop.close()


def test_conversation_keeps_listening_when_nothing_was_heard(qt_app) -> None:
    """An utterance that never becomes a turn produces no terminal event. The
    controller used to wait for one anyway, dropping every later pause as
    "still working on the last one" until voice was toggled off and on."""
    controller, recorder = _controller(qt_app)
    listening: list[bool] = []
    sent: list[str] = []
    controller.listening_changed.connect(listening.append)
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert len(sent) == 1
    assert listening[-1] is False

    # Transcription came back empty: no turn, so nothing else will report in.
    controller.notify_utterance_dropped()
    assert listening[-1] is True

    recorder.push(_tone(1.0) + _silence(1.4))
    assert len(sent) == 2, "the next thing said must still be heard"


def test_a_spoken_physics_verb_does_not_deafen_conversation(qt_app) -> None:
    """Closed verbs skip USER_MESSAGE. Conversation must listen again, not wait."""
    from arelis.ui.app import ArelisWindow, BusBridge

    controller, recorder = _controller(qt_app)
    listening: list[bool] = []
    controller.listening_changed.connect(listening.append)

    config = {
        "ui": {"window_title": "Arelis", "default_width": 800, "default_height": 600},
        "router": {"default_role": "fast"},
        "models": {"fast": "mock"},
        "voice": {"enabled": False},
    }
    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), EventBus())
    try:
        window.voice_controller = controller
        window.conversation.room.set_room("physics", name="Reality")
        controller.set_conversation(True)
        recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
        assert listening[-1] is False
        assert controller.debug_state()["awaiting"] is True

        window._on_event(Event(EventType.PHYSICS_VERB, {"verb": "pause"}))
        assert listening[-1] is True
        assert controller.debug_state()["awaiting"] is False
    finally:
        window.dispose()
        window.hide()
        window.loop.close()


def test_conversation_listen_gate_does_not_depend_on_world_focus(qt_app) -> None:
    """The mic gate is turn/speech/awaiting — not which plate is active."""
    controller, _recorder = _controller(qt_app)
    controller.set_conversation(True)
    assert controller._wants_listening() is True
    assert "focus" not in controller.debug_state()
    controller.notify_turn_started()
    assert controller._wants_listening() is False
    controller.notify_turn_finished()
    assert controller._wants_listening() is True


def test_voice_hotkeys_allowed_when_world_is_the_active_window(qt_app, monkeypatch) -> None:
    """World is a native Tool window; conversation chords still belong to Arelis."""
    from PySide6.QtWidgets import QApplication

    from arelis.ui.app import ArelisWindow, BusBridge

    config = {
        "ui": {"window_title": "Arelis", "default_width": 800, "default_height": 600},
        "router": {"default_role": "fast"},
        "voice": {"enabled": False},
    }
    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), EventBus())
    try:
        monkeypatch.setattr(
            QApplication, "activeWindow", lambda *a, **k: window.world_window
        )
        assert window._voice_hotkeys_allowed() is True
        monkeypatch.setattr(QApplication, "activeWindow", lambda *a, **k: None)
        assert window._voice_hotkeys_allowed() is False
    finally:
        window.dispose()
        window.hide()
        window.loop.close()


def test_spoken_goodbye_unlatches_conversation(qt_app) -> None:
    """Hangup is a closed act: the two-arcs toggle drops, wake can listen."""
    from arelis.ui.app import ArelisWindow, BusBridge

    controller, recorder = _controller(qt_app)
    listening: list[bool] = []
    controller.listening_changed.connect(listening.append)

    config = {
        "ui": {"window_title": "Arelis", "default_width": 800, "default_height": 600},
        "router": {"default_role": "fast"},
        "models": {"fast": "mock"},
        "voice": {"enabled": False},
    }
    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), EventBus())
    try:
        window.voice_controller = controller
        controller.set_conversation(True)
        window.conversation.set_conversing(True)
        recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
        assert controller.debug_state()["awaiting"] is True

        window._on_event(Event(EventType.CONVERSATION_END, {"reason": "voice"}))
        assert not window.conversation.conversation_btn.isChecked()
        assert controller.debug_state()["awaiting"] is False
        assert controller.mode != "conversation"
    finally:
        window.dispose()
        window.hide()
        window.loop.close()


def test_confirm_card_keeps_conversation_listening(qt_app) -> None:
    """Conversation mode hears allow / deny. The mic stays on for the card."""
    controller, _recorder = _controller(qt_app)
    listening: list[bool] = []
    controller.listening_changed.connect(listening.append)

    controller.set_conversation(True)
    assert listening[-1] is True

    controller.notify_turn_started()
    controller.notify_confirm_pending(True)
    assert listening[-1] is True

    controller.notify_confirm_pending(False)
    controller.notify_turn_finished()
    assert listening[-1] is True


def test_a_voice_error_does_not_end_someone_elses_turn(qt_app) -> None:
    """Voice ingest runs outside any turn and can fail while a typed turn is
    mid-flight. Treating that as the turn's terminal event re-enabled the
    composer and dismissed a confirm card the agent loop was parked on."""
    from arelis.ui.app import ArelisWindow, BusBridge

    config = {"ui": {}, "router": {"default_role": "fast"}, "voice": {"enabled": False}}
    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), EventBus())
    try:
        window._set_busy(True)
        window._on_event(
            Event(EventType.TOOL_CONFIRM, {"id": "c1", "tool": "workspace", "summary": "write x"})
        )
        # The pending id is the load-bearing part: a dismissed card cannot be
        # answered, and the agent loop is blocked on that answer.
        assert window.conversation.confirm._confirm_id == "c1"

        window._on_event(
            Event(EventType.ERROR, {"message": "Could not transcribe that", "scope": "voice"})
        )
        assert window._turn_busy, "the typed turn is still running"
        assert window.conversation.confirm._confirm_id == "c1", "its confirm must survive"
        assert "Could not transcribe" in window.chat.view.toPlainText()

        # A real turn error still ends the turn.
        window._on_event(Event(EventType.ERROR, {"message": "Ollama is unreachable"}))
        assert not window._turn_busy
    finally:
        window.loop.close()


def test_a_capture_failure_actually_leaves_the_mode(qt_app) -> None:
    """Unchecking the buttons without stopping the controller showed voice as
    off while the microphone was still held open."""
    from arelis.ui.app import ArelisWindow, BusBridge
    from arelis.voice import VoiceService

    config = {
        "ui": {},
        "router": {"default_role": "fast"},
        "voice": {"enabled": True, "stt": {}, "tts": {"enabled": False}, "conversation": {}},
    }
    bus = EventBus()
    window = ArelisWindow(
        config, BusBridge(), asyncio.new_event_loop(), bus, VoiceService(bus, config)
    )
    try:
        if window.voice_controller is None:
            pytest.skip("no input device on this machine")
        # Nothing here reaches the async side, and the loop is not running.
        window.voice = None
        recorder = _FakeRecorder(window.voice_controller)
        window.voice_controller.recorder = recorder
        window.voice_controller.set_conversation(True)
        assert recorder.is_recording()

        window._on_capture_failed("The microphone was unplugged.")
        assert not recorder.is_recording()
        assert window.voice_controller.mode() == "off"
        assert not window.conversation.conversation_btn.isChecked()
    finally:
        window.loop.close()


def test_the_window_builds_with_voice_switched_on(qt_app) -> None:
    """Smoke test for the wiring itself. Voice on means a controller, a player,
    and visible controls get constructed during window setup, none of which the
    other tests exercise together."""
    from arelis.ui.app import ArelisWindow, BusBridge
    from arelis.voice import VoiceService

    config = {
        "ui": {},
        "router": {"default_role": "fast"},
        "voice": {"enabled": True, "stt": {}, "tts": {"voice_model": ""}, "conversation": {}},
    }
    bus = EventBus()
    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), bus, VoiceService(bus, config))
    try:
        window.show()
        window.conversation.set_idle_mode(False)
        # Idle hides the composer mic (orbit is the face). Workbench must show it.
        assert window.conversation.mic_btn.isVisible()
        if window.voice_controller is None:
            assert window.conversation.mic_btn.toolTip()
        else:
            assert window.conversation.mic_btn.isEnabled()
    finally:
        # Not close(): that saves the window layout over the user's own.
        if window.voice_controller is not None:
            window.voice_controller.stop_all()
        window._stop_speech()
        window.hide()
        window.loop.close()


def test_a_typed_message_is_not_painted_twice(qt_app) -> None:
    """The USER_MESSAGE branch has to ignore anything it did not hear."""
    from arelis.ui.app import ArelisWindow, BusBridge

    config = {"ui": {}, "router": {"default_role": "fast"}, "voice": {"enabled": False}}
    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), EventBus())
    try:
        window._on_event(Event(EventType.USER_MESSAGE, {"text": "typed", "role": "fast"}))
        assert "typed" not in window.chat.view.toPlainText()
        assert not window._turn_busy
    finally:
        window.loop.close()


# --------------------------------------------------------------------------
# The chord: Ctrl+M / Ctrl+Shift+M
# --------------------------------------------------------------------------


def _chord(kind, *, shift: bool, autorep: bool = False):
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QKeyEvent

    mods = _Qt.KeyboardModifier.ControlModifier
    if shift:
        mods = mods | _Qt.KeyboardModifier.ShiftModifier
    return QKeyEvent(kind, _Qt.Key.Key_M, mods, "\r", autorep, 1)


def _hotkey_window():
    from arelis.ui.app import ArelisWindow, BusBridge

    config = {"ui": {}, "router": {"default_role": "fast"}, "voice": {"enabled": False}}
    window = ArelisWindow(config, BusBridge(), asyncio.new_event_loop(), EventBus())
    # The real gate reads QApplication.activeWindow(), which is None offscreen.
    window._voice_hotkeys_allowed = lambda: True  # type: ignore[method-assign]
    return window


def test_one_held_chord_latches_conversation_on(qt_app) -> None:
    """Held Ctrl+Shift+M must latch ON and stay there.

    One physical press arrives as ShortcutOverride and then KeyPress, and
    Windows repeats a held chord every few tens of milliseconds once the repeat
    delay expires. Toggling on every delivery meant the mode turned on and
    straight back off, so the orbit looked dead and the mic never opened.
    """
    from PySide6.QtCore import QEvent

    window = _hotkey_window()
    try:
        toggles: list[bool] = []
        window.conversation.conversation_toggled.connect(toggles.append)

        override = _chord(QEvent.Type.ShortcutOverride, shift=True)
        assert window.eventFilter(window, override) is True
        assert override.isAccepted(), "the composer must not receive the m"
        assert toggles == [], "ShortcutOverride must not toggle anything"

        assert window.eventFilter(window, _chord(QEvent.Type.KeyPress, shift=True)) is True
        assert toggles == [True]

        for _ in range(6):
            window.eventFilter(
                window, _chord(QEvent.Type.KeyPress, shift=True, autorep=True)
            )
        assert toggles == [True], "auto-repeat is one press, not seven"
        assert window.conversation.conversation_btn.isChecked()

        # A deliberate second chord, after the echo window, releases the latch.
        window._voice_hotkey_at = 0.0
        window.eventFilter(window, _chord(QEvent.Type.KeyPress, shift=True))
        assert toggles == [True, False]
    finally:
        window.loop.close()


def test_the_shift_chord_does_not_start_dictation(qt_app) -> None:
    """Ctrl+M and Ctrl+Shift+M are different modes and both are exclusive."""
    from PySide6.QtCore import QEvent

    window = _hotkey_window()
    try:
        dictate: list[bool] = []
        talk: list[bool] = []
        window.conversation.dictate_toggled.connect(dictate.append)
        window.conversation.conversation_toggled.connect(talk.append)

        window.eventFilter(window, _chord(QEvent.Type.KeyPress, shift=True))
        assert talk == [True]
        assert dictate == []

        window._voice_hotkey_at = 0.0
        window.eventFilter(window, _chord(QEvent.Type.KeyPress, shift=False))
        assert dictate == [True]
        # Entering dictation drops conversation: one mic, one owner.
        assert talk == [True, False]
        assert window.conversation.mic_btn.isChecked()
        assert not window.conversation.conversation_btn.isChecked()
    finally:
        window.loop.close()


def test_the_latched_mode_is_readable_on_the_empty_orbit(qt_app) -> None:
    """The orbit is the whole UI in idle. A latched mode with no visible mark
    is indistinguishable from a dead hotkey, which is how two hours went."""
    window = _hotkey_window()
    try:
        window._reset_layout()
        idle = window.chat.empty
        off = idle.listen_word.text()

        window._on_voice_mode("conversation")
        talking = idle.listen_word.text()
        assert talking != off
        assert "talking" in talking.lower()
        assert idle.listen_word.property("live") == "true"

        window._on_voice_mode("dictate")
        assert idle.listen_word.text() not in {off, talking}
        assert idle.listen_word.property("live") == "true"

        # Wake is always on in idle, so it reads the same as nothing latched.
        window._on_voice_mode("wake")
        assert idle.listen_word.text() == off
        assert idle.listen_word.property("live") == "false"
    finally:
        window.hide()
        window.loop.close()


# --------------------------------------------------------------------------
# Wake word
# --------------------------------------------------------------------------


def test_match_wake_strips_hey_arelis() -> None:
    from arelis.voice.wake import match_wake

    assert match_wake("Hey Arelis, what is the weather like today") == (
        "what is the weather like today"
    )
    assert match_wake("hey airelyse what's up") == "what's up"
    assert match_wake("Hey Airelease, hello") == "hello"
    assert match_wake("Hey Arelis") == ""
    assert match_wake("Hey Arelis.") == ""
    assert match_wake("hay arelis, hello") == "hello"
    assert match_wake("what is the weather") is None
    assert match_wake("") is None


def test_match_wake_requires_hey() -> None:
    from arelis.voice.wake import classify_wake, match_wake

    # Bare name and casual greetings must not wake (Discord / room talk).
    assert match_wake("Arelis") is None
    assert match_wake("arelis. What is the difficulty with using wake words?") is None
    assert match_wake("Airelyse, what's up") is None
    assert match_wake("Hi Arelis") is None
    assert match_wake("Okay Arelis") is None
    assert match_wake("or Ellis, can you hear me") is None
    # Mid-clip "pay" is a verb, not a wake greeting.
    assert match_wake("I need to pay Aurelis later") is None
    # Double wake must not become a user turn.
    assert match_wake("Hey Arelis. Hey Arelis.") == ""
    hit = classify_wake("Hey Arelis")
    assert hit.matched and hit.remainder == ""
    miss = classify_wake("Arelis")
    assert not miss.matched
    weather = classify_wake("what is the weather")
    assert not weather.matched


def test_match_wake_leading_filler_and_mid_clip() -> None:
    from arelis.voice.wake import match_wake

    # Whisper prepended "and" — still needs Hey.
    assert match_wake("and hey arelis. Send a text message to my wife") == (
        "Send a text message to my wife"
    )
    assert match_wake("and arelis. Send a text message to my wife") is None
    # Long hallucination then a real compound wake (Aurelis spelling).
    heard = (
        "Available for peeking over the air balloon reactor. "
        "Hey, Aurelis. What's the weather"
    )
    assert match_wake(heard) == "What's the weather"
    # Bare name later in a clip is not a wake (Discord said "Arelis").
    assert match_wake("yeah Arelis is the name of the app") is None
    # Repeated name at the end after a command.
    assert match_wake(
        "and hey arelis. Send a text to my wife. Arelis. Arelis."
    ) == "Send a text to my wife"


def test_match_wake_accepts_whisper_arrelis() -> None:
    """Live clips: Whisper wrote Arrelis / Pay a relus and the list said no."""
    from arelis.voice.wake import classify_wake, match_wake

    assert match_wake("Hey, Arrelis") == ""
    assert match_wake("Hey, Arrelis. How are you today?") == "How are you today?"
    assert match_wake("Pay Arellis") == ""
    assert match_wake("Pay a relus") == ""
    assert match_wake("Hey, Arrelas") == ""
    assert match_wake("Hey, Aurelis") == ""
    hit = classify_wake("Hey, Arrelis")
    assert hit.matched and hit.remainder == ""


def test_looks_like_prompt_echo() -> None:
    from arelis.voice.stt import looks_like_prompt_echo

    long_prompt = "Hey Arelis. Arelis, Ollama, ComfyUI, Whisper, astrophysics."
    short_prompt = "Hey Arelis."
    # Jargon dump from the old long prompt — scrub. "metastrophysics" is a
    # deliberate near-miss: a hallucinated word that still contains a prompt
    # term has to count as a hit, or noisy clips slip through the filter.
    assert looks_like_prompt_echo(
        "metastrophysics. Arelis, Ollama, ComfyUI, Whisper,",
        long_prompt,
    )
    assert looks_like_prompt_echo("Ollama, ComfyUI, Whisper", long_prompt)
    # Bare wake must NEVER be scrubbed (this is what broke wake after the
    # prompt-echo filter landed).
    assert not looks_like_prompt_echo("Hey Arelis.", short_prompt)
    assert not looks_like_prompt_echo("Hey Arelis", long_prompt)
    assert not looks_like_prompt_echo("Arelis", short_prompt)
    assert not looks_like_prompt_echo("Airelyse", long_prompt)
    assert not looks_like_prompt_echo("open x.com please", long_prompt)
    assert not looks_like_prompt_echo("What's the weather outside?", long_prompt)
    # Wake-only prompt has no jargon — cannot false-positive on wake clips.
    assert not looks_like_prompt_echo("Hey Arelis. Hey Arelis.", short_prompt)


def test_sherpa_all_caps_is_softened() -> None:
    from arelis.voice.stt import soften_stt_case

    assert soften_stt_case("WHAT IS SEVENTEEN TIMES NINETEEN") == (
        "What is seventeen times nineteen"
    )
    assert soften_stt_case("hello there") == "hello there"


def _sherpa_pack(root) -> None:
    pack = root / "sherpa-onnx-streaming-zipformer-en-2023-06-26"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "tokens.txt").write_text("a\n", encoding="utf-8")
    for part in ("encoder", "decoder", "joiner"):
        (pack / f"{part}-epoch-99-avg-1-chunk-16-left-128.onnx").write_bytes(b"x")


def _sherpa_stt(tmp_path, monkeypatch):
    from arelis.voice.stt import SpeechToText

    _sherpa_pack(tmp_path)
    stt = SpeechToText(
        {
            "voice": {
                "stt": {
                    "backend": "sherpa",
                    "model_dir": str(tmp_path),
                    "allow_download": False,
                }
            }
        }
    )
    monkeypatch.setattr(
        "arelis.voice.sherpa_stt.sherpa_package_available", lambda: True
    )
    monkeypatch.setattr(stt, "_whisper_installed", lambda: True)
    return stt


def test_wake_uses_whisper_while_turns_use_sherpa(tmp_path, monkeypatch) -> None:
    """Zipformer invents openers on one-phrase clips, which costs a wake."""
    stt = _sherpa_stt(tmp_path, monkeypatch)
    assert stt.resolved_backend(purpose="wake") == "faster-whisper"
    assert stt.resolved_backend(purpose="turn") == "sherpa"
    assert stt.resolved_backend(purpose="dictate") == "sherpa"


def test_a_wake_clip_does_not_pin_later_turns_to_whisper(
    tmp_path, monkeypatch
) -> None:
    """Idle wake loads Whisper. Conversation must still be heard by Sherpa.

    The backend was picked from whichever weights happened to be in memory, so
    the first "Hey Arelis" quietly demoted every conversation turn for the rest
    of the session to the model Sherpa was installed to replace.
    """
    stt = _sherpa_stt(tmp_path, monkeypatch)
    assert stt.resolved_backend(purpose="wake") == "faster-whisper"
    stt._model = object()  # Whisper weights now resident, as after a wake clip.
    assert stt.resolved_backend(purpose="turn") == "sherpa"
    assert stt.resolved_backend(purpose="wake") == "faster-whisper"


def test_scrub_transcript_strips_hallucination_and_dupes() -> None:
    from arelis.voice.stt import scrub_transcript

    assert scrub_transcript("are you ready? Alright, thank you.") == (
        "Alright, thank you"
    )
    assert scrub_transcript(
        "What's the weather like outside? What's the weather like outside?"
    ) == "What's the weather like outside"
    assert scrub_transcript(
        "I, I, I I, I, I'm, I'm, I'm, I'm I'm a soldier"
    ) == ""
    assert scrub_transcript(
        "I'm going to kill you, I'm going to kill you. Ok, stop"
    ) == "Ok, stop"
    assert scrub_transcript(
        "I'm going to have a call with you in the office. "
        "I'm going to be the last one in the office. All right, stop"
    ) == "All right, stop"


def test_scrub_transcript_repairs_mail_stt() -> None:
    from arelis.voice.stt import repair_stt_mail_words, scrub_transcript

    assert repair_stt_mail_words("Check your in box") == "Check your inbox"
    assert repair_stt_mail_words("any new emiles today") == "any new emails today"
    assert repair_stt_mail_words("Did you get any new emile") == (
        "Did you get any new email"
    )
    assert repair_stt_mail_words("access to my emil for sure") == (
        "access to my email for sure"
    )
    assert scrub_transcript("Check your in box") == "Check your inbox"


@pytest.mark.asyncio
async def test_superseded_wake_skips_whisper(tmp_path) -> None:
    """Ambient wake jobs must not hold the STT lock after conversation starts."""
    bus = EventBus()
    service = VoiceService(bus, _config())
    calls: list[str] = []

    class _CountingSTT(_FakeSTT):
        async def transcribe(self, path, *, proceed=None, purpose: str = "turn") -> str:
            if proceed is not None and not proceed():
                return ""
            calls.append(str(path))
            return self.text

    service.stt = _CountingSTT("Hey Arelis, hi")
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"x")
    text = await service.ingest_audio(
        clip, deliver="wake", proceed=lambda: False
    )
    assert text == ""
    assert calls == []


def test_wake_listen_emits_wake_deliver(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.start_wake()
    assert controller.mode() == "wake"
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert sent == ["wake"]


def test_conversation_stays_on_when_mic_resume_fails(qt_app) -> None:
    """A blipped mic after Stop must not drop conversation into whisper wake."""
    controller, recorder = _controller(qt_app)
    controller.set_conversation(True)
    assert controller.mode() == "conversation"
    controller.notify_turn_started()
    recorder._recording = False
    recorder.start = lambda: False  # type: ignore[method-assign]
    controller.notify_turn_finished()
    assert controller.mode() == "conversation"


def test_leaving_conversation_resumes_wake_listen(qt_app) -> None:
    from PySide6.QtCore import QCoreApplication

    controller, _recorder = _controller(qt_app)
    controller.set_conversation(True)
    assert controller.mode() == "conversation"
    controller.set_conversation(False)
    # start_wake is deferred on a zero timer
    QCoreApplication.processEvents()
    assert controller.mode() == "wake"


def test_wake_is_paused_during_dictate(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))
    controller.start_wake()
    controller.set_dictate(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert sent == ["dictate"]
    assert controller.mode() == "dictate"


@pytest.mark.asyncio
async def test_wake_ingest_does_not_publish_a_transcript(tmp_path) -> None:
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.stt = _FakeSTT("Hey Arelis, hello")
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"x")
    events = await _collect(bus, service.ingest_audio(clip, deliver="wake"))
    assert EventType.VOICE_TRANSCRIPT not in [e.type for e in events]


# --------------------------------------------------------------------------
# The reply, not the clip: what conversation mode actually waits for
#
# Every test below pins one leg of the same defect. ASSISTANT_DONE is published
# about a second before Piper renders the first sentence, and clips arrive one
# at a time after that, so neither "the turn ended" nor "the player went quiet"
# means she has finished talking. Treating either as the end reopened the
# microphone while she was still speaking, her own voice came back through the
# speakers as the next question, and conversation died on the second exchange.
# --------------------------------------------------------------------------


class _SpyController:
    """Records what the window tells the voice controller, in order."""

    def __init__(self) -> None:
        from arelis.voice.telemetry import VoiceTrace

        self.calls: list[tuple[str, Any]] = []
        self.trace = VoiceTrace(False)

    def notify_speaking(self, speaking: bool) -> None:
        self.calls.append(("speaking", speaking))

    def notify_confirm_pending(self, pending: bool) -> None:
        self.calls.append(("confirm_pending", pending))

    def notify_turn_started(self) -> None:
        self.calls.append(("turn_started", None))

    def notify_turn_finished(self) -> None:
        self.calls.append(("turn_finished", None))

    def notify_utterance_dropped(self) -> None:
        self.calls.append(("utterance_dropped", None))

    def debug_state(self) -> dict[str, Any]:
        return {}

    def stop_all(self) -> None:
        self.calls.append(("stop_all", None))

    def said(self, name: str) -> list[Any]:
        return [value for call, value in self.calls if call == name]


def _speech_window(spy: _SpyController):
    """A window with playback wired up and no microphone, plus a spy controller."""
    from arelis.ui.app import ArelisWindow, BusBridge

    config = {
        "ui": {},
        "router": {"default_role": "fast"},
        "voice": {
            "enabled": True,
            "stt": {"enabled": False},
            "tts": {"enabled": True, "voice_model": ""},
            "conversation": {},
        },
    }
    bus = EventBus()
    window = ArelisWindow(
        config, BusBridge(), asyncio.new_event_loop(), bus, VoiceService(bus, config)
    )
    window.voice_controller = spy  # type: ignore[assignment]
    window.voice.speak_enabled = True
    return window


def test_the_microphone_is_held_across_the_gap_before_she_starts_talking(qt_app) -> None:
    """The headline defect. Piper needs about a second for the first sentence,
    and in that second the turn is over and nothing is playing, which used to
    read as "she has finished" and reopen the microphone in time to record her
    own opening words."""
    spy = _SpyController()
    window = _speech_window(spy)
    try:
        window._on_event(Event(EventType.ASSISTANT_DONE, {"text": "Hello.", "speak": True}))
        assert window._speech_expected
        assert spy.said("speaking")[-1] is True
        # Order is the whole point: both feed the same decision, so clearing
        # busy first leaves a window in which nothing is pending.
        assert spy.calls.index(("speaking", True)) < spy.calls.index(("turn_finished", None))
    finally:
        window.loop.close()


def test_the_queue_draining_between_sentences_is_not_the_end_of_the_reply(qt_app) -> None:
    """Sentence one can finish playing before sentence two has been rendered."""
    spy = _SpyController()
    window = _speech_window(spy)
    try:
        window._on_event(Event(EventType.ASSISTANT_DONE, {"text": "One. Two.", "speak": True}))
        window._on_playback(True)
        window._on_playback(False)
        assert spy.said("speaking")[-1] is True, "the next sentence is still in Piper"

        window._on_event(_speech_done(clips=2))
        assert spy.said("speaking")[-1] is False
        assert not window._speech_expected
    finally:
        window.loop.close()


def test_synthesis_finishing_is_not_the_end_while_a_clip_is_still_playing(qt_app) -> None:
    spy = _SpyController()
    window = _speech_window(spy)
    try:
        window._on_event(Event(EventType.ASSISTANT_DONE, {"text": "One.", "speak": True}))
        window._on_playback(True)
        window._on_event(_speech_done(clips=1))
        assert spy.said("speaking")[-1] is True, "the last clip is still audible"
        window._on_playback(False)
        assert spy.said("speaking")[-1] is False
    finally:
        window.loop.close()


def test_a_turn_with_no_spoken_reply_does_not_hold_the_microphone(qt_app) -> None:
    """Slash commands and the cancel notice publish ASSISTANT_DONE with no
    VOICE_SPEAK behind it, so nothing would ever report the speech finished."""
    spy = _SpyController()
    window = _speech_window(spy)
    try:
        window._on_event(Event(EventType.ASSISTANT_DONE, {"text": "Stopped."}))
        assert not window._speech_expected
        assert True not in spy.said("speaking")
    finally:
        window.loop.close()


def test_speech_that_never_reports_finishing_gives_the_microphone_back(qt_app) -> None:
    """A lost terminal event must cost a pause, not conversation mode."""
    spy = _SpyController()
    window = _speech_window(spy)
    try:
        window._on_event(Event(EventType.ASSISTANT_DONE, {"text": "Hello.", "speak": True}))
        assert window._speech_expected
        window._on_speech_watchdog()
        assert not window._speech_expected
        assert spy.said("speaking")[-1] is False
    finally:
        window.loop.close()


def test_speech_watchdog_clears_has_work_only_stuck(qt_app) -> None:
    """Last-clip error can leave has_work True with expected/playing False."""
    spy = _SpyController()
    window = _speech_window(spy)

    class _StuckPlayer:
        def __init__(self) -> None:
            self._work = True

        def has_work(self) -> bool:
            return self._work

        def stop(self) -> None:
            self._work = False

        def is_playing(self) -> bool:
            return False

    try:
        window.speech_player = _StuckPlayer()  # type: ignore[assignment]
        window._speech_expected = False
        window._speech_playing = False
        window._update_speaking()
        assert spy.said("speaking")[-1] is True
        window._on_speech_watchdog()
        assert spy.said("speaking")[-1] is False
    finally:
        window.loop.close()


def _speech_done(*, clips: int) -> Event:
    return Event(EventType.VOICE_SPEECH_DONE, {"utterance": 1, "clips": clips})


@pytest.mark.asyncio
async def test_a_missing_piper_does_not_leave_conversation_waiting(tmp_path) -> None:
    """Every path past the speak gate has to report itself finished. The UI goes
    deaf the moment the answer lands and only the terminal event brings it back,
    so a synthesis that gives up quietly is indistinguishable from one that is
    still going, forever."""
    bus = EventBus()
    service = VoiceService(bus, _config())  # voice_model is "", so piper cannot run
    service.speak_enabled = True
    service._out_dir = tmp_path
    events = await _collect(
        bus, bus.publish(Event(EventType.VOICE_SPEAK, {"text": "Hello there."}))
    )
    kinds = [e.type for e in events]
    assert EventType.VOICE_AUDIO_READY not in kinds
    assert kinds.count(EventType.VOICE_SPEECH_DONE) == 1


@pytest.mark.asyncio
async def test_speech_reports_finished_after_the_last_clip(tmp_path) -> None:
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.speak_enabled = True
    service._out_dir = tmp_path

    class _FakeTTS:
        def problem(self) -> None:
            return None

        async def synthesize(self, text: str, out) -> Path:
            return _fake_clip(Path(out))

    service.tts = _FakeTTS()
    events = await _collect(
        bus, bus.publish(Event(EventType.VOICE_SPEAK, {"text": "One. Two."}))
    )
    kinds = [e.type for e in events]
    assert kinds.count(EventType.VOICE_SPEECH_DONE) == 1
    last_clip = max(i for i, k in enumerate(kinds) if k == EventType.VOICE_AUDIO_READY)
    assert kinds.index(EventType.VOICE_SPEECH_DONE) > last_clip


@pytest.mark.asyncio
async def test_speech_is_not_reported_at_all_when_she_was_never_going_to_talk(
    tmp_path,
) -> None:
    """Outside conversation mode there is no speech to wait for, so publishing a
    terminal event for one would arm a wait that nothing asked for."""
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.speak_enabled = False
    service._out_dir = tmp_path
    events = await _collect(
        bus, bus.publish(Event(EventType.VOICE_SPEAK, {"text": "Hello."}))
    )
    assert EventType.VOICE_SPEECH_DONE not in [e.type for e in events]


@pytest.mark.asyncio
async def test_being_interrupted_stops_rendering_the_rest_of_the_answer(tmp_path) -> None:
    """Dropping the queued clips is only half of it. The service would keep
    synthesizing sentences nobody will hear, and conversation mode stays deaf
    until that loop reaches its terminal event."""
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.speak_enabled = True
    service._out_dir = tmp_path
    written: list[str] = []

    class _InterruptedTTS:
        def problem(self) -> None:
            return None

        async def synthesize(self, text: str, out) -> Path:
            written.append(text)
            service.cancel_speech()  # the user talks over the first sentence
            return _fake_clip(Path(out))

    service.tts = _InterruptedTTS()
    events = await _collect(
        bus, bus.publish(Event(EventType.VOICE_SPEAK, {"text": "One. Two. Three."}))
    )
    assert written == ["One."]
    assert EventType.VOICE_SPEECH_DONE in [e.type for e in events]


@pytest.mark.asyncio
async def test_streaming_deltas_speak_completed_sentences_before_voice_speak(
    tmp_path,
) -> None:
    """Audio should start on stable sentences while the answer is still growing."""
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.speak_enabled = True
    service._out_dir = tmp_path
    written: list[str] = []

    class _FakeTTS:
        def problem(self) -> None:
            return None

        async def synthesize(self, text: str, out) -> Path:
            written.append(text)
            return _fake_clip(Path(out))

    service.tts = _FakeTTS()
    events = await _collect(
        bus,
        _stream_then_speak(
            bus,
            service,
            deltas=[
                "First sentence. ",
                "Second sentence. ",
                "Trailing fragment",
            ],
            final="First sentence. Second sentence. Trailing fragment.",
        ),
    )
    assert written == [
        "First sentence.",
        "Second sentence.",
        "Trailing fragment.",
    ]
    assert [e.type for e in events].count(EventType.VOICE_SPEECH_DONE) == 1
    # Completed sentences must have been synthesized before the terminal speak
    # closed the cycle; the trailing fragment is the finalize-only unit.
    ready = [e for e in events if e.type == EventType.VOICE_AUDIO_READY]
    speak_at = next(
        i for i, e in enumerate(events) if e.type == EventType.VOICE_SPEAK
    )
    assert sum(1 for e in events[:speak_at] if e.type == EventType.VOICE_AUDIO_READY) == 2
    assert len(ready) == 3


@pytest.mark.asyncio
async def test_streaming_retract_drops_preamble_speech(tmp_path) -> None:
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.speak_enabled = True
    service._out_dir = tmp_path
    written: list[str] = []

    class _FakeTTS:
        def problem(self) -> None:
            return None

        async def synthesize(self, text: str, out) -> Path:
            written.append(text)
            return _fake_clip(Path(out))

    service.tts = _FakeTTS()

    async def scenario() -> None:
        for chunk in (
            "Looking that up. ",
            "One moment. ",
            "Still working",
        ):
            await bus.publish(Event(EventType.ASSISTANT_DELTA, {"text": chunk}))
        await bus.drain()
        await service._await_drain()
        # Trailing fragment is held; the two completed sentences already spoke.
        assert written == ["Looking that up.", "One moment."]

        await bus.publish(Event(EventType.ASSISTANT_RETRACT, {}))
        await bus.drain()
        await service._await_drain()

        written.clear()
        await _stream_then_speak(
            bus,
            service,
            deltas=["Here is the answer. ", "It worked. ", "Truly."],
            final="Here is the answer. It worked. Truly.",
        )

    events = await _collect(bus, scenario())
    assert EventType.VOICE_SPEECH_DONE in [e.type for e in events]
    assert written == ["Here is the answer.", "It worked.", "Truly."]
    # Retract closed one cycle; the real answer closed another.
    assert [e.type for e in events].count(EventType.VOICE_SPEECH_DONE) == 2


@pytest.mark.asyncio
async def test_voice_speak_after_stream_does_not_double_speak(tmp_path) -> None:
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.speak_enabled = True
    service._out_dir = tmp_path
    written: list[str] = []

    class _FakeTTS:
        def problem(self) -> None:
            return None

        async def synthesize(self, text: str, out) -> Path:
            written.append(text)
            return _fake_clip(Path(out))

    service.tts = _FakeTTS()
    events = await _collect(
        bus,
        _stream_then_speak(
            bus,
            service,
            deltas=["Alpha sentence. ", "Beta sentence."],
            final="Alpha sentence. Beta sentence.",
        ),
    )
    assert written == ["Alpha sentence.", "Beta sentence."]
    assert [e.type for e in events].count(EventType.VOICE_SPEECH_DONE) == 1


async def _stream_then_speak(
    bus: EventBus,
    service: VoiceService,
    *,
    deltas: list[str],
    final: str,
) -> None:
    for chunk in deltas:
        await bus.publish(Event(EventType.ASSISTANT_DELTA, {"text": chunk}))
    await bus.drain()
    await service._await_drain()
    await bus.publish(Event(EventType.VOICE_SPEAK, {"text": final}))
    await bus.drain()
    await service._await_drain()


# --------------------------------------------------------------------------
# Conversation survives more than one exchange
# --------------------------------------------------------------------------


def _answer(controller, recorder, *, echo: bool = True) -> None:
    """Play out a whole reply the way the window drives it."""
    controller.notify_turn_started()
    controller.notify_speaking(True)  # the answer landed; a spoken one follows
    controller.notify_turn_finished()
    if echo:
        # On speakers rather than a headset, her own voice arrives back through
        # the microphone as a perfectly good utterance.
        recorder.push(_tone(1.2) + _silence(1.4))
    controller.notify_speaking(False)


def test_three_turns_in_a_row_without_toggling_conversation(qt_app) -> None:
    """The acceptance test for the whole change."""
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_conversation(True)
    for _ in range(3):
        recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
        _answer(controller, recorder)

    assert sent == ["turn", "turn", "turn"]
    assert controller.mode() == "conversation"
    assert controller.listening()


def test_her_own_voice_is_not_sent_as_the_next_question(qt_app) -> None:
    """Without a headset the speakers feed straight back into the microphone.
    Nothing used to stop that becoming a turn, so the second exchange was Arelis
    answering herself and the third was her answering that."""
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert sent == ["turn"]

    controller.notify_turn_started()
    controller.notify_speaking(True)
    controller.notify_turn_finished()
    recorder.push(_tone(1.5) + _silence(1.4))
    assert sent == ["turn"], "that was her own answer coming back"


def test_barge_in_becomes_the_next_turn(qt_app) -> None:
    """Headset: talking over her is the next question, not soup-as-control."""
    controller, recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))
    interrupts: list[int] = []
    controller.barge_in.connect(lambda: interrupts.append(1))

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    controller.notify_turn_started()
    controller.notify_speaking(True)
    controller.notify_turn_finished()
    sent.clear()

    recorder.push(_tone(0.8))  # talking over her
    assert interrupts == [1]
    assert controller.debug_state()["discard_barge"] is True
    controller.notify_speaking(False)  # the window cut playback
    recorder.push(_tone(0.5) + _silence(1.4))

    assert sent == ["turn"], "headset barge-in is the next turn"
    assert controller.debug_state()["discard_barge"] is False


def test_barge_in_as_control_when_speakers(qt_app) -> None:
    """Speakers: mixed clip stays control so her own voice is not a question."""
    from arelis.ui.voice_control import VoiceController

    config = _config(conversation={"barge_in_as_turn": False})
    controller = VoiceController(config)
    recorder = _FakeRecorder(controller)
    controller.recorder = recorder
    recorder.frames.connect(controller._on_frames)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))
    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    controller.notify_turn_started()
    controller.notify_speaking(True)
    controller.notify_turn_finished()
    sent.clear()
    recorder.push(_tone(0.8))
    controller.notify_speaking(False)
    recorder.push(_tone(0.5) + _silence(1.4))
    assert sent == ["control"]


def test_a_lost_utterance_callback_does_not_deafen_conversation(qt_app) -> None:
    """Nothing in the hand-off path is unbounded, but a callback that never
    arrives used to cost the rest of the session rather than a pause."""
    controller, recorder = _controller(qt_app)
    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert not controller.listening()

    controller._on_turn_watchdog()  # what the timer does thirty seconds later
    assert controller.listening()


def test_voice_debug_records_the_state_that_stuck(qt_app, tmp_path) -> None:
    """The point of the trace: reading the last line has to say which of the
    three flags is holding the microphone shut."""
    from arelis.voice.telemetry import VoiceTrace

    controller, recorder = _controller(qt_app)
    controller.trace = VoiceTrace(True, log_dir=tmp_path)

    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    controller.notify_turn_started()
    controller.notify_speaking(True)

    lines = controller.trace.recent()
    assert any("speech_end" in line for line in lines)
    # The last line alone says which flag is holding the microphone shut.
    assert "mode=conversation" in lines[-1]
    assert "listening=0" in lines[-1]
    assert "turn_busy=1" in lines[-1]
    assert "speaking=1" in lines[-1]


def test_a_pause_that_captured_nothing_leaves_the_listening_alone(qt_app) -> None:
    """Nothing was said, so there is no turn to wait for. Going deaf here used
    to need a deferred timer to undo it."""
    controller, _recorder = _controller(qt_app)
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))

    controller.set_conversation(True)
    assert controller.listening()
    controller._on_speech_ended(timed_out=False)  # the buffer is empty
    assert sent == []
    assert controller.listening()


def test_piper_is_asked_for_the_configured_speaking_pace(tmp_path, monkeypatch) -> None:
    from arelis.voice import tts as tts_module

    tts = tts_module.TextToSpeech(
        {"voice": {"tts": {"voice_model": "v.onnx", "length_scale": 0.9}}}
    )
    tts.command = ["piper"]
    seen: list[list[str]] = []

    def fake_run(argv, input=b"", **kwargs):
        seen.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, b"", b"nope")

    monkeypatch.setattr(tts_module.subprocess, "run", fake_run)
    tts._run_piper("hello", tmp_path / "o.wav", "modern", tts.length_scale)
    tts._run_piper("hello", tmp_path / "o.wav", "legacy", tts.length_scale)

    assert "--length-scale" in seen[0]
    assert seen[0][seen[0].index("--length-scale") + 1] == "0.9"
    # The text still has to be the last thing after the separator.
    assert seen[0][-2:] == ["--", "hello"]
    assert "--length_scale" in seen[1]


def test_the_default_pace_passes_no_flag_at_all(tmp_path, monkeypatch) -> None:
    """1.0 is the voice's own pace, and passing a flag for it would be one more
    thing an older piper build could reject."""
    from arelis.voice import tts as tts_module

    tts = tts_module.TextToSpeech(
        {"voice": {"tts": {"voice_model": "v.onnx", "length_scale": 1.0}}}
    )
    assert tts.length_scale is None


@pytest.mark.asyncio
async def test_a_piper_that_rejects_the_speed_flag_still_speaks(tmp_path, monkeypatch) -> None:
    """A comfort setting must never be the reason speech stops working."""
    from arelis.voice import tts as tts_module

    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    (tmp_path / "v.onnx.json").write_text("{}", encoding="utf-8")
    tts = tts_module.TextToSpeech(
        {"voice": {"tts": {"voice_model": str(model), "length_scale": 0.9}}}
    )
    tts.command = ["piper"]
    attempts: list[bool] = []

    def fake_run(argv, input=b"", **kwargs):
        speed = "--length-scale" in argv or "--length_scale" in argv
        attempts.append(speed)
        if speed:
            return subprocess.CompletedProcess(argv, 2, b"", b"unrecognized arguments")
        Path(argv[argv.index("-f") + 1]).write_bytes(b"RIFF")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(tts_module.subprocess, "run", fake_run)
    await tts.synthesize("one", tmp_path / "a.wav")
    await tts.synthesize("two", tmp_path / "b.wav")

    assert attempts[0] is True
    # Remembered, so the rest of the session does not pay for the failed spawn.
    assert attempts[-1] is False
    assert attempts.count(True) == 2, "both argument styles are tried with speed first"


def test_kokoro_rewrites_the_piper_name_spelling() -> None:
    from arelis.voice.kokoro_tts import prepare_kokoro_text

    assert prepare_kokoro_text("Uh-rell-iss can hear you.").startswith("Arelis")
    assert "airelyse" not in prepare_kokoro_text("Airelyse can hear you.").lower()


def test_auto_tts_falls_back_to_piper_when_kokoro_cannot_run(tmp_path) -> None:
    """A missing Kokoro install must not silence conversation mode."""
    from arelis.voice.tts import TextToSpeech

    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    (tmp_path / "v.onnx.json").write_text("{}", encoding="utf-8")
    tts = TextToSpeech(
        {
            "voice": {
                "tts": {
                    "backend": "auto",
                    "voice_model": str(model),
                    "allow_download": False,
                    "kokoro_model": str(tmp_path / "missing.onnx"),
                    "kokoro_voices": str(tmp_path / "missing.bin"),
                }
            }
        }
    )
    tts.command = ["piper"]
    assert not tts._use_kokoro()
    assert tts.problem() is None


@pytest.mark.asyncio
async def test_kokoro_backend_writes_a_wav_without_spawning_piper(
    tmp_path, monkeypatch
) -> None:
    from arelis.voice import tts as tts_module
    from arelis.voice.kokoro_tts import KokoroSynthesizer

    out = tmp_path / "k.wav"

    def fake_synth(self, text, path):
        path.write_bytes(b"RIFFKOKORO")
        return path

    monkeypatch.setattr(KokoroSynthesizer, "problem", lambda self: None)
    monkeypatch.setattr(KokoroSynthesizer, "synthesize", fake_synth)
    tts = tts_module.TextToSpeech(
        {
            "voice": {
                "tts": {
                    "backend": "kokoro",
                    "allow_download": False,
                    "voice_model": "",
                }
            }
        }
    )

    def boom(*args, **kwargs):
        raise AssertionError("Piper must not run when Kokoro succeeds")

    monkeypatch.setattr(tts_module.subprocess, "run", boom)
    written = await tts.synthesize("Hello there.", out)
    assert written.read_bytes() == b"RIFFKOKORO"


def test_closing_a_stream_then_finishing_does_not_duplicate_the_answer(qt_app) -> None:
    """Conversation-mode race: user line arrives while the draft is still open,
    finalizes it via _close_stream, then ASSISTANT_DONE must not append a copy."""
    from arelis.ui.panels.chat import ChatPanel

    panel = ChatPanel()
    panel.begin_assistant()
    panel.append_delta("I can hear you!")
    panel.add_user("Hello? Can you hear me?")
    panel.finish_assistant("I can hear you!")
    text = panel.view.toPlainText()
    assert text.count("I can hear you!") == 1
    assert text.index("I can hear you!") < text.index("Hello? Can you hear me?")


@pytest.mark.asyncio
async def test_bus_mirrors_user_message_before_orchestrator_runs_the_turn() -> None:
    """Wildcard subscribers must run before type-specific ones.

    Otherwise the UI only sees a spoken USER_MESSAGE after the turn finishes,
    which is the ordering that duplicated assistant bubbles in conversation mode.
    """
    bus = EventBus()
    order: list[str] = []

    async def mirror(event: Event) -> None:
        if event.type == EventType.USER_MESSAGE:
            order.append("mirror")

    async def orchestrator(event: Event) -> None:
        order.append("orchestrator")
        await bus.publish(Event(EventType.ASSISTANT_DONE, {"text": "hi"}))

    bus.subscribe(None, mirror)
    bus.subscribe(EventType.USER_MESSAGE, orchestrator)
    events = await _collect(
        bus, bus.publish(Event(EventType.USER_MESSAGE, {"text": "hi", "source": "voice"}))
    )
    assert order == ["mirror", "orchestrator"]
    assert EventType.ASSISTANT_DONE in [e.type for e in events]


@pytest.mark.asyncio
async def test_ingest_strips_a_leading_wake_phrase(tmp_path) -> None:
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.stt = _FakeSTT("Hey Arelis, what is the weather like today")
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"x")
    events = await _collect(bus, service.ingest_audio(clip, strip_wake=True))
    transcripts = [e for e in events if e.type == EventType.VOICE_TRANSCRIPT]
    assert transcripts
    assert transcripts[0].payload["text"] == "what is the weather like today"


@pytest.mark.asyncio
async def test_ingest_drops_a_wake_only_remainder(tmp_path) -> None:
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.stt = _FakeSTT("Hey Arelis")
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"x")
    events = await _collect(bus, service.ingest_audio(clip, strip_wake=True))
    assert EventType.VOICE_TRANSCRIPT not in [e.type for e in events]


@pytest.mark.asyncio
async def test_finish_live_stt_peels_wake() -> None:
    class _FakeBridge:
        def finish(self, timeout: float = 20.0) -> str:
            return "Hey Arelis, lights off"

    bus = EventBus()
    service = VoiceService(bus, _config())
    service._live_bridge = _FakeBridge()
    events = await _collect(bus, service.finish_live_stt(strip_wake=True))
    transcripts = [e for e in events if e.type == EventType.VOICE_TRANSCRIPT]
    assert transcripts
    assert transcripts[0].payload["text"] == "lights off"


def test_start_live_stt_skips_without_sherpa() -> None:
    bus = EventBus()
    service = VoiceService(bus, _config())
    service.stt = _FakeSTT()
    assert service.start_live_stt() is False


def test_smart_turn_incomplete_pause_does_not_end_the_turn(qt_app) -> None:
    class _StubSmartTurn:
        def __init__(self) -> None:
            self.complete_value = False
            self.calls = 0

        def predict(self, pcm, sample_rate=16000, channels=1):
            self.calls += 1
            return {
                "complete": self.complete_value,
                "probability": 0.9 if self.complete_value else 0.1,
            }

    controller, recorder = _controller(qt_app)
    stub = _StubSmartTurn()
    controller._smart_turn = stub
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))
    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert sent == []
    assert stub.calls >= 1
    stub.complete_value = True
    recorder.push(_tone(0.6) + _silence(1.4))
    assert sent == ["turn"]


def test_missing_smart_turn_uses_silence_ms(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    assert controller._smart_turn is None
    sent: list[str] = []
    controller.utterance.connect(lambda pcm, rate, ch, deliver: sent.append(deliver))
    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert sent == ["turn"]


def test_conversation_onset_emits_live_started(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    hits: list[int] = []
    controller.live_started.connect(lambda: hits.append(1))
    controller.set_conversation(True)
    recorder.push(_silence(0.5) + _tone(1.0) + _silence(1.4))
    assert hits == [1]


def test_wake_to_conversation_keeps_the_buffer(qt_app) -> None:
    controller, recorder = _controller(qt_app)
    hits: list[int] = []
    controller.live_started.connect(lambda: hits.append(1))
    controller.start_wake()
    recorder.push(_tone(0.8))
    kept = len(recorder.peek())
    assert kept > 0
    controller.set_conversation(True)
    assert len(recorder.peek()) == kept
    assert hits == [1]
    assert controller.debug_state()["vad"] is True

