from __future__ import annotations

import asyncio
import importlib.util
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from arelis.config import PROJECT_ROOT
from arelis.voice.kokoro_tts import (
    KokoroSynthesizer,
    KokoroUnavailableError,
    g2p_available,
    kokoro_files_present,
)

log = logging.getLogger(__name__)

# Piper takes its model as an .onnx file, but it also reads a sibling
# .onnx.json holding the sample rate, the phoneme map, and the speaker list.
# Downloading only the .onnx is the most common way to get this wrong, and
# piper's own error for it is a stack trace, so the pair is checked by name.
_CONFIG_SUFFIX = ".onnx.json"

_NO_BINARY = (
    "Piper is not installed. Run: pip install piper-tts  (inside the Arelis "
    "virtualenv). If you have a piper binary elsewhere, set voice.tts.piper_exe "
    "to its full path in arelis/config/default.yaml."
)
_NO_MODEL = (
    "No Piper voice is configured. Set voice.tts.voice_model in "
    "arelis/config/default.yaml to a feminine .onnx voice, for example "
    "models/piper/en_GB-jenny_dioco-medium.onnx. See the Voice section of "
    "README.md for how to download one."
)

# Two generations of piper CLI are in the wild and they disagree about both the
# flags and where the text comes from. The current pip package takes the text as
# an argument after "--"; the archived 2023 binary reads it from stdin. Rather
# than making the user work out which one they have, both are tried and the one
# that works is remembered for the rest of the session.
_MODERN = "modern"
_LEGACY = "legacy"
_STYLES: tuple[str, ...] = (_MODERN, _LEGACY)

# Piper scales phoneme durations, so this changes tempo without touching pitch:
# it is a slower or faster reading, not a resampled one, and there is no
# chipmunk effect at either end. Below about 0.7 the consonants start to smear.
_MIN_LENGTH_SCALE = 0.5
_MAX_LENGTH_SCALE = 2.0


