"""Loudness envelope for a spoken WAV clip. No speakers involved."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def _envelope(path: Path):
    from arelis.ui.audio import wav_loudness_envelope

    return wav_loudness_envelope(path)


def _write_pcm(path: Path, samples: np.ndarray, rate: int = 24000) -> None:
    frames = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames.tobytes())


def test_a_loud_half_reads_high_and_a_silent_half_reads_near_zero(tmp_path: Path):
    """RMS across the clip follows the loud half and stays quiet in the silent half."""
    rate = 24000
    loud = 0.6 * np.sin(2 * np.pi * 220 * np.arange(rate) / rate)
    silent = np.zeros(rate)
    path = tmp_path / "half.wav"
    _write_pcm(path, np.concatenate([loud, silent]), rate)
    env = _envelope(path)
    assert env is not None
    assert env.ndim == 1
    mid = len(env) // 2
    assert float(np.median(env[:mid])) > 0.5
    assert float(np.median(env[mid:])) < 0.05


def test_a_missing_file_gives_no_level_without_raising(tmp_path: Path):
    """A path that is not a readable WAV returns None."""
    missing = _envelope(tmp_path / "nope.wav")
    assert missing is None
    junk = tmp_path / "notes.txt"
    junk.write_text("not a wav", encoding="utf-8")
    assert _envelope(junk) is None


def test_player_exposes_a_level_that_is_none_when_idle(qt_app):
    """Nothing playing means no loudness, and asking does not raise."""
    from arelis.ui.audio import SpeechPlayer

    player = SpeechPlayer()
    assert player.current_level() is None
