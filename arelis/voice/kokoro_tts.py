"""Kokoro-82M TTS on CPU ONNX — the mouth, not the conversation state machine.

Piper stays the fallback. This engine keeps one InferenceSession for the life
of the process so sentence two does not pay a model load, and it does not touch
the GPU (Ollama owns that). G2P is espeak-ng via phonemizer-fork (the same
stack Kokoro ONNX was exported with), so Windows does not need spaCy.
"""
from __future__ import annotations

import logging
import re
import wave
from pathlib import Path
from typing import Any

import numpy as np

from arelis.paths import models_dir

log = logging.getLogger(__name__)

SAMPLE_RATE = 24000
MAX_PHONEME_LENGTH = 510
DEFAULT_VOICE = "af_heart"
_DEFAULT_MODEL = models_dir() / "kokoro" / "kokoro-v1.0.onnx"
_DEFAULT_VOICES = models_dir() / "kokoro" / "voices-v1.0.bin"
_MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/kokoro-v1.0.onnx"
)
_VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.0/voices-v1.0.bin"
)

# Piper spells the name so Jenny does not say "airelyse". Espeak sees Arelis.
_PIPER_NAME = re.compile(r"(?i)\bUh-rell-iss\b")
_ARELIS = re.compile(r"(?i)\b(?:Airelyse|Airelis|Ahrelis)\b")

# Kokoro v1 token map (hexgrad / kokoro-onnx config.json). Unknown glyphs drop.
_VOCAB: dict[str, int] = {
    ";": 1, ":": 2, ",": 3, ".": 4, "!": 5, "?": 6, "—": 9, "…": 10,
    '"': 11, "(": 12, ")": 13, "“": 14, "”": 15, " ": 16, "\u0303": 17,
    "ʣ": 18, "ʥ": 19, "ʦ": 20, "ʨ": 21, "ᵝ": 22, "\uab67": 23,
    "A": 24, "I": 25, "O": 31, "Q": 33, "S": 35, "T": 36, "W": 39, "Y": 41,
    "ᵊ": 42, "a": 43, "b": 44, "c": 45, "d": 46, "e": 47, "f": 48, "h": 50,
    "i": 51, "j": 52, "k": 53, "l": 54, "m": 55, "n": 56, "o": 57, "p": 58,
    "q": 59, "r": 60, "s": 61, "t": 62, "u": 63, "v": 64, "w": 65, "x": 66,
    "y": 67, "z": 68, "ɑ": 69, "ɐ": 70, "ɒ": 71, "æ": 72, "β": 75, "ɔ": 76,
    "ɕ": 77, "ç": 78, "ɖ": 80, "ð": 81, "ʤ": 82, "ə": 83, "ɚ": 85, "ɛ": 86,
    "ɜ": 87, "ɟ": 90, "ɡ": 92, "ɥ": 99, "ɨ": 101, "ɪ": 102, "ʝ": 103,
    "ɯ": 110, "ɰ": 111, "ŋ": 112, "ɳ": 113, "ɲ": 114, "ɴ": 115, "ø": 116,
    "ɸ": 118, "θ": 119, "œ": 120, "ɹ": 123, "ɾ": 125, "ɻ": 126, "ʁ": 128,
    "ɽ": 129, "ʂ": 130, "ʃ": 131, "ʈ": 132, "ʧ": 133, "ʊ": 135, "ʋ": 136,
    "ʌ": 138, "ɣ": 139, "ɤ": 140, "χ": 142, "ʎ": 143, "ʒ": 147, "ʔ": 148,
    "ˈ": 156, "ˌ": 157, "ː": 158, "ʰ": 162, "ʲ": 164, "↓": 169, "→": 171,
    "↗": 172, "↘": 173, "ᵻ": 177,
}

_NO_G2P = (
    "Kokoro TTS needs espeak-ng phonemizer. "
    'Run: pip install -e ".[voice]"  (inside the Arelis virtualenv).'
)
_NO_ORT = (
    "Kokoro TTS needs onnxruntime. "
    'Run: pip install -e ".[voice]"  (inside the Arelis virtualenv).'
)


class KokoroUnavailableError(RuntimeError):
    """Weights, onnxruntime, or G2P are missing / unusable."""


def g2p_available() -> bool:
    return importlib_ok("phonemizer") and importlib_ok("espeakng_loader")


