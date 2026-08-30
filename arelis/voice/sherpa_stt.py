"""Sherpa-ONNX ear for dictate and conversation.

Wave 1 fed a finished WAV into a streaming Zipformer (OnlineRecognizer).
Wave 2 feeds live PCM into the same recognizer so finish() is cheap. CPU on
purpose — the GPU stays on the chat model. Kroko 2025 is the default pack
(conversational English); the 2023 LibriSpeech pack remains a fallback.
Nothing here phones home except the optional first-run download.
"""

from __future__ import annotations

import logging
import tarfile
import wave
from pathlib import Path
from typing import Any
from urllib.request import urlretrieve

import numpy as np

from arelis.paths import models_dir, resolve_model_path

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
_DEFAULT_DIR = models_dir() / "sherpa"
_KROKO_PACK = "sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06"
_LEGACY_PACK = "sherpa-onnx-streaming-zipformer-en-2023-06-26"
_PACK_NAME = _KROKO_PACK
_ARCHIVE = f"{_PACK_NAME}.tar.bz2"
_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    f"asr-models/{_ARCHIVE}"
)
# Streaming zipformers need ~0.66 s of tail pad to flush the last chunk.
_TAIL_S = 0.66

_NO_PACKAGE = (
    "Speech recognition needs sherpa-onnx, which is not installed. "
    'Run: pip install -e ".[voice]"'
)


class SherpaUnavailableError(RuntimeError):
    """Package, model files, or download failed."""


def sherpa_package_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("sherpa_onnx") is not None


def resolve_model_dir(stt_config: dict[str, Any] | None = None) -> Path:
    raw = str((stt_config or {}).get("model_dir") or "models/sherpa").strip()
    path = Path(raw)
    if path.is_absolute():
        return path
    return resolve_model_path(path)


def find_transducer_files(root: Path) -> dict[str, Path] | None:
    """encoder / decoder / joiner / tokens in the same folder, or None.

    Prefers the Kroko 2025 conversational pack, then the 2023 LibriSpeech
    pack, then any other transducer folder under root.
    """
    if not root.is_dir():
        return None
    for name in (_KROKO_PACK, _LEGACY_PACK):
        found = _transducer_in(root / name)
        if found is not None:
            return found
    for tokens in root.rglob("tokens.txt"):
        found = _transducer_in(tokens.parent)
        if found is not None:
            return found
    return None


def _transducer_in(parent: Path) -> dict[str, Path] | None:
    if not parent.is_dir():
        return None
    tokens = parent / "tokens.txt"
    if not tokens.is_file():
        return None
    encoder = _pick_onnx(parent, "encoder")
    decoder = _pick_onnx(parent, "decoder")
    joiner = _pick_onnx(parent, "joiner")
    if encoder and decoder and joiner:
        return {
            "tokens": tokens,
            "encoder": encoder,
            "decoder": decoder,
            "joiner": joiner,
            "pack": parent.name,
        }
    return None


def sherpa_files_present(model_dir: Path | None = None) -> bool:
    root = Path(model_dir) if model_dir else _DEFAULT_DIR
    return find_transducer_files(root) is not None


def sherpa_usable(stt_config: dict[str, Any] | None = None) -> bool:
    """True when Sherpa can run now or after a one-time download."""
    if not sherpa_package_available():
        return False
    cfg = stt_config or {}
    if sherpa_files_present(resolve_model_dir(cfg)):
        return True
    return bool(cfg.get("allow_download", True))


