"""Raw PCM helpers shared by capture, silence detection, and the WAV writer.

Qt hands back signed 16 bit little-endian frames; faster-whisper wants a file it
can decode. This module is the seam between the two, and it is deliberately
free of both Qt and faster-whisper so the arithmetic can be tested without a
microphone or a model.

audioop would cover most of this and is not used: it was deprecated in 3.11 and
removed in 3.13, and the array module does the same work in a few lines.
"""
from __future__ import annotations

import math
import sys
import wave
from array import array
from pathlib import Path

SAMPLE_WIDTH = 2  # signed 16 bit, the only width Arelis captures
_FULL_SCALE = 32768.0


def write_wav(
    path: str | Path,
    pcm: bytes,
    *,
    sample_rate: int,
    channels: int = 1,
) -> Path:
    """Write raw frames as a PCM WAV file, creating parent directories."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as fh:
        fh.setnchannels(channels)
        fh.setsampwidth(SAMPLE_WIDTH)
        fh.setframerate(sample_rate)
        fh.writeframes(pcm)
    return out


def duration_seconds(pcm: bytes, *, sample_rate: int, channels: int = 1) -> float:
    frame_bytes = SAMPLE_WIDTH * max(1, channels)
    if sample_rate <= 0:
        return 0.0
    return len(pcm) / frame_bytes / sample_rate


def rms_level(pcm: bytes) -> float:
    """Root mean square of a frame block, normalised to 0.0 - 1.0.

    Returned as a fraction of full scale rather than dB so a threshold can be
    written as a plain number in config and compared without special cases for
    silence, where dB would be negative infinity.
    """
    usable = len(pcm) - (len(pcm) % SAMPLE_WIDTH)
    if usable <= 0:
        return 0.0
    samples = _samples(pcm[:usable])
    total = 0
    for sample in samples:
        total += sample * sample
    return math.sqrt(total / len(samples)) / _FULL_SCALE


def peak_level(pcm: bytes) -> float:
    """Loudest single sample in the block, normalised to 0.0 - 1.0."""
    usable = len(pcm) - (len(pcm) % SAMPLE_WIDTH)
    if usable <= 0:
        return 0.0
    samples = _samples(pcm[:usable])
    return min(1.0, max(abs(s) for s in samples) / _FULL_SCALE)


def trim_trailing_silence(
    pcm: bytes,
    *,
    sample_rate: int,
    channels: int = 1,
    level: float = 0.012,
    keep_ms: int = 80,
    block_ms: int = 20,
) -> bytes:
    """Drop trailing quiet after end-pointing so Whisper sees less empty audio.

    Speeds STT without changing what the user said. keep_ms leaves a tiny pad
    so the last consonant is not clipped.
    """
    frame = SAMPLE_WIDTH * max(1, channels)
    if sample_rate <= 0 or len(pcm) < frame * 2:
        return pcm
    block = max(1, int(sample_rate * block_ms / 1000)) * frame
    keep = max(0, int(sample_rate * keep_ms / 1000)) * frame
    end = len(pcm) - (len(pcm) % frame)
    cut = end
    pos = end
    while pos > 0:
        start = max(0, pos - block)
        chunk = pcm[start:pos]
        if rms_level(chunk) >= level:
            break
        cut = start
        pos = start
    cut = min(end, cut + keep)
    if cut >= end:
        return pcm[:end]
    return pcm[:cut]


def _samples(pcm: bytes) -> array:
    """Decode little-endian frames whatever the host's byte order is."""
    samples = array("h")
    samples.frombytes(pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples
