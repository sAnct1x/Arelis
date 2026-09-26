"""Live Silero VAD via ONNX Runtime (no PyTorch).

Official constraint: at 16 kHz feed exactly 512 samples (32 ms) per step and
keep the LSTM state + 64-sample context between calls. Qt delivers variable
block sizes, so callers push PCM through ``SileroOnnxVad.push`` which rechunks
and returns one speech probability per completed frame.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from arelis.paths import models_dir
from arelis.voice.pcm import SAMPLE_WIDTH

log = logging.getLogger(__name__)

TARGET_SR = 16000
FRAME_SAMPLES = 512  # 32 ms at 16 kHz
CONTEXT_SAMPLES = 64
_DEFAULT_MODEL = models_dir() / "silero" / "silero_vad.onnx"

# Upstream Silero ONNX (opset 16). Vendored under models/silero/; this URL is
# the documented fallback when the file is missing.
_MODEL_URL = (
    "https://github.com/snakers4/silero-vad/raw/master/"
    "src/silero_vad/data/silero_vad.onnx"
)


class SileroUnavailableError(RuntimeError):
    """onnxruntime or the ONNX weights are missing / unusable."""


def default_model_path() -> Path:
    return _DEFAULT_MODEL


def silero_available(model_path: Path | None = None) -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    path = Path(model_path) if model_path else _DEFAULT_MODEL
    return path.is_file()


class SileroOnnxVad:
    """Stateful Silero ONNX session for streaming 16 kHz mono float PCM."""

    def __init__(
        self,
        model_path: Path | str | None = None,
        *,
        intra_op_threads: int = 1,
    ) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise SileroUnavailableError(
                "onnxruntime is not installed. "
                'Run: pip install -e ".[voice]"'
            ) from exc

        path = Path(model_path) if model_path else _DEFAULT_MODEL
        if not path.is_file():
            raise SileroUnavailableError(
                f"Silero VAD model not found at {path}. "
                "See models/silero/README.md for the download URL."
            )

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = max(1, int(intra_op_threads))
        opts.log_severity_level = 3
        self._session = ort.InferenceSession(
            str(path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        self._pending = np.zeros(0, dtype=np.float32)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, CONTEXT_SAMPLES), dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)

    def push(self, samples_f32: np.ndarray) -> list[float]:
        """Append 16 kHz mono float samples; return speech probs for finished frames."""
        if samples_f32.size == 0:
            return []
        flat = np.asarray(samples_f32, dtype=np.float32).reshape(-1)
        if self._pending.size:
            flat = np.concatenate([self._pending, flat])
        probs: list[float] = []
        offset = 0
        while offset + FRAME_SAMPLES <= flat.size:
            chunk = flat[offset : offset + FRAME_SAMPLES]
            probs.append(self._infer_frame(chunk))
            offset += FRAME_SAMPLES
        self._pending = flat[offset:].copy()
        return probs

    def _infer_frame(self, frame: np.ndarray) -> float:
        # frame: (512,) float32 at 16 kHz
        x = np.concatenate(
            [self._context, frame.reshape(1, FRAME_SAMPLES)], axis=1
        ).astype(np.float32)
        feeds: dict[str, Any] = {
            "input": x,
            "state": self._state,
            "sr": np.array(TARGET_SR, dtype=np.int64),
        }
        # Some builds name inputs differently; only pass what the session expects.
        feeds = {k: v for k, v in feeds.items() if k in self._input_names}
        outs = self._session.run(None, feeds)
        out, state = outs[0], outs[1]
        self._state = np.asarray(state, dtype=np.float32)
        self._context = x[:, -CONTEXT_SAMPLES:]
        # out shape is typically (1, 1) or (1,)
        return float(np.asarray(out).reshape(-1)[0])


def int16_pcm_to_float32(pcm: bytes, *, channels: int = 1) -> np.ndarray:
    """Interleaved int16 PCM → mono float32 in [-1, 1]."""
    if not pcm:
        return np.zeros(0, dtype=np.float32)
    ch = max(1, int(channels))
    # Drop a trailing odd byte so frombuffer stays aligned.
    usable = len(pcm) - (len(pcm) % (SAMPLE_WIDTH * ch))
    if usable <= 0:
        return np.zeros(0, dtype=np.float32)
    samples = np.frombuffer(pcm[:usable], dtype=np.int16).astype(np.float32)
    if ch > 1:
        samples = samples.reshape(-1, ch).mean(axis=1)
    return samples / 32768.0


def resample_to_16k(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Lightweight linear resample to 16 kHz (good enough for VAD)."""
    sr = int(sample_rate)
    if sr <= 0 or samples.size == 0:
        return np.zeros(0, dtype=np.float32)
    if sr == TARGET_SR:
        return np.asarray(samples, dtype=np.float32)
    if sr % TARGET_SR == 0:
        step = sr // TARGET_SR
        return np.asarray(samples[::step], dtype=np.float32)
    # General case: linear interpolation.
    duration = samples.size / float(sr)
    out_len = max(1, round(duration * TARGET_SR))
    x_old = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=out_len, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


def ensure_silero_model(model_path: Path | None = None) -> Path:
    """Return a usable model path; download once if missing (best-effort)."""
    path = Path(model_path) if model_path else _DEFAULT_MODEL
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import urllib.request

        log.info("Downloading Silero VAD ONNX to %s", path)
        urllib.request.urlretrieve(_MODEL_URL, path)
    except Exception as exc:
        raise SileroUnavailableError(
            f"Could not download Silero VAD model to {path}: {exc}"
        ) from exc
    if not path.is_file():
        raise SileroUnavailableError(f"Silero VAD model missing after download: {path}")
    return path
