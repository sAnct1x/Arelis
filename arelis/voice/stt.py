from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_MISSING_DEP = (
    "Speech recognition is not available. "
    'Install the voice extra: pip install -e ".[voice]"'
)

_WORD = re.compile(r"[a-z0-9]+", re.I)

# Whisper filler openers on short/noisy clips (YouTube-trained habits).
_HALLUCINATION_PREFIX = re.compile(
    r"(?is)^\s*(?:"
    r"(?:are you ready\??\s*)|"
    r"(?:thank you for watching\.?\s*)|"
    r"(?:thanks for watching\.?\s*)|"
    r"(?:please subscribe\.?\s*)|"
    r"(?:see you next time\.?\s*)|"
    r"(?:i'?ll see you in the next (?:video|one)\.?\s*)"
    r")+"
)

# Full-clip junk Whisper invents from burps, coughs, and barge-in of TTS.
_HALLUCINATION_CLIP = re.compile(
    r"(?is)^\s*(?:"
    r"(?:i(?:'m| am)?\s*[,.]?\s*)+a soldier[.!,]?\s*|"
    r"(?:i(?:'m| am) going to kill you[.!,]?\s*)+|"
    r"(?:thank you for watching[.!,]?\s*)+|"
    r"(?:thanks for watching[.!,]?\s*)+|"
    r"(?:please subscribe(?:\s+to\s+my\s+channel)?[.!,]?\s*)+|"
    r"(?:you[.!,]?\s*)+"
    r")\s*$"
)

# Mixed barge-in: peel the invented threat, keep "ok stop".
_HALLUCINATION_SPAN = re.compile(
    r"(?is)(?:^|\s+)(?:i(?:'m| am) going to kill you[.!,]?\s*)+"
)

# Barge-in of TTS often becomes a fake "I'm going to…" story, then the real cut.
_STOP_TAIL = re.compile(
    r"(?is)^(?P<lead>.+?)(?P<stop>(?:all\s+right|alright|ok(?:ay)?),?\s+stop)\s*$"
)

_STUTTER = re.compile(
    r"(?i)\b((?:i(?:'m)?|uh|um|ah|oh|like))(?:(?:\s*[,.]?\s+|\s+)\1)+\b"
)

# Tokens that belong to the wake phrase itself — not "jargon echo".
_WAKE_PROMPT_WORDS = frozenset(
    {
        "hey",
        "hi",
        "ok",
        "okay",
        "arelis",
        "airelyse",
        "airelease",
        "aurelis",
        "aurelyse",
        "arelyse",
        "arelys",
        "areliss",
        "arellis",
        "aerolyse",
        "orelis",
        "air",
        "elise",
        "elis",
        "a",
        "relis",
    }
)


def collapse_repeated_phrase(text: str) -> str:
    """Collapse 'Hello world. Hello world.' / doubled STT repeats into one."""
    raw = (text or "").strip()
    if not raw:
        return ""
    halves = re.match(
        r"(?is)^\s*(?P<a>.+?)\s*[.?!]?\s+(?P=a)\s*[.?!]?\s*$",
        raw,
    )
    if halves:
        return halves.group("a").strip()
    parts = re.split(r"(?<=[.?!])\s+", raw)
    if len(parts) >= 2:
        out: list[str] = []
        prev_norm = ""
        for part in parts:
            norm = re.sub(r"[^a-z0-9]+", "", part.lower())
            if norm and norm == prev_norm:
                continue
            out.append(part.strip())
            prev_norm = norm
        return " ".join(out).strip()
    return raw


def scrub_transcript(text: str) -> str:
    """Strip common Whisper junk and collapse accidental repeats."""
    raw = (text or "").strip()
    if not raw:
        return ""
    raw = _STUTTER.sub(r"\1", raw)
    raw = _HALLUCINATION_PREFIX.sub("", raw).strip()
    raw = _HALLUCINATION_SPAN.sub(" ", raw)
    raw = collapse_repeated_phrase(raw)
    raw = raw.strip(" ,.-")
    if _HALLUCINATION_CLIP.match(raw):
        return ""
    stop = _STOP_TAIL.match(raw)
    if stop is not None:
        lead = (stop.group("lead") or "").strip()
        if len(lead) >= 24 and re.match(r"(?i)^i(?:'m| am) going to\b", lead):
            return (stop.group("stop") or "stop").strip()
    return raw


