"""Microphone capture and speech playback, on the Qt thread.

QtMultimedia rather than sounddevice or pyaudio, for three reasons. PySide6 is
already a hard dependency and QtMultimedia ships inside it, so this costs no new
package. There is no native build step and no PortAudio DLL to ship, which
matters on a Windows/AMD workstation. And Qt owns the main thread here anyway,
so putting audio anywhere else would mean marshalling device callbacks back into
Qt, which is the problem this avoids rather than the one it creates.

The cost is that audio is bound to the Qt thread. Everything crossing to the
async side goes through the bus, the same as every other UI interaction.
"""

from __future__ import annotations

import logging
import time
import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from arelis.core.failure_copy import plain_reason
from arelis.voice.pcm import rms_level

log = logging.getLogger(__name__)

# Loudness samples per second. Matches the mouth follower the face expects.
_LEVEL_HZ = 60.0


def wav_loudness_envelope(path: str | Path) -> np.ndarray | None:
    """RMS loudness of a WAV clip, about 60 samples a second, or None.

    Kokoro and the shared PCM writer both store 16 bit mono WAV. Anything
    that is missing, not a WAV, or too odd to read returns None and never
    raises. Values are scaled by a high percentile so one spike does not
    flatten the rest of the sentence.
    """
    try:
        clip = Path(path)
        if not clip.is_file():
            return None
        with wave.open(str(clip), "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            rate = handle.getframerate()
            raw = handle.readframes(handle.getnframes())
        if rate <= 0 or not raw or channels < 1 or width not in (2, 4):
            return None
        if width == 2:
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        else:
            samples = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2.0**31
        if channels > 1:
            frames = len(samples) // channels
            if frames <= 0:
                return None
            samples = samples[: frames * channels].reshape(frames, channels).mean(axis=1)
        hop = max(1, round(rate / _LEVEL_HZ))
        usable = (len(samples) // hop) * hop
        if usable < hop:
            return None
        block = samples[:usable].reshape(-1, hop)
        rms = np.sqrt(np.mean(block * block, axis=1))
        peak = float(np.percentile(rms, 95))
        if peak < 1e-8:
            return np.zeros(len(rms), dtype=np.float32)
        return np.clip(rms / peak, 0.0, 1.0).astype(np.float32)
    except Exception:
        return None


try:
    from PySide6.QtMultimedia import (
        QAudioFormat,
        QAudioOutput,
        QAudioSource,
        QMediaDevices,
        QMediaPlayer,
    )

    MULTIMEDIA_AVAILABLE = True
except ImportError as exc:  # pragma: no cover - depends on the PySide6 build
    log.warning("QtMultimedia unavailable, voice hardware is disabled: %s", exc)
    MULTIMEDIA_AVAILABLE = False


def list_audio_input_names() -> list[str]:
    if not MULTIMEDIA_AVAILABLE:
        return []
    return [d.description() for d in QMediaDevices.audioInputs() if not d.isNull()]


def list_audio_output_names() -> list[str]:
    if not MULTIMEDIA_AVAILABLE:
        return []
    return [d.description() for d in QMediaDevices.audioOutputs() if not d.isNull()]


def _match_device(devices: list, hint: str):
    if not devices:
        return None
    needle = (hint or "").strip().lower()
    if needle:
        for device in devices:
            if needle in device.description().lower():
                return device
    return None


class MicRecorder(QObject):
    """Captures signed 16 bit mono PCM from an input device.

    Frames are accumulated in memory rather than streamed to disk: a minute of
    16 kHz mono is under two megabytes, and keeping it in a buffer means the
    silence detector can look at the level of what is arriving without racing a
    file writer for the same bytes.
    """

    level = Signal(float)  # 0.0 - 1.0, one per arriving block
    frames = Signal(bytes)  # each block, for callers doing their own analysis
    failed = Signal(str)

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        device_hint: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.requested_rate = sample_rate
        self.device_hint = device_hint
        self.sample_rate = sample_rate
        self.channels = 1
        self._source = None
        self._io = None
        self._buffer = bytearray()
        self._recording = False

    # ------------------------------------------------------------ readiness

    def problem(self) -> str | None:
        """Why recording cannot start, or None when it can."""
        if not MULTIMEDIA_AVAILABLE:
            return "QtMultimedia is not available in this PySide6 build."
        if not QMediaDevices.audioInputs():
            return "No microphone was found. Plug one in or check Windows sound settings."
        return None

    def device_name(self) -> str:
        device = self._device()
        return device.description() if device is not None else ""

    def set_device_hint(self, hint: str) -> None:
        """Switch input device; restarts capture if currently recording."""
        was = self._recording
        buffered = b""
        if was:
            buffered = self.stop()
        self.device_hint = hint or ""
        if was:
            if self.start() and buffered:
                self._buffer.extend(buffered)

    def _device(self):
        if not MULTIMEDIA_AVAILABLE:
            return None
        inputs = QMediaDevices.audioInputs()
        if not inputs:
            return None
        matched = _match_device(inputs, self.device_hint)
        if matched is not None:
            return matched
        default = QMediaDevices.defaultAudioInput()
        return default if not default.isNull() else inputs[0]

    # ------------------------------------------------------------- capture

    def is_recording(self) -> bool:
        return self._recording

    def start(self) -> bool:
        if self._recording:
            return True
        problem = self.problem()
        if problem:
            self.failed.emit(problem)
            return False
        device = self._device()
        if device is None:
            self.failed.emit("No usable input device.")
            return False

        fmt = QAudioFormat()
        fmt.setSampleRate(self.requested_rate)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            # Whisper resamples whatever it is given, so a device that insists
            # on 48 kHz stereo is a size problem, not a correctness one.
            fmt = device.preferredFormat()
            if fmt.sampleFormat() != QAudioFormat.SampleFormat.Int16:
                fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self.sample_rate = fmt.sampleRate()
        self.channels = max(1, fmt.channelCount())

        try:
            self._source = QAudioSource(device, fmt, self)
            self._io = self._source.start()
        except Exception as exc:
            log.exception("Could not open the microphone")
            self.failed.emit(f"I could not open the microphone. {plain_reason(exc)}")
            self._source = None
            self._io = None
            return False
        if self._io is None:
            self.failed.emit("The microphone opened but produced no stream.")
            self._source = None
            return False

        self._buffer.clear()
        self._recording = True
        self._io.readyRead.connect(self._on_ready_read)
        return True

    def stop(self) -> bytes:
        """Stop capture and return everything recorded since start()."""
        if not self._recording:
            return bytes(self._buffer)
        self._recording = False
        if self._io is not None:
            try:
                self._io.readyRead.disconnect(self._on_ready_read)
            except (RuntimeError, TypeError):
                pass
            # Anything the device buffered between the last signal and now is
            # the tail of the last word, so it is drained rather than dropped.
            self._drain()
        if self._source is not None:
            self._source.stop()
            self._source.deleteLater()
        self._source = None
        self._io = None
        return bytes(self._buffer)

    def take(self) -> bytes:
        """Hand over everything buffered so far and keep recording.

        Conversation mode slices one continuous stream into utterances, so it
        needs the audio up to this moment without closing the device: stopping
        and restarting between sentences would clip the first syllable of the
        next one.
        """
        pcm = bytes(self._buffer)
        self._buffer.clear()
        return pcm

    def keep_last_ms(self, ms: int) -> None:
        """Drop older buffered audio, keeping only the last ``ms`` milliseconds.

        Used when VAD marks speech start so minutes of pre-onset silence are not
        shipped to Whisper (which then hallucinates and kills wake matching).
        """
        if ms <= 0:
            self._buffer.clear()
            return
        bytes_per_s = self.sample_rate * max(1, self.channels) * 2
        keep = max(0, int(bytes_per_s * (ms / 1000.0)))
        if keep <= 0:
            self._buffer.clear()
            return
        if len(self._buffer) > keep:
            self._buffer[:] = self._buffer[-keep:]

    def peek(self) -> bytes:
        """Copy the buffer without clearing, for provisional mid-utterance STT."""
        return bytes(self._buffer)

    def discard(self) -> None:
        self.stop()
        self._buffer.clear()

    def _on_ready_read(self) -> None:
        self._drain()

    def _drain(self) -> None:
        if self._io is None:
            return
        data = self._io.readAll()
        if not data:
            return
        block = bytes(data.data())
        self._buffer.extend(block)
        self.frames.emit(block)
        self.level.emit(rms_level(block))


class SpeechPlayer(QObject):
    """Plays synthesized clips back to back, and can be cut off mid-sentence.

    The voice service emits one clip per sentence, which is what makes stopping
    her feel immediate: the current sentence finishes or is cut, and the rest of
    the queue is simply thrown away rather than having to be waited out.

    Clips are tagged with the utterance they belong to. A clip that arrives
    after its utterance was cancelled is dropped, because synthesis of sentence
    four can land after the user has already interrupted sentence two.
    """

    started = Signal()
    finished = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue: list[tuple[int, Path]] = []
        self._utterance = 0
        self._cancelled: set[int] = set()
        self._player = None
        self._output = None
        self._active = False
        self._device_hint = ""
        self._level_env: np.ndarray | None = None
        self._level_pos_ms = -1
        self._level_mark = 0.0
        if MULTIMEDIA_AVAILABLE:
            self._output = QAudioOutput(self)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._output)
            self._player.mediaStatusChanged.connect(self._on_status)
            self._player.errorOccurred.connect(self._on_error)

    def available(self) -> bool:
        return self._player is not None

    def has_work(self) -> bool:
        """True while a clip is playing or still queued (covers SPEECH_DONE races)."""
        return self._active or bool(self._queue)

    def set_volume(self, volume: float) -> None:
        if self._output is not None:
            self._output.setVolume(max(0.0, min(1.0, volume)))

    def volume(self) -> float:
        if self._output is None:
            return 1.0
        return float(self._output.volume())

    def current_level(self) -> float | None:
        """Loudness of the clip at the playhead, or None when there is nothing to read."""
        try:
            env = self._level_env
            if not self._active or self._player is None or env is None or len(env) == 0:
                return None
            pos = int(self._player.position())
            now = time.monotonic()
            if pos != self._level_pos_ms:
                self._level_pos_ms = pos
                self._level_mark = now
            extra = now - self._level_mark
            if extra < 0.0:
                extra = 0.0
            elif extra > 0.05:
                extra = 0.05
            index = int((self._level_pos_ms / 1000.0 + extra) * _LEVEL_HZ)
            if index < 0:
                return None
            if index >= len(env):
                return float(env[-1])
            return float(env[index])
        except Exception:
            return None

    def _load_level(self, clip: Path) -> None:
        self._level_env = wav_loudness_envelope(clip)
        self._level_pos_ms = -1
        self._level_mark = time.monotonic()

    def _clear_level(self) -> None:
        self._level_env = None
        self._level_pos_ms = -1

    def set_output_device(self, hint: str) -> None:
        """Select an output by substring of the Windows device name."""
        self._device_hint = hint or ""
        if self._output is None or not MULTIMEDIA_AVAILABLE:
            return
        outputs = QMediaDevices.audioOutputs()
        matched = _match_device(outputs, self._device_hint)
        if matched is None:
            default = QMediaDevices.defaultAudioOutput()
            matched = default if not default.isNull() else (outputs[0] if outputs else None)
        if matched is not None:
            self._output.setDevice(matched)

    def enqueue(self, path: str | Path, utterance: int = 0) -> None:
        if self._player is None:
            return
        if utterance and utterance in self._cancelled:
            return
        clip = Path(path)
        if not clip.exists():
            return
        self._queue.append((utterance, clip))
        if not self._active:
            self._advance()

    def stop(self) -> None:
        """Cut playback now and abandon everything queued behind it."""
        if self._player is None:
            return
        if self._utterance:
            self._cancelled.add(self._utterance)
        for utterance, _ in self._queue:
            if utterance:
                self._cancelled.add(utterance)
        self._queue.clear()
        self._active = False
        self._clear_level()
        self._player.stop()
        # Releasing the source lets the file be overwritten or pruned; Windows
        # keeps a media handle open otherwise.
        self._player.setSource(QUrl())
        # No finished signal here. finished means "she said everything she had
        # to say", which is what conversation mode listens for to take its turn.
        # Being cut off is the opposite, and the caller doing the cutting
        # already knows it happened.
        if len(self._cancelled) > 64:
            self._cancelled = set(sorted(self._cancelled)[-32:])

    def _advance(self) -> None:
        if self._player is None:
            return
        while self._queue:
            utterance, clip = self._queue.pop(0)
            if utterance and utterance in self._cancelled:
                continue
            self._utterance = utterance
            self._active = True
            self._player.setSource(QUrl.fromLocalFile(str(clip)))
            self._load_level(clip)
            self._player.play()
            self.started.emit()
            return
        if self._active:
            self._active = False
            self._clear_level()
            self._player.setSource(QUrl())
            self.finished.emit()

    def _on_status(self, status) -> None:
        if self._player is None:
            return
        end = QMediaPlayer.MediaStatus.EndOfMedia
        invalid = QMediaPlayer.MediaStatus.InvalidMedia
        if status in (end, invalid) and self._active:
            # Give Qt a turn to release the finished file before the next
            # setSource; doing it inline from the status callback intermittently
            # left the player in a stopped state with a queued clip.
            QTimer.singleShot(0, self._advance)

    def _on_error(self, error, message: str = "") -> None:
        if self._player is None:
            return
        if error == QMediaPlayer.Error.NoError:
            return
        # Clear active BEFORE failed so has_work() is false when the window
        # resyncs speaking — otherwise conversation stays deaf forever after a
        # last-clip error (SPEECH_DONE already cleared _speech_expected).
        self._active = False
        self._queue.clear()
        self._clear_level()
        try:
            self._player.stop()
            self._player.setSource(QUrl())
        except Exception:
            pass
        self.failed.emit(message or "Playback failed.")
        self.finished.emit()