class TextToSpeech:
    """Speech out: Kokoro on CPU when available, Piper as fallback.

    Conversation mode, barge-in, and the sentence queue live elsewhere. This
    class only turns one already-scrubbed sentence into a WAV.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        voice = config.get("voice", {}).get("tts", {})
        # Tests and explicit piper configs omit backend; production yaml uses auto.
        self.backend = str(voice.get("backend") or "piper").strip().lower()
        self.voice_model = _resolve_model(voice.get("voice_model") or "")
        self.command = _resolve_command(voice.get("piper_exe") or "")
        self.length_scale = _clean_length_scale(voice.get("length_scale", 1.0))
        self._style: str | None = None
        # Piper has changed its argument names across releases and users run
        # whichever build they installed. A speed setting is a comfort, so it is
        # never allowed to be the reason speech stops working: if the flag is
        # rejected, it is dropped for the rest of the session and she talks at
        # the model's own pace instead.
        self._speed_supported = True
        self._kokoro = KokoroSynthesizer(
            model_path=_resolve_model(voice.get("kokoro_model") or "") or None,
            voices_path=_resolve_model(voice.get("kokoro_voices") or "") or None,
            voice=str(voice.get("kokoro_voice") or "af_heart"),
            speed=voice.get("speed", 1.0),
            allow_download=bool(voice.get("allow_download", True)),
        )
        self._kokoro_failed = False

    def available(self) -> bool:
        return self.problem() is None

    def _use_kokoro(self) -> bool:
        if self.backend == "piper" or self._kokoro_failed:
            return False
        if self.backend == "kokoro":
            return True
        # auto: only when the engine can actually run, so Piper tests and a
        # missing first download still speak.
        if not g2p_available():
            return False
        if kokoro_files_present(self._kokoro.model_path, self._kokoro.voices_path):
            return True
        return bool(self._kokoro.allow_download) and self.backend == "auto"

    def problem(self) -> str | None:
        """Why synthesis cannot run, phrased as something the user can act on."""
        if self.backend not in {"piper", "kokoro", "auto"}:
            return (
                f"Unknown TTS backend {self.backend!r}. "
                "Use auto, kokoro, or piper."
            )
        if self._use_kokoro():
            issue = self._kokoro.problem()
            if issue is None:
                return None
            if self.backend == "kokoro":
                return issue
            piper_issue = self._piper_problem()
            return piper_issue
        return self._piper_problem()

    def _piper_problem(self) -> str | None:
        if not self.voice_model:
            return _NO_MODEL
        model = Path(self.voice_model)
        if not model.exists():
            return f"Piper voice model not found at {model}. {_NO_MODEL}"
        sidecar = model.with_suffix(model.suffix + ".json")
        if not sidecar.exists():
            return (
                f"Found {model.name} but not {sidecar.name}. Piper needs both: "
                f"download the {_CONFIG_SUFFIX} file from the same folder as the "
                "voice and put it beside the .onnx."
            )
        if not self.command:
            return _NO_BINARY
        return None

    async def synthesize(self, text: str, out_path: str | Path) -> Path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if self._use_kokoro():
            try:
                return await asyncio.to_thread(self._kokoro.synthesize, text, out)
            except KokoroUnavailableError as exc:
                if self.backend == "kokoro":
                    raise RuntimeError(str(exc)) from exc
                log.warning("Kokoro TTS failed (%s); falling back to Piper.", exc)
                self._kokoro_failed = True
            except Exception as exc:
                if self.backend == "kokoro":
                    raise
                log.warning("Kokoro TTS failed (%s); falling back to Piper.", exc)
                self._kokoro_failed = True
        problem = self._piper_problem()
        if problem:
            raise RuntimeError(problem)
        # Piper is an external process that takes about as long as the speech
        # it produces. Running it inline would block the event loop, and that
        # loop is also carrying event delivery, the stop button, and the confirm
        # card, so the whole app would freeze for the length of the sentence.
        styles = (self._style,) if self._style else _STYLES
        last_error = "piper failed"
        for scale in self._speed_attempts():
            for style in styles:
                ok, last_error = await asyncio.to_thread(
                    self._synthesize_once, text, out, style, scale
                )
                if ok:
                    self._style = style
                    if scale is None and self._speed_supported:
                        self._speed_supported = False
                        log.warning(
                            "This Piper build rejected the speed flag; ignoring "
                            "voice.tts.length_scale for the rest of the session."
                        )
                    return out
        raise RuntimeError(last_error)

    def _speed_attempts(self) -> tuple[float | None, ...]:
        """The length scales to try, most wanted first.

        Only ever more than one entry on the first synthesis of a session, and
        only when a non-default speed was asked for. Once a working combination
        is found it is remembered, so the probe costs one extra piper run at
        most and never happens mid-conversation.
        """
        if self.length_scale is None or not self._speed_supported:
            return (None,)
        return (self.length_scale, None)

    def _synthesize_once(
        self, text: str, out: Path, style: str, length_scale: float | None
    ) -> tuple[bool, str]:
        """Run piper and judge the result, all inside the worker thread.

        The verdict is formed here rather than back on the loop so the stat of
        the output file happens off the loop too, along with the process.
        """
        proc = self._run_piper(text, out, style, length_scale)
        if proc.returncode == 0 and out.exists() and out.stat().st_size > 0:
            return True, ""
        error = proc.stderr.decode("utf-8", errors="replace").strip()
        return False, error or f"piper failed ({style} arguments, exit {proc.returncode})"

    def _run_piper(
        self, text: str, out: Path, style: str, length_scale: float | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        if style == _MODERN:
            argv = [*self.command, "-m", self.voice_model, "-f", str(out)]
            if length_scale is not None:
                argv += ["--length-scale", f"{length_scale:g}"]
            argv += ["--", text]
            stdin = b""
        else:
            argv = [*self.command, "--model", self.voice_model, "--output_file", str(out)]
            if length_scale is not None:
                argv += ["--length_scale", f"{length_scale:g}"]
            stdin = text.encode("utf-8")
        return subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            check=False,
            # Piper is a console program. Without this the desktop app flashes a
            # black window on every sentence it speaks.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


def _clean_length_scale(value: Any) -> float | None:
    """None when the model's own pace is wanted, so no flag is passed at all."""
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return None
    if scale <= 0 or abs(scale - 1.0) < 1e-6:
        return None
    return min(_MAX_LENGTH_SCALE, max(_MIN_LENGTH_SCALE, scale))


def _resolve_model(value: str) -> str:
    """Resolve a configured voice path against the repo, not the shell's cwd.

    Arelis is started from the Start menu as often as from a terminal, and a
    relative models/piper/... path has to mean the same thing either way.
    """
    if not value:
        return ""
    path = Path(value)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return str(path)


def _resolve_command(configured: str) -> list[str]:
    """Find a way to run piper, in order of how specific it is.

    The last fallback is the important one on Windows. pip install piper-tts
    puts piper.exe in the virtualenv's Scripts directory, which is only on PATH
    while the venv is activated, and Arelis is normally launched by a shortcut
    that never activates anything. Running it as a module through the same
    interpreter sidesteps that entirely.
    """
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        if path.exists():
            return [str(path)]
        found = shutil.which(configured)
        return [found] if found else []

    found = shutil.which("piper")
    if found:
        return [found]
    beside = Path(sys.executable).parent / ("piper.exe" if sys.platform == "win32" else "piper")
    if beside.exists():
        return [str(beside)]
    if importlib.util.find_spec("piper") is not None:
        return [sys.executable, "-m", "piper"]
    return []
