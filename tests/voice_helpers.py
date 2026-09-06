"""Shared fakes and helpers for the split voice test modules.

Not collected (no test_ prefix). Copied once from the former test_voice.py.
"""
from __future__ import annotations

import asyncio
import math
import struct
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from arelis.core.bus import EventBus
from arelis.core.events import Event, EventType
from arelis.voice import VoiceService
from arelis.voice.vad import UtteranceDetector


def _config(**overrides: Any) -> dict[str, Any]:
    voice: dict[str, Any] = {
        "enabled": True,
        "keep_recordings": False,
        "stt": {"enabled": True, "model_size": "base", "allow_download": False},
        "tts": {
            "enabled": True,
            "backend": "piper",
            "voice_model": "",
            "max_chars": 0,
            "allow_download": False,
        },
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

def _feed(detector: UtteranceDetector, pcm: bytes, *, block_ms: int = 100) -> list[str]:
    """Feed audio in realistic block sizes and collect what fired."""
    block = int(16000 * block_ms / 1000) * 2
    events = []
    for start in range(0, len(pcm), block):
        event = detector.feed(pcm[start : start + block])
        if event:
            events.append(event)
    return events

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

def _speech_done(*, clips: int) -> Event:
    return Event(EventType.VOICE_SPEECH_DONE, {"utterance": 1, "clips": clips})

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