def looks_like_prompt_echo(text: str, prompt: str) -> bool:
    """True when Whisper mostly regurgitated initial_prompt instead of speech.

    Short/noisy clips often come back as the bias prompt ("Arelis, Ollama,
    ComfyUI, Whisper…") rather than what the user said.

    Never treats a bare wake phrase as echo — the prompt is *supposed* to bias
    toward "Hey Arelis", and scrubbing that broke wake entirely.
    """
    from arelis.voice.wake import match_wake

    heard = (text or "").strip()
    seed = (prompt or "").strip()
    if not heard or not seed:
        return False

    rem = match_wake(heard)
    # Bare "Hey Arelis" / "Arelis" is a successful wake transcript, not echo.
    if rem is not None and not rem.strip():
        return False

    prompt_words = {w.lower() for w in _WORD.findall(seed)}
    jargon = prompt_words - _WAKE_PROMPT_WORDS
    # Wake-only prompts ("Hey Arelis.") have no jargon to echo-detect with.
    if len(jargon) < 2:
        return False

    # If there was a wake + remainder, judge the remainder (the command).
    check = rem.strip() if (rem is not None and rem.strip()) else heard
    text_words = [w.lower() for w in _WORD.findall(check)]
    if not text_words:
        return False
    if len(text_words) > 16:
        return False
    hits = sum(1 for w in text_words if w in jargon)
    compact_heard = " ".join(text_words)
    compact_jargon = " ".join(sorted(jargon))
    if compact_heard and len(text_words) >= 2:
        # Dense jargon dump (ollama comfyui whisper…).
        if hits >= 2 and (hits / len(text_words)) >= 0.5:
            return True
    if compact_jargon and compact_jargon in compact_heard:
        return True
    return False


def soften_stt_case(text: str) -> str:
    """Sherpa Zipformer often returns ALL CAPS. Parsers and chat should not shout."""
    raw = (text or "").strip()
    letters = [c for c in raw if c.isalpha()]
    if len(letters) < 6:
        return raw
    if (sum(1 for c in letters if c.isupper()) / len(letters)) < 0.8:
        return raw
    lower = raw.lower()
    parts = re.split(r"([.?!]\s+)", lower)
    out: list[str] = []
    cap_next = True
    for part in parts:
        if cap_next and part and part[0].isalpha():
            out.append(part[0].upper() + part[1:])
            cap_next = False
        else:
            out.append(part)
        if re.search(r"[.?!]\s*$", part):
            cap_next = True
    return "".join(out)