class SherpaSpeechToText:
    """Offline-on-a-file adapter. Same lock/preload pattern as Whisper."""

    def __init__(self, stt_config: dict[str, Any] | None = None) -> None:
        self.config = stt_config or {}
        self.model_dir = resolve_model_dir(self.config)
        self.allow_download = bool(self.config.get("allow_download", True))
        self._recognizer = None
        self._pack = ""

    def loaded(self) -> bool:
        return self._recognizer is not None

    def transcribe(self, audio_path: str | Path) -> str:
        recognizer = self.ensure_loaded()
        samples, sample_rate = _read_wav_mono(Path(audio_path))
        if samples.size == 0:
            return ""
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        tail = np.zeros(int(_TAIL_S * sample_rate), dtype=np.float32)
        stream.accept_waveform(sample_rate, tail)
        stream.input_finished()
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        result = recognizer.get_result(stream)
        if result is None:
            return ""
        text = result.text if hasattr(result, "text") else str(result)
        return (text or "").strip()

    def ensure_loaded(self):
        """Download if needed, then build the recognizer. Worker-thread only."""
        if self._recognizer is not None:
            return self._recognizer
        if not sherpa_package_available():
            raise SherpaUnavailableError(_NO_PACKAGE)
        files = ensure_sherpa_files(
            self.model_dir, allow_download=self.allow_download
        )
        import sherpa_onnx

        kwargs: dict[str, Any] = {
            "tokens": str(files["tokens"]),
            "encoder": str(files["encoder"]),
            "decoder": str(files["decoder"]),
            "joiner": str(files["joiner"]),
            "num_threads": 2,
            "sample_rate": SAMPLE_RATE,
            "feature_dim": 80,
            "decoding_method": "greedy_search",
            "provider": "cpu",
        }
        pack = str(files.get("pack") or Path(files["encoder"]).parent.name)
        if _KROKO_PACK in pack:
            kwargs["model_type"] = "zipformer2"
        try:
            self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(**kwargs)
        except TypeError:
            kwargs.pop("model_type", None)
            self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(**kwargs)
        self._pack = pack
        log.info("Sherpa STT ready pack=%s", pack)
        return self._recognizer

    def begin_live(self, *, sample_rate: int = SAMPLE_RATE) -> LiveSherpaSession:
        return LiveSherpaSession(self.ensure_loaded(), sample_rate=sample_rate)


class LiveSherpaSession:
    """Feed PCM while the user talks. finish() flushes the last chunk."""

    def __init__(self, recognizer: Any, *, sample_rate: int = SAMPLE_RATE) -> None:
        self._recognizer = recognizer
        self._stream = recognizer.create_stream()
        self._sample_rate = int(sample_rate) or SAMPLE_RATE
        self.partial = ""
        self.pack = getattr(recognizer, "_pack", "")

    def feed_pcm(self, pcm: bytes, *, sample_rate: int, channels: int) -> str:
        if not pcm:
            return self.partial
        from arelis.voice.silero_vad import int16_pcm_to_float32, resample_to_16k

        samples = int16_pcm_to_float32(pcm, channels=max(1, channels))
        samples = resample_to_16k(samples, int(sample_rate) or self._sample_rate)
        if samples.size == 0:
            return self.partial
        self._stream.accept_waveform(SAMPLE_RATE, samples)
        rec = self._recognizer
        while rec.is_ready(self._stream):
            rec.decode_stream(self._stream)
        self.partial = _result_text(rec.get_result(self._stream))
        return self.partial

    def finish(self) -> str:
        rec = self._recognizer
        tail = np.zeros(int(_TAIL_S * SAMPLE_RATE), dtype=np.float32)
        self._stream.accept_waveform(SAMPLE_RATE, tail)
        self._stream.input_finished()
        while rec.is_ready(self._stream):
            rec.decode_stream(self._stream)
        self.partial = _result_text(rec.get_result(self._stream))
        return self.partial


class LiveSherpaBridge:
    """Thread-safe PCM queue so Qt never runs Sherpa."""

    def __init__(self, engine: SherpaSpeechToText) -> None:
        import queue
        import threading

        self._engine = engine
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._text = ""
        self._partial = ""
        self._error: str | None = None

    def start(self) -> None:
        import threading

        self._thread = threading.Thread(
            target=self._run, name="arelis-sherpa-live", daemon=True
        )
        self._thread.start()

    def feed(self, pcm: bytes, sample_rate: int, channels: int) -> None:
        self._queue.put(("pcm", pcm, sample_rate, channels))

    def abort(self) -> None:
        self._queue.put(("abort", b"", 0, 0))

    def finish(self, timeout: float = 20.0) -> str:
        self._queue.put(("end", b"", 0, 0))
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        if self._error:
            raise SherpaUnavailableError(self._error)
        return self._text

    def _run(self) -> None:
        try:
            session = self._engine.begin_live()
            while True:
                kind, pcm, rate, channels = self._queue.get()
                if kind == "abort":
                    return
                if kind == "end":
                    self._text = session.finish()
                    return
                self._partial = session.feed_pcm(
                    pcm, sample_rate=rate, channels=channels
                )
        except Exception as exc:
            log.exception("Live Sherpa failed")
            self._error = str(exc)


