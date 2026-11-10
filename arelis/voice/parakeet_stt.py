"""NVIDIA Parakeet TDT 0.6B v3 (int8 ONNX) via sherpa-onnx on CPU.

Opt-in speech-to-text engine. Weights are fetched on first use into the
user models folder, never vendored. Same transcribe(path) -> text shape
as the Whisper ear. Offline only: this is a full-utterance model, so
conversation uses the clip path rather than the live Zipformer stream.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arelis.paths import models_dir, resolve_model_path

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
PACK_NAME = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
ARCHIVE_NAME = f"{PACK_NAME}.tar.bz2"
MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    f"asr-models/{ARCHIVE_NAME}"
)
# Official sherpa-onnx asr-models release asset (GitHub API, 2026-11-07).
ARCHIVE_BYTES = 487_211_443
ARCHIVE_SHA256 = "1495e91b59d7fc53ddca91f3431758ec99f8fa253fdb0e1e851be0f72b14b0f9"
# Floor checks after extract, under the sizes listed in the sherpa-onnx docs.
_MIN_ENCODER = 600_000_000
_MIN_DECODER = 10_000_000
_MIN_JOINER = 5_000_000
_MIN_TOKENS = 50_000

# Extra room for the unpacked pack (~640 MB) after the archive is on disk.
_EXTRACT_SLACK = 700_000_000

Progress = Callable[[str, int, int], None]
Cancel = Callable[[], bool]

_NO_PACKAGE = (
    "Speech recognition needs sherpa-onnx, which is not installed. "
    'Run: pip install -e ".[voice]"'
)
_STOPPED = (
    "The Parakeet speech model download was stopped. Using Whisper instead."
)
_FAILED = "Could not download the Parakeet speech model. Using Whisper instead."
_MISMATCH = (
    "The Parakeet speech model file did not match what we expected. "
    "Using Whisper instead."
)
_DISK = (
    "This computer does not have enough free space for the Parakeet "
    "speech model. Using Whisper instead."
)
_MISSING = (
    "The Parakeet speech model is not on this PC, and downloads are off. "
    "Using Whisper instead."
)
_BROKEN = (
    "The Parakeet speech model could not be unpacked. Using Whisper instead."
)


class ParakeetUnavailableError(RuntimeError):
    """Package, model files, or download failed. Callers may fall back."""


def parakeet_package_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("sherpa_onnx") is not None


def resolve_parakeet_dir(stt_config: dict[str, Any] | None = None) -> Path:
    raw = str((stt_config or {}).get("parakeet_dir") or "models/parakeet").strip()
    path = Path(raw)
    if path.is_absolute():
        return path
    return resolve_model_path(path)


def physical_core_count() -> int:
    """Physical cores, not logical threads. Parakeet is slower with SMT."""
    logical = os.cpu_count() or 1
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    if text:
        cores: set[tuple[str, str]] = set()
        phys = ""
        for line in text.splitlines():
            if line.startswith("physical id"):
                phys = line.split(":", 1)[1].strip()
            elif line.startswith("core id"):
                cores.add((phys, line.split(":", 1)[1].strip()))
        if cores:
            return max(1, len(cores))
    return max(1, logical // 2 if logical > 1 else 1)


def parakeet_num_threads(stt_config: dict[str, Any] | None = None) -> int:
    cfg = stt_config or {}
    raw = cfg.get("num_threads")
    if raw is not None and str(raw).strip() != "":
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            pass
    # Match the Zipformer ear's default of 4, and never exceed physical cores.
    return max(1, min(4, physical_core_count()))


def _pack_dir(root: Path) -> Path:
    return root / PACK_NAME


def _required_files(root: Path) -> dict[str, Path] | None:
    parent = _pack_dir(root)
    if not parent.is_dir():
        return None
    files = {
        "encoder": parent / "encoder.int8.onnx",
        "decoder": parent / "decoder.int8.onnx",
        "joiner": parent / "joiner.int8.onnx",
        "tokens": parent / "tokens.txt",
    }
    floors = {
        "encoder": _MIN_ENCODER,
        "decoder": _MIN_DECODER,
        "joiner": _MIN_JOINER,
        "tokens": _MIN_TOKENS,
    }
    for key, path in files.items():
        try:
            if not path.is_file() or path.stat().st_size < floors[key]:
                return None
        except OSError:
            return None
    return files


def parakeet_files_present(model_dir: Path | None = None) -> bool:
    root = Path(model_dir) if model_dir else models_dir() / "parakeet"
    return _required_files(root) is not None


def parakeet_usable(stt_config: dict[str, Any] | None = None) -> bool:
    """True when Parakeet can run now or after a one-time download."""
    if not parakeet_package_available():
        return False
    cfg = stt_config or {}
    if parakeet_files_present(resolve_parakeet_dir(cfg)):
        return True
    return bool(cfg.get("allow_download", True))


def _status_line(done: int, total: int) -> str:
    if total <= 0:
        return "Downloading the Parakeet speech model…"
    mb = 1_000_000
    return (
        "Downloading the Parakeet speech model… "
        f"{done // mb} of {total // mb} MB"
    )


def _rewrite_download_error(exc: BaseException) -> ParakeetUnavailableError:
    text = str(exc)
    lower = text.lower()
    if "stopped" in lower:
        return ParakeetUnavailableError(_STOPPED)
    if "enough free space" in lower:
        return ParakeetUnavailableError(_DISK)
    if "did not match" in lower:
        return ParakeetUnavailableError(_MISMATCH)
    return ParakeetUnavailableError(_FAILED)


def _adapt_progress(progress: Progress | None) -> Progress | None:
    if progress is None:
        return None

    last = {"t": 0.0}

    def hook(_status: str, done: int, total: int) -> None:
        now = time.monotonic()
        is_edge = done <= 0 or (total > 0 and done >= total)
        if not is_edge and now - last["t"] < 0.4:
            return
        last["t"] = now
        progress(_status_line(done, total), done, total)

    return hook


def ensure_parakeet_files(
    model_dir: Path | None = None,
    *,
    allow_download: bool,
    progress: Progress | None = None,
    cancelled: Cancel | None = None,
) -> dict[str, Path]:
    """Return encoder/decoder/joiner/tokens, downloading once if needed."""
    root = Path(model_dir) if model_dir else models_dir() / "parakeet"
    found = _required_files(root)
    if found is not None:
        return found
    if not allow_download:
        raise ParakeetUnavailableError(_MISSING)
    if cancelled is not None and cancelled():
        raise ParakeetUnavailableError(_STOPPED)

    root.mkdir(parents=True, exist_ok=True)
    archive = root / ARCHIVE_NAME
    log.info("Downloading Parakeet STT model to %s", archive)
    if progress is not None:
        progress(_status_line(0, ARCHIVE_BYTES), 0, ARCHIVE_BYTES)

    from arelis.setup.download import download_file

    try:
        download_file(
            MODEL_URL,
            archive,
            expected_bytes=ARCHIVE_BYTES,
            sha256=ARCHIVE_SHA256,
            progress=_adapt_progress(progress),
            cancelled=cancelled,
        )
    except Exception as exc:
        raise _rewrite_download_error(exc) from exc

    if cancelled is not None and cancelled():
        raise ParakeetUnavailableError(_STOPPED)

    _require_extract_space(root)
    if progress is not None:
        progress("Unpacking the Parakeet speech model…", ARCHIVE_BYTES, ARCHIVE_BYTES)
    try:
        from arelis.voice.sherpa_stt import _extract_archive

        _extract_archive(archive, root)
    except Exception as exc:
        _remove_broken_pack(root)
        raise ParakeetUnavailableError(_BROKEN) from exc

    found = _required_files(root)
    if found is None:
        _remove_broken_pack(root)
        raise ParakeetUnavailableError(_BROKEN)
    try:
        archive.unlink(missing_ok=True)
    except OSError:
        log.warning("Could not remove the Parakeet archive after unpack: %s", archive)
    return found


def _require_extract_space(root: Path) -> None:
    import shutil

    probe = root
    while not probe.exists():
        parent = probe.parent
        if parent == probe:
            break
        probe = parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as exc:
        raise ParakeetUnavailableError(_DISK) from exc
    if free < _EXTRACT_SLACK:
        raise ParakeetUnavailableError(_DISK)


def _remove_broken_pack(root: Path) -> None:
    import shutil

    pack = _pack_dir(root)
    if pack.is_dir():
        shutil.rmtree(pack, ignore_errors=True)


class ParakeetSpeechToText:
    """Offline file adapter. Same lock/preload pattern as Whisper."""

    def __init__(
        self,
        stt_config: dict[str, Any] | None = None,
        *,
        progress: Progress | None = None,
        cancelled: Cancel | None = None,
    ) -> None:
        self.config = stt_config or {}
        self.model_dir = resolve_parakeet_dir(self.config)
        self.allow_download = bool(self.config.get("allow_download", True))
        self.progress = progress
        self.cancelled = cancelled
        self._recognizer = None

    def loaded(self) -> bool:
        return self._recognizer is not None

    def transcribe(self, audio_path: str | Path) -> str:
        recognizer = self.ensure_loaded()
        from arelis.voice.sherpa_stt import _read_wav_mono

        samples, sample_rate = _read_wav_mono(Path(audio_path))
        if samples.size == 0:
            return ""
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, samples)
        recognizer.decode_stream(stream)
        result = stream.result
        if result is None:
            return ""
        text = result.text if hasattr(result, "text") else str(result)
        return (text or "").strip()

    def ensure_loaded(self):
        """Download if needed, then build the recognizer. Worker-thread only."""
        if self._recognizer is not None:
            return self._recognizer
        if not parakeet_package_available():
            raise ParakeetUnavailableError(_NO_PACKAGE)
        files = ensure_parakeet_files(
            self.model_dir,
            allow_download=self.allow_download,
            progress=self.progress,
            cancelled=self.cancelled,
        )
        import sherpa_onnx

        threads = parakeet_num_threads(self.config)
        self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(files["encoder"]),
            decoder=str(files["decoder"]),
            joiner=str(files["joiner"]),
            tokens=str(files["tokens"]),
            num_threads=threads,
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
            provider="cpu",
            model_type="nemo_transducer",
        )
        log.info("Parakeet STT ready pack=%s threads=%s", PACK_NAME, threads)
        return self._recognizer