def importlib_ok(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def kokoro_files_present(model_path: Path | None = None, voices_path: Path | None = None) -> bool:
    model = Path(model_path) if model_path else _DEFAULT_MODEL
    voices = Path(voices_path) if voices_path else _DEFAULT_VOICES
    return model.is_file() and voices.is_file()


def prepare_kokoro_text(text: str) -> str:
    """Undo Piper's phonetic spelling so espeak sees the real name."""
    cleaned = _PIPER_NAME.sub("Arelis", text or "")
    return _ARELIS.sub("Arelis", cleaned)


class KokoroSynthesizer:
    """One loaded Kokoro session. Safe to call from a worker thread."""

    def __init__(
        self,
        *,
        model_path: Path | str | None = None,
        voices_path: Path | str | None = None,
        voice: str = DEFAULT_VOICE,
        speed: float = 1.0,
        allow_download: bool = True,
    ) -> None:
        self.model_path = Path(model_path) if model_path else _DEFAULT_MODEL
        self.voices_path = Path(voices_path) if voices_path else _DEFAULT_VOICES
        self.voice = (voice or DEFAULT_VOICE).strip() or DEFAULT_VOICE
        self.speed = _clean_speed(speed)
        self.allow_download = allow_download
        self._session = None
        self._input_names: set[str] = set()
        self._voices: dict[str, np.ndarray] = {}
        self._phoneme_lang = "en-us"
        self._speed_dtype = np.float32

    def problem(self) -> str | None:
        if not importlib_ok("onnxruntime"):
            return _NO_ORT
        if not g2p_available():
            return _NO_G2P
        if kokoro_files_present(self.model_path, self.voices_path):
            return None
        if self.allow_download:
            return None
        return (
            f"Kokoro model not found at {self.model_path} "
            f"(voices {self.voices_path}). See models/kokoro/README.md."
        )

    def ensure_loaded(self) -> None:
        """Download if needed, then load ONNX + voices + G2P once."""
        if self._session is not None:
            return
        problem = self.problem()
        if problem and not self.allow_download:
            raise KokoroUnavailableError(problem)
        if not importlib_ok("onnxruntime"):
            raise KokoroUnavailableError(_NO_ORT)
        if not g2p_available():
            raise KokoroUnavailableError(_NO_G2P)
        ensure_kokoro_files(
            self.model_path, self.voices_path, allow_download=self.allow_download
        )
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 2
        opts.log_severity_level = 3
        self._session = ort.InferenceSession(
            str(self.model_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self._input_names = {i.name for i in self._session.get_inputs()}
        self._speed_dtype = np.float32
        for item in self._session.get_inputs():
            if item.name == "speed" and "int" in (item.type or ""):
                self._speed_dtype = np.int32
        self._voices = _load_voices(self.voices_path)
        if self.voice not in self._voices:
            available = ", ".join(sorted(self._voices)[:12]) or "(none)"
            raise KokoroUnavailableError(
                f"Kokoro voice {self.voice!r} is not in {self.voices_path}. "
                f"Known (first): {available}"
            )
        british = self.voice.startswith("bf_") or self.voice.startswith("bm_")
        self._phoneme_lang = "en-gb" if british else "en-us"
        _configure_espeak()

    def synthesize(self, text: str, out_path: Path) -> Path:
        self.ensure_loaded()
        assert self._session is not None
        spoken = prepare_kokoro_text(text).strip()
        if not spoken:
            raise KokoroUnavailableError("Nothing to speak.")
        phonemes = _phonemize(spoken, self._phoneme_lang)
        phonemes = "".join(ch for ch in phonemes if ch in _VOCAB)
        if not phonemes.strip():
            raise KokoroUnavailableError("Kokoro G2P produced no speakable phonemes.")
        chunks = _split_phonemes(phonemes)
        style = self._voices[self.voice]
        audio_parts: list[np.ndarray] = []
        for chunk in chunks:
            part = self._infer_chunk(chunk, style)
            audio_parts.append(_trim_silence(part))
        samples = np.concatenate(audio_parts) if audio_parts else np.zeros(0, dtype=np.float32)
        _write_wav(out_path, samples, SAMPLE_RATE)
        return out_path

    def _infer_chunk(self, phonemes: str, style: np.ndarray) -> np.ndarray:
        assert self._session is not None
        ids = [i for i in (_VOCAB.get(ch) for ch in phonemes) if i is not None]
        if not ids:
            return np.zeros(0, dtype=np.float32)
        padded = np.array([[0, *ids, 0]], dtype=np.int64)
        style_vec = _style_for_tokens(style, len(ids))
        speed = np.array([self.speed], dtype=self._speed_dtype)
        feeds: dict[str, Any] = {}
        if "input_ids" in self._input_names:
            feeds["input_ids"] = padded
        elif "tokens" in self._input_names:
            feeds["tokens"] = padded
        else:
            name = next(iter(self._input_names), "input_ids")
            feeds[name] = padded
        if "style" in self._input_names:
            feeds["style"] = style_vec
        if "speed" in self._input_names:
            feeds["speed"] = speed
        feeds = {k: v for k, v in feeds.items() if k in self._input_names}
        raw = self._session.run(None, feeds)[0]
        audio = np.asarray(raw, dtype=np.float32).reshape(-1)
        return audio


def _configure_espeak() -> None:
    """Point phonemizer at the bundled espeak-ng, once per process."""
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
    EspeakWrapper.set_library(espeakng_loader.get_library_path())


def _phonemize(text: str, lang: str) -> str:
    import phonemizer

    _configure_espeak()
    raw = phonemizer.phonemize(
        text, lang, preserve_punctuation=True, with_stress=True
    )
    return str(raw or "")


def _clean_speed(value: Any) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(2.0, max(0.5, speed))


def _split_phonemes(phonemes: str) -> list[str]:
    if len(phonemes) <= MAX_PHONEME_LENGTH:
        return [phonemes]
    parts: list[str] = []
    current = ""
    for piece in re.split(r"([.,!?;])", phonemes):
        piece = piece.strip()
        if not piece:
            continue
        extra = 0 if piece in ".,!?;" else (1 if current else 0)
        if current and len(current) + extra + len(piece) >= MAX_PHONEME_LENGTH:
            parts.append(current.strip())
            current = piece
        elif piece in ".,!?;":
            current += piece
        else:
            current = f"{current} {piece}".strip() if current else piece
    if current.strip():
        parts.append(current.strip())
    return parts or [phonemes[:MAX_PHONEME_LENGTH]]


def _style_for_tokens(style: np.ndarray, n_tokens: int) -> np.ndarray:
    arr = np.asarray(style, dtype=np.float32)
    # Common layout: (max_len, 256) or (max_len, 1, 256)
    if arr.ndim == 3:
        index = min(max(n_tokens, 0), arr.shape[0] - 1)
        vec = arr[index]
    elif arr.ndim == 2 and arr.shape[0] > 8:
        index = min(max(n_tokens, 0), arr.shape[0] - 1)
        vec = arr[index]
    else:
        vec = arr
    vec = np.asarray(vec, dtype=np.float32)
    if vec.ndim == 1:
        vec = vec.reshape(1, -1)
    return vec


def _trim_silence(samples: np.ndarray, *, floor: float = 0.004) -> np.ndarray:
    if samples.size == 0:
        return samples
    amp = np.abs(samples)
    hits = np.where(amp > floor)[0]
    if hits.size == 0:
        return samples[:0]
    start = int(hits[0])
    end = int(hits[-1]) + 1
    return samples[start:end]


def _write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    frames = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(frames.tobytes())


def _load_voices(path: Path) -> dict[str, np.ndarray]:
    data = np.load(str(path), allow_pickle=True)
    if hasattr(data, "files"):
        return {name: np.asarray(data[name]) for name in data.files}
    if isinstance(data, np.ndarray) and data.dtype == object:
        item = data.item()
        if isinstance(item, dict):
            return {str(k): np.asarray(v) for k, v in item.items()}
    raise KokoroUnavailableError(f"Could not read Kokoro voices from {path}")


def ensure_kokoro_files(
    model_path: Path,
    voices_path: Path,
    *,
    allow_download: bool,
) -> None:
    if model_path.is_file() and voices_path.is_file():
        return
    if not allow_download:
        raise KokoroUnavailableError(
            f"Kokoro model not found at {model_path}. See models/kokoro/README.md."
        )
    import urllib.request

    for dest, url in ((model_path, _MODEL_URL), (voices_path, _VOICES_URL)):
        if dest.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        log.info("Downloading Kokoro TTS weights to %s", dest)
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            urllib.request.urlretrieve(url, tmp)
            tmp.replace(dest)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise KokoroUnavailableError(
                f"Could not download Kokoro file to {dest}: {exc}"
            ) from exc
        if not dest.is_file():
            raise KokoroUnavailableError(f"Kokoro file missing after download: {dest}")
