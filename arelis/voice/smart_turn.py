"""Pipecat Smart Turn v3 — semantic end-of-turn on CPU ONNX.

Silero says there was a pause. This model looks at the last 8 s of audio
(prosody, not the transcript) and says whether the speaker is done or still
thinking. Missing weights fall back to silence_ms. Apache-2.0 weights;
inference stays local.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from arelis.paths import models_dir
from arelis.voice.silero_vad import int16_pcm_to_float32, resample_to_16k

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
WINDOW_S = 8
_DEFAULT_MODEL = models_dir() / "smart_turn" / "smart-turn-v3.2-cpu.onnx"
_MODEL_URLS = (
    "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/"
    "smart-turn-v3.2-cpu.onnx",
    "https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/"
    "smart-turn-v3.1.onnx",
)


class SmartTurnUnavailableError(RuntimeError):
    """onnxruntime or the Smart Turn ONNX is missing / unusable."""


def default_model_path() -> Path:
    return _DEFAULT_MODEL


def smart_turn_available(model_path: Path | None = None) -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    path = Path(model_path) if model_path else _DEFAULT_MODEL
    return path.is_file()


def ensure_smart_turn_model(
    model_path: Path | None = None,
    *,
    allow_download: bool = True,
) -> Path:
    path = Path(model_path) if model_path else _DEFAULT_MODEL
    if path.is_file():
        return path
    if not allow_download:
        raise SmartTurnUnavailableError(
            f"Smart Turn model not found at {path}. See models/smart_turn/."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    last_exc: Exception | None = None
    for url in _MODEL_URLS:
        try:
            import urllib.request

            log.info("Downloading Smart Turn ONNX from %s", url)
            tmp = path.with_suffix(path.suffix + ".part")
            urllib.request.urlretrieve(url, tmp)
            tmp.replace(path)
            break
        except Exception as exc:
            last_exc = exc
            continue
    else:
        raise SmartTurnUnavailableError(
            f"Could not download Smart Turn model to {path}: {last_exc}"
        )
    if not path.is_file():
        raise SmartTurnUnavailableError(f"Smart Turn model missing after download: {path}")
    return path


class SmartTurnAnalyzer:
    """Complete (True) vs incomplete (False) for one utterance PCM buffer."""

    def __init__(
        self,
        model_path: Path | str | None = None,
        *,
        threshold: float = 0.5,
        intra_op_threads: int = 1,
    ) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise SmartTurnUnavailableError(
                "onnxruntime is not installed. "
                'Run: pip install -e ".[voice]"'
            ) from exc

        path = Path(model_path) if model_path else _DEFAULT_MODEL
        if not path.is_file():
            raise SmartTurnUnavailableError(f"Smart Turn model not found at {path}.")

        opts = ort.SessionOptions()
        opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = max(1, int(intra_op_threads))
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.log_severity_level = 3
        self._session = ort.InferenceSession(str(path), sess_options=opts)
        self._threshold = float(threshold)
        self.last_probability = 0.0

    def complete(
        self,
        pcm: bytes,
        *,
        sample_rate: int = SAMPLE_RATE,
        channels: int = 1,
    ) -> bool:
        """True when the speaker has finished their turn."""
        result = self.predict(pcm, sample_rate=sample_rate, channels=channels)
        return bool(result["complete"])

    def predict(
        self,
        pcm: bytes,
        *,
        sample_rate: int = SAMPLE_RATE,
        channels: int = 1,
    ) -> dict[str, Any]:
        if not pcm:
            self.last_probability = 1.0
            return {"complete": True, "probability": 1.0}
        samples = int16_pcm_to_float32(pcm, channels=max(1, channels))
        samples = resample_to_16k(samples, int(sample_rate) or SAMPLE_RATE)
        n_keep = WINDOW_S * SAMPLE_RATE
        if samples.size > n_keep:
            samples = samples[-n_keep:]
        elif samples.size < n_keep:
            samples = np.pad(samples, (n_keep - samples.size, 0), mode="constant")

        from arelis.voice.whisper_mel import compute_whisper_log_mel_features

        log_mel = compute_whisper_log_mel_features(samples, do_normalize=True)
        features = np.expand_dims(log_mel, axis=0)
        outputs = self._session.run(None, {"input_features": features})
        probability = float(np.asarray(outputs[0]).reshape(-1)[0])
        self.last_probability = probability
        complete = probability > self._threshold
        return {"complete": complete, "probability": probability}


def load_smart_turn(
    model_path: str | Path | None = None,
    *,
    allow_download: bool = True,
    threshold: float = 0.5,
) -> SmartTurnAnalyzer | None:
    """Return an analyzer, or None when the model cannot run."""
    try:
        path = ensure_smart_turn_model(
            Path(model_path) if model_path else None,
            allow_download=allow_download,
        )
        return SmartTurnAnalyzer(path, threshold=threshold)
    except Exception as exc:
        log.warning("Smart Turn unavailable (%s); using silence_ms", exc)
        return None