def _result_text(result: Any) -> str:
    if result is None:
        return ""
    text = result.text if hasattr(result, "text") else str(result)
    return (text or "").strip()


def ensure_sherpa_files(
    model_dir: Path | None = None,
    *,
    allow_download: bool,
) -> dict[str, Path]:
    root = Path(model_dir) if model_dir else _DEFAULT_DIR
    found = find_transducer_files(root)
    if found is not None:
        return found
    if not allow_download:
        raise SherpaUnavailableError(
            f"Sherpa model not found in {root}. See models/sherpa/README.md."
        )
    root.mkdir(parents=True, exist_ok=True)
    archive = root / _ARCHIVE
    log.info("Downloading Sherpa STT model to %s", archive)
    tmp = archive.with_suffix(archive.suffix + ".part")
    try:
        urlretrieve(_MODEL_URL, tmp)
        tmp.replace(archive)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        raise SherpaUnavailableError(
            f"Could not download Sherpa model from {_MODEL_URL}: {exc}"
        ) from exc
    try:
        _extract_archive(archive, root)
    except SherpaUnavailableError:
        raise
    except Exception as exc:
        raise SherpaUnavailableError(
            f"Could not unpack Sherpa model {archive}: {exc}"
        ) from exc
    found = find_transducer_files(root)
    if found is None:
        raise SherpaUnavailableError(
            f"Sherpa archive extracted but encoder/decoder/joiner/tokens "
            f"were not found in {root}."
        )
    return found


def _extract_archive(archive: Path, dest: Path) -> None:
    dest = dest.resolve()
    with tarfile.open(archive, "r:bz2") as tar:
        for member in tar.getmembers():
            target = (dest / member.name).resolve()
            try:
                target.relative_to(dest)
            except ValueError as exc:
                raise SherpaUnavailableError(
                    f"Refusing Sherpa archive path outside {dest}: {member.name}"
                ) from exc
        kwargs: dict[str, Any] = {}
        if _extract_supports_filter():
            kwargs["filter"] = "data"
        tar.extractall(dest, **kwargs)


def _extract_supports_filter() -> bool:
    import inspect

    try:
        return "filter" in inspect.signature(tarfile.TarFile.extractall).parameters
    except (TypeError, ValueError):
        return False


def _pick_onnx(folder: Path, prefix: str) -> Path | None:
    matches = [
        path
        for path in folder.iterdir()
        if path.is_file()
        and path.suffix.lower() == ".onnx"
        and path.name.lower().startswith(prefix)
    ]
    if not matches:
        return None
    non_int8 = [path for path in matches if "int8" not in path.name.lower()]
    return sorted(non_int8 or matches, key=lambda p: p.name)[0]


def _read_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as fh:
        sample_rate = int(fh.getframerate())
        channels = max(1, int(fh.getnchannels()))
        width = int(fh.getsampwidth())
        raw = fh.readframes(fh.getnframes())
    if width != 2 or not raw:
        return np.zeros(0, dtype=np.float32), SAMPLE_RATE
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if sample_rate != SAMPLE_RATE and samples.size:
        duration = samples.size / float(sample_rate)
        out_len = max(1, round(duration * SAMPLE_RATE))
        old_x = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
        new_x = np.linspace(0.0, 1.0, num=out_len, endpoint=False)
        samples = np.interp(new_x, old_x, samples).astype(np.float32)
        sample_rate = SAMPLE_RATE
    return samples.astype(np.float32), sample_rate