class SpeechToText:
    """Local STT adapter. Sherpa-ONNX by default; faster-whisper as fallback."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config.get("voice", {}).get("stt", {})
        self._model = None
        self._sherpa = None
        self._sherpa_failed = False
        self._lock = asyncio.Lock()

    def requested_backend(self) -> str:
        raw = str(self.config.get("backend") or "sherpa").strip().lower()
        if raw in {"faster-whisper", "faster_whisper", "whisper"}:
            return "faster-whisper"
        return "sherpa"

    def resolved_backend(self, *, purpose: str = "turn") -> str | None:
        """Which ear will actually run. None if neither backend can.

        Wake stays on faster-whisper: it is one short clip judged against a
        phrase, and Zipformer's habit of inventing an opener costs a wake. Every
        other purpose uses the configured backend.

        The choice is made from configuration and purpose only. An earlier
        version returned faster-whisper whenever its weights happened to be in
        memory, which meant the first idle wake clip loaded Whisper and every
        conversation turn for the rest of the session quietly went there too —
        Sherpa was configured, downloaded, and never used again.
        """
        whisper_ready = self._whisper_installed() or self._model is not None
        if purpose == "wake" and whisper_ready:
            return "faster-whisper"
        want = self.requested_backend()
        if want == "sherpa" and not self._sherpa_failed and self._sherpa_usable():
            return "sherpa"
        if whisper_ready:
            return "faster-whisper"
        return None

    def available(self) -> bool:
        return self.resolved_backend() is not None

    def loaded(self) -> bool:
        """True once the weights are in memory, so the caller can warn first."""
        if self.resolved_backend() == "sherpa":
            return self._sherpa_engine().loaded()
        return self._model is not None

    async def transcribe(
        self,
        audio_path: str | Path,
        *,
        proceed: Callable[[], bool] | None = None,
        purpose: str = "turn",
    ) -> str:
        """Transcribe a file without blocking the event loop.

        Both halves of this used to run inline in the async function: loading
        the model, which downloads weights on first use and takes tens of
        seconds, and the transcription itself, which is seconds of pure CPU.
        The loop carries event delivery, the stop button, and the confirm card,
        so either one froze the whole app. They run in a worker thread now.

        The lock serialises calls because neither backend is re-entrant, and
        because two overlapping presses would otherwise each construct their
        own copy of the weights.

        proceed is checked after the lock is acquired so a superseded wake clip
        can leave without burning seconds of STT while conversation waits.
        """
        if not self.available():
            raise RuntimeError(_MISSING_DEP)
        async with self._lock:
            if proceed is not None and not proceed():
                return ""
            return await asyncio.to_thread(
                self._transcribe_blocking, str(audio_path), purpose
            )

    async def preload(self) -> None:
        """Build the model ahead of time, off the loop. Safe to call twice."""
        if not self.available() or self.loaded():
            return
        async with self._lock:
            await asyncio.to_thread(self._ensure_active)

    def _transcribe_blocking(self, audio_path: str, purpose: str = "turn") -> str:
        if self.resolved_backend(purpose=purpose) == "sherpa":
            try:
                text = self._sherpa_engine().transcribe(audio_path)
            except Exception as exc:
                from arelis.voice.sherpa_stt import SherpaUnavailableError

                if isinstance(exc, SherpaUnavailableError) and self._whisper_installed():
                    log.warning("Sherpa STT unavailable (%s); using faster-whisper", exc)
                    self._sherpa_failed = True
                else:
                    raise
            else:
                return soften_stt_case(scrub_transcript(text))
        return soften_stt_case(self._transcribe_whisper(audio_path))

    def _transcribe_whisper(self, audio_path: str) -> str:
        model = self._ensure_model()
        language = self.config.get("language") or None
        prompt = str(self.config.get("initial_prompt") or "").strip() or None
        segments, _info = model.transcribe(
            audio_path,
            language=language,
            beam_size=int(self.config.get("beam_size", 1)),
            vad_filter=bool(self.config.get("vad_filter", False)),
            # Biases decoding toward the wake name. Keep the prompt short —
            # long jargon lists are often echoed as the whole transcript.
            initial_prompt=prompt,
            # Without this, Whisper can latch onto the prompt / prior text and
            # invent loops on short or noisy clips.
            condition_on_previous_text=False,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        text = scrub_transcript(text)
        if prompt and looks_like_prompt_echo(text, prompt):
            return ""
        return text

    def _ensure_active(self) -> None:
        if self.resolved_backend() == "sherpa":
            try:
                self._sherpa_engine().ensure_loaded()
                return
            except Exception as exc:
                from arelis.voice.sherpa_stt import SherpaUnavailableError

                if isinstance(exc, SherpaUnavailableError) and self._whisper_installed():
                    log.warning("Sherpa STT preload failed (%s); using faster-whisper", exc)
                    self._sherpa_failed = True
                else:
                    raise
        self._ensure_model()

    def _ensure_model(self):
        """Construct the Whisper model. Only ever called inside a worker thread."""
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        size = self.config.get("model_size", "base")
        device = self.config.get("device", "cpu")
        # int8 on CPU is roughly three times faster than float32 for a
        # negligible accuracy cost at these model sizes, and this runs on a
        # machine whose GPU is reserved for the language models.
        compute_type = self.config.get("compute_type") or (
            "int8" if device == "cpu" else "default"
        )
        self._model = WhisperModel(size, device=device, compute_type=compute_type)
        return self._model

    def _sherpa_engine(self):
        if self._sherpa is None:
            from arelis.voice.sherpa_stt import SherpaSpeechToText

            self._sherpa = SherpaSpeechToText(self.config)
        return self._sherpa

    def _sherpa_usable(self) -> bool:
        from arelis.voice.sherpa_stt import sherpa_usable

        return sherpa_usable(self.config)

    def _whisper_installed(self) -> bool:
        try:
            import faster_whisper  # noqa: F401

            return True
        except ImportError:
            return False
