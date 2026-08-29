"""Deciding when someone has started talking, and when they have stopped.

Hands-free conversation needs an answer to "are they done?" that does not
involve a button. Two backends share one event API:

- energy: RMS loudness against a room floor (zero deps; headset-quiet rooms).
- silero: live Silero ONNX speech probability (production default).

Time is counted in samples, never with a clock. That makes the whole thing
deterministic and testable: a test can feed two seconds of synthetic silence in
one call and get exactly the decision the real stream would produce.

Adaptive end-pointing: short command-like utterances end after a tighter
silence window; longer speech keeps the full silence_ms so mid-thought pauses
do not chop one question into three turns. That is felt latency, not model TTFT.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from arelis.voice.pcm import SAMPLE_WIDTH, rms_level

log = logging.getLogger(__name__)

STARTED = "started"
ENDED = "ended"
TIMEOUT = "timeout"

# How loud, relative to the measured room floor, counts as a voice. Three is
# forgiving enough for someone leaning back from the mic and still well clear
# of fan noise.
_FLOOR_MULTIPLE = 3.0
# A floor this high means calibration heard something that was not the room.
# Past it the configured level is trusted instead.
_FLOOR_CEILING = 0.08
# Speech has to hold for this long before it counts, so a keyboard clack or a
# chair creak does not open an utterance.
_DEFAULT_ONSET_MS = 160
# Silero frame is 32 ms at 16 kHz; probability EMA softens single-frame blips.
_SILERO_PROB_EMA = 0.65


@dataclass(slots=True)
class DetectorConfig:
    sample_rate: int = 16000
    channels: int = 1
    # Pause that ends a longer / thoughtful utterance.
    silence_ms: int = 900
    # Tighter pause after short command-like speech (see short_utterance_ms).
    # Set equal to silence_ms (or 0) to disable adaptive end-pointing.
    short_silence_ms: int = 550
    # Voiced duration under this uses short_silence_ms instead of silence_ms.
    short_utterance_ms: int = 2800
    speech_level: float = 0.02
    calibration_ms: int = 400
    max_utterance_s: int = 60
    # Live Silero / shared onset hold.
    speech_threshold: float = 0.5
    # Silero only: end-point when EMA falls below this (defaults to 0.7 * threshold).
    end_threshold: float = 0.0
    onset_ms: int = _DEFAULT_ONSET_MS
    # Optional override for the ONNX weights (silero backend).
    silero_model_path: str = ""


@runtime_checkable
class UtteranceDetectorProtocol(Protocol):
    config: DetectorConfig

    @property
    def backend(self) -> str: ...

    @property
    def speaking(self) -> bool: ...

    @property
    def last_speech_prob(self) -> float | None: ...

    def reset(self) -> None: ...

    def reset_soft(self) -> None: ...

    def required_silence_ms(self) -> int: ...

    def feed(self, block: bytes) -> str | None: ...


class EnergyUtteranceDetector:
    """Emits STARTED, ENDED, or TIMEOUT from RMS energy vs room floor."""

    backend = "energy"

    def __init__(self, config: DetectorConfig | None = None) -> None:
        self.config = config or DetectorConfig()
        self._last_speech_prob: float | None = None
        self.reset()

    def reset(self) -> None:
        self._calibrated_samples = 0
        self._floor = 0.0
        self._speaking = False
        self._onset_samples = 0
        self._silence_samples = 0
        self._speech_samples = 0
        self._voiced_samples = 0
        self._finished = False
        self._last_speech_prob = None

    def resume_after_pause(self) -> None:
        """Keep the utterance open after a pause Smart Turn called incomplete."""
        self._finished = False
        self._silence_samples = 0

    def force_speaking(self) -> None:
        """Treat the live buffer as already in speech (OWW remainder)."""
        self._speaking = True
        self._finished = False
        self._onset_samples = 0
        self._silence_samples = 0
        if self._speech_samples <= 0:
            self._speech_samples = 1
        if self._voiced_samples <= 0:
            self._voiced_samples = 1

    def reset_soft(self) -> None:
        """Clear utterance state but keep a capped floor (post-reply resume).

        A full reset re-calibrates against post-TTS room noise and often sets
        the threshold so high that the next quiet "thanks" never starts speech
        until the user repeats louder.
        """
        cfg = self.config
        kept = 0.0
        if self._floor > 0:
            kept = min(self._floor, float(cfg.speech_level) * 1.2)
        self.reset()
        if kept > 0:
            self._floor = kept
            self._calibrated_samples = _ms_to_samples(
                cfg.calibration_ms, cfg.sample_rate
            )

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def last_speech_prob(self) -> float | None:
        return self._last_speech_prob

    @property
    def threshold(self) -> float:
        floor_based = self._floor * _FLOOR_MULTIPLE
        if self._floor > _FLOOR_CEILING:
            return self.config.speech_level
        return max(self.config.speech_level, floor_based)

    def required_silence_ms(self) -> int:
        return _required_silence_ms(
            self.config, self._voiced_samples, sample_rate=self.config.sample_rate
        )

    def feed(self, block: bytes) -> str | None:
        """Consume one block of PCM and return an event, or None."""
        if self._finished or not block:
            return None
        cfg = self.config
        samples = len(block) // (SAMPLE_WIDTH * max(1, cfg.channels))
        if samples <= 0:
            return None
        level = rms_level(block)
        self._last_speech_prob = None

        calibration_samples = _ms_to_samples(cfg.calibration_ms, cfg.sample_rate)
        if self._calibrated_samples < calibration_samples and not self._speaking:
            if level < cfg.speech_level * 4:
                self._floor = max(self._floor, level)
                self._calibrated_samples += samples
                return None
            self._calibrated_samples = calibration_samples

        onset_ms = int(cfg.onset_ms or _DEFAULT_ONSET_MS)
        if level >= self.threshold:
            self._silence_samples = 0
            if not self._speaking:
                self._onset_samples += samples
                if self._onset_samples >= _ms_to_samples(onset_ms, cfg.sample_rate):
                    self._speaking = True
                    self._speech_samples = self._onset_samples
                    self._voiced_samples = self._onset_samples
                    return STARTED
                return None
            self._speech_samples += samples
            self._voiced_samples += samples
        else:
            self._onset_samples = 0
            if not self._speaking:
                return None
            self._speech_samples += samples
            self._silence_samples += samples
            need = _ms_to_samples(self.required_silence_ms(), cfg.sample_rate)
            if self._silence_samples >= need:
                self._finished = True
                return ENDED

        if self._speech_samples >= cfg.max_utterance_s * cfg.sample_rate:
            self._finished = True
            return TIMEOUT
        return None


# Backward-compatible name used throughout tests and older call sites.
UtteranceDetector = EnergyUtteranceDetector


class SileroUtteranceDetector:
    """Live Silero speech-probability → STARTED / ENDED / TIMEOUT."""

    backend = "silero"

    def __init__(
        self,
        config: DetectorConfig | None = None,
        *,
        engine: Any | None = None,
    ) -> None:
        from arelis.voice.silero_vad import SileroOnnxVad

        self.config = config or DetectorConfig()
        if engine is not None:
            self._engine = engine
        else:
            path = (self.config.silero_model_path or "").strip() or None
            self._engine = SileroOnnxVad(path)
        self._last_speech_prob: float | None = None
        self._prob_ema = 0.0
        self.reset()

    def resume_after_pause(self) -> None:
        """Keep the utterance open after a pause Smart Turn called incomplete."""
        self._finished = False
        self._silence_samples = 0

    def force_speaking(self) -> None:
        """Treat the live buffer as already in speech (OWW remainder)."""
        from arelis.voice.silero_vad import FRAME_SAMPLES

        self._speaking = True
        self._finished = False
        self._onset_samples = 0
        self._silence_samples = 0
        if self._speech_samples <= 0:
            self._speech_samples = FRAME_SAMPLES
        if self._voiced_samples <= 0:
            self._voiced_samples = FRAME_SAMPLES

    def reset(self) -> None:
        self._speaking = False
        self._onset_samples = 0
        self._silence_samples = 0
        self._speech_samples = 0
        self._voiced_samples = 0
        self._finished = False
        self._last_speech_prob = None
        self._prob_ema = 0.0
        reset = getattr(self._engine, "reset", None)
        if callable(reset):
            reset()

    def reset_soft(self) -> None:
        """Fresh neural state after TTS/deaf window — no energy floor."""
        self.reset()

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def last_speech_prob(self) -> float | None:
        return self._last_speech_prob

    def required_silence_ms(self) -> int:
        # Voiced duration is tracked in 16 kHz sample units from Silero frames.
        from arelis.voice.silero_vad import TARGET_SR

        return _required_silence_ms(
            self.config, self._voiced_samples, sample_rate=TARGET_SR
        )

    def feed(self, block: bytes) -> str | None:
        if self._finished or not block:
            return None
        from arelis.voice.silero_vad import (
            FRAME_SAMPLES,
            TARGET_SR,
            int16_pcm_to_float32,
            resample_to_16k,
        )

        cfg = self.config
        mono = int16_pcm_to_float32(block, channels=cfg.channels)
        if mono.size == 0:
            return None
        samples_16k = resample_to_16k(mono, cfg.sample_rate)
        probs = self._engine.push(samples_16k)
        if not probs:
            return None

        event: str | None = None
        onset_need = _ms_to_samples(int(cfg.onset_ms or _DEFAULT_ONSET_MS), TARGET_SR)
        threshold = float(cfg.speech_threshold)
        end_threshold = float(cfg.end_threshold or 0.0)
        if end_threshold <= 0:
            end_threshold = max(0.15, threshold * 0.7)
        for prob in probs:
            self._last_speech_prob = float(prob)
            self._prob_ema = (
                _SILERO_PROB_EMA * float(prob)
                + (1.0 - _SILERO_PROB_EMA) * self._prob_ema
            )
            if not self._speaking:
                voiced = self._prob_ema >= threshold
            else:
                # Hysteresis: stay in speech until EMA clearly drops.
                voiced = self._prob_ema >= end_threshold
            if voiced:
                self._silence_samples = 0
                if not self._speaking:
                    self._onset_samples += FRAME_SAMPLES
                    if self._onset_samples >= onset_need:
                        self._speaking = True
                        self._speech_samples = self._onset_samples
                        self._voiced_samples = self._onset_samples
                        event = STARTED
                    continue
                self._speech_samples += FRAME_SAMPLES
                self._voiced_samples += FRAME_SAMPLES
            else:
                self._onset_samples = 0
                if not self._speaking:
                    continue
                self._speech_samples += FRAME_SAMPLES
                self._silence_samples += FRAME_SAMPLES
                need = _ms_to_samples(self.required_silence_ms(), TARGET_SR)
                if self._silence_samples >= need:
                    self._finished = True
                    return ENDED

            if self._speech_samples >= cfg.max_utterance_s * TARGET_SR:
                self._finished = True
                return TIMEOUT
        return event


def make_utterance_detector(
    backend: str = "silero",
    config: DetectorConfig | None = None,
    *,
    model_path: Path | str | None = None,
    allow_download: bool = False,
) -> UtteranceDetectorProtocol:
    """Build a live utterance detector; fall back to energy if Silero cannot load."""
    cfg = config or DetectorConfig()
    name = (backend or "silero").strip().lower()
    if name in {"", "auto"}:
        name = "silero"
    if name == "energy":
        return EnergyUtteranceDetector(cfg)
    if name != "silero":
        log.warning("Unknown voice.vad.backend=%r; using energy", backend)
        return EnergyUtteranceDetector(cfg)

    try:
        from arelis.voice.silero_vad import (
            SileroOnnxVad,
            SileroUnavailableError,
            ensure_silero_model,
        )

        path = model_path or (cfg.silero_model_path or "").strip() or None
        if allow_download:
            resolved = ensure_silero_model(Path(path) if path else None)
        else:
            resolved = Path(path) if path else None
            if resolved is None:
                from arelis.voice.silero_vad import default_model_path

                resolved = default_model_path()
            if not resolved.is_file():
                raise SileroUnavailableError(f"Silero model missing: {resolved}")
        engine = SileroOnnxVad(resolved)
        if cfg.silero_model_path != str(resolved):
            cfg.silero_model_path = str(resolved)
        return SileroUtteranceDetector(cfg, engine=engine)
    except Exception as exc:
        log.warning(
            "Silero VAD unavailable (%s); falling back to energy backend",
            exc,
        )
        return EnergyUtteranceDetector(cfg)


def _required_silence_ms(
    cfg: DetectorConfig, voiced_samples: int, *, sample_rate: int
) -> int:
    short = int(cfg.short_silence_ms or 0)
    long = int(cfg.silence_ms)
    if short <= 0 or short >= long:
        return long
    rate = max(1, int(sample_rate))
    voiced_ms = (voiced_samples * 1000) // rate
    if voiced_ms < int(cfg.short_utterance_ms):
        return short
    return long


def _ms_to_samples(ms: int, sample_rate: int) -> int:
    return max(1, int(sample_rate * ms / 1000))
