"""Idle wake via openWakeWord (no Whisper on ambient clips).

Requires a custom ONNX under models/wake/ (see models/wake/README.md). Runtime
never trains — training is an offline Piper-synthetic pipeline.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from arelis.paths import models_dir
from arelis.voice.silero_vad import int16_pcm_to_float32, resample_to_16k

log = logging.getLogger(__name__)

_DEFAULT_MODEL = models_dir() / "wake" / "hey_arelis.onnx"
# openWakeWord expects 80 ms frames at 16 kHz → 1280 samples.
_FRAME_SAMPLES = 1280
_TARGET_SR = 16000


class OpenWakeUnavailableError(RuntimeError):
    """openwakeword package or custom ONNX missing."""


def default_wake_model_path() -> Path:
    return _DEFAULT_MODEL


def openwake_available(model_path: str | Path | None = None) -> bool:
    try:
        import openwakeword  # noqa: F401
    except ImportError:
        return False
    path = Path(model_path) if model_path else _DEFAULT_MODEL
    return path.is_file()


class OpenWakeListener:
    """Score streaming PCM for the custom Hey Arelis model."""

    def __init__(
        self,
        *,
        model_path: str | Path | None = None,
        threshold: float = 0.5,
        cooldown_ms: int = 1500,
        sample_rate: int = 16000,
    ) -> None:
        try:
            from openwakeword.model import Model
        except ImportError as exc:
            raise OpenWakeUnavailableError(
                "openwakeword is not installed. "
                'Run: pip install -e ".[voice]"'
            ) from exc

        path = Path(model_path) if model_path else _DEFAULT_MODEL
        if not path.is_file():
            raise OpenWakeUnavailableError(
                f"Wake model not found at {path}. "
                "Train offline and place hey_arelis.onnx under models/wake/ "
                "(see models/wake/README.md)."
            )

        self._threshold = float(threshold)
        self._cooldown_s = max(0.0, float(cooldown_ms) / 1000.0)
        self._device_rate = int(sample_rate) if sample_rate else _TARGET_SR
        self._pending = np.zeros(0, dtype=np.float32)
        self.last_score: float = 0.0
        self._last_hit_at = 0.0
        # Single custom model; inference frameworks bundled by openwakeword.
        self._model = Model(
            wakeword_models=[str(path)],
            inference_framework="onnx",
        )
        self._model_keys = list(self._model.models.keys())

    def reset(self) -> None:
        self._pending = np.zeros(0, dtype=np.float32)
        self.last_score = 0.0
        reset = getattr(self._model, "reset", None)
        if callable(reset):
            reset()

    def set_device_rate(self, sample_rate: int) -> None:
        self._device_rate = int(sample_rate) if sample_rate else _TARGET_SR

    def feed(self, block: bytes, *, channels: int = 1) -> bool:
        """Return True once when score crosses threshold (with cooldown)."""
        if not block:
            return False
        mono = int16_pcm_to_float32(block, channels=channels)
        if mono.size == 0:
            return False
        samples = resample_to_16k(mono, self._device_rate)
        if self._pending.size:
            samples = np.concatenate([self._pending, samples])
        hit = False
        offset = 0
        while offset + _FRAME_SAMPLES <= samples.size:
            frame = samples[offset : offset + _FRAME_SAMPLES]
            offset += _FRAME_SAMPLES
            # openWakeWord wants int16 PCM for predict in many versions.
            pcm16 = np.clip(frame * 32768.0, -32768, 32767).astype(np.int16)
            scores = self._model.predict(pcm16)
            score = _max_score(scores, self._model_keys)
            self.last_score = score
            if score >= self._threshold:
                now = time.monotonic()
                if now - self._last_hit_at >= self._cooldown_s:
                    self._last_hit_at = now
                    hit = True
        self._pending = samples[offset:].copy()
        return hit


def _max_score(scores: Any, keys: list[str]) -> float:
    if scores is None:
        return 0.0
    if isinstance(scores, dict):
        vals = []
        for key in keys or scores.keys():
            val = scores.get(key)
            if val is None:
                continue
            if isinstance(val, (list, tuple, np.ndarray)):
                vals.append(float(np.max(val)))
            else:
                vals.append(float(val))
        return max(vals) if vals else 0.0
    try:
        return float(np.max(scores))
    except Exception:
        return 0.0
