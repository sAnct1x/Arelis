"""Download the voice weights a first "Hey Arelis" actually needs.

The setup `.exe` does not ship Sherpa, Kokoro, Silero, or Smart Turn. Those
land the first time someone talks — or during first-open model setup, so the
idle line is not still lying when they say the wake phrase.

This module has no Qt. The wizard and VoiceService.preload share it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arelis.paths import resolve_model_path

log = logging.getLogger(__name__)

Progress = Callable[[str, int, int], None]


def _voice(config: dict[str, Any] | None) -> dict[str, Any]:
    block = (config or {}).get("voice")
    return block if isinstance(block, dict) else {}


def _allow(value: object, default: bool = True) -> bool:
    if value is None:
        return default
    return bool(value)


def missing_voice_parts(
    config: dict[str, Any] | None = None,
    *,
    allowed_only: bool = False,
) -> list[str]:
    """Human labels for weights that are not on disk yet. Order is fetch order.

    ``allowed_only`` keeps parts we are allowed to download, so a test that
    turns downloads off does not look like a first-run fetch.
    """
    voice = _voice(config)
    missing: list[str] = []

    from arelis.voice.sherpa_stt import resolve_model_dir, sherpa_files_present

    stt = voice.get("stt") if isinstance(voice.get("stt"), dict) else {}
    if not sherpa_files_present(resolve_model_dir(stt)):
        if not allowed_only or _allow(stt.get("allow_download"), True):
            missing.append("the ear")

    from arelis.voice.silero_vad import default_model_path

    vad = voice.get("vad") if isinstance(voice.get("vad"), dict) else {}
    silero = str(vad.get("model_path") or "").strip()
    silero_path = Path(silero) if silero else default_model_path()
    if not silero_path.is_file():
        if not allowed_only or _allow(vad.get("allow_download"), True):
            missing.append("the pause")

    from arelis.voice.kokoro_tts import kokoro_files_present

    tts = voice.get("tts") if isinstance(voice.get("tts"), dict) else {}
    model = resolve_model_path(str(tts.get("kokoro_model") or "models/kokoro/kokoro-v1.0.onnx"))
    voices = resolve_model_path(
        str(tts.get("kokoro_voices") or "models/kokoro/voices-v1.0.bin")
    )
    if not kokoro_files_present(model, voices):
        if not allowed_only or _allow(tts.get("allow_download"), True):
            missing.append("her voice")

    conversation = voice.get("conversation") if isinstance(voice.get("conversation"), dict) else {}
    smart = conversation.get("smart_turn")
    if smart is False:
        return missing
    smart_cfg = smart if isinstance(smart, dict) else {}
    if not _allow(smart_cfg.get("enabled"), True):
        return missing
    from arelis.voice.smart_turn import _DEFAULT_MODEL

    raw = str(smart_cfg.get("model_path") or "").strip()
    target = Path(raw) if raw else _DEFAULT_MODEL
    if not target.is_file():
        if not allowed_only or _allow(smart_cfg.get("allow_download"), True):
            missing.append("the turn")
    return missing


def prepare_voice_files(
    config: dict[str, Any] | None = None,
    progress: Progress | None = None,
) -> list[str]:
    """Fetch anything missing. Fail-soft per part. Returns labels that landed."""
    voice = _voice(config)
    fetched: list[str] = []

    def report(status: str) -> None:
        if progress is not None:
            progress(status, 0, 0)

    stt = voice.get("stt") if isinstance(voice.get("stt"), dict) else {}
    if _allow(stt.get("allow_download"), True):
        from arelis.voice.sherpa_stt import (
            ensure_sherpa_files,
            resolve_model_dir,
            sherpa_files_present,
        )

        root = resolve_model_dir(stt)
        if not sherpa_files_present(root):
            report("Getting the ear…")
            try:
                ensure_sherpa_files(root, allow_download=True)
                fetched.append("the ear")
            except Exception as exc:
                log.warning("Could not get the ear: %s", exc)

    vad = voice.get("vad") if isinstance(voice.get("vad"), dict) else {}
    if _allow(vad.get("allow_download"), True):
        from arelis.voice.silero_vad import default_model_path, ensure_silero_model

        raw = str(vad.get("model_path") or "").strip()
        path = Path(raw) if raw else default_model_path()
        if not path.is_file():
            report("Getting the pause…")
            try:
                ensure_silero_model(path)
                fetched.append("the pause")
            except Exception as exc:
                log.warning("Could not get the pause: %s", exc)

    tts = voice.get("tts") if isinstance(voice.get("tts"), dict) else {}
    if _allow(tts.get("allow_download"), True):
        from arelis.voice.kokoro_tts import ensure_kokoro_files, kokoro_files_present

        model = resolve_model_path(
            str(tts.get("kokoro_model") or "models/kokoro/kokoro-v1.0.onnx")
        )
        voices = resolve_model_path(
            str(tts.get("kokoro_voices") or "models/kokoro/voices-v1.0.bin")
        )
        if not kokoro_files_present(model, voices):
            report("Getting her voice…")
            try:
                ensure_kokoro_files(model, voices, allow_download=True)
                fetched.append("her voice")
            except Exception as exc:
                log.warning("Could not get her voice: %s", exc)

    conversation = voice.get("conversation") if isinstance(voice.get("conversation"), dict) else {}
    smart = conversation.get("smart_turn")
    smart_cfg = smart if isinstance(smart, dict) else {}
    if smart is not False and _allow(smart_cfg.get("enabled"), True):
        if _allow(smart_cfg.get("allow_download"), True):
            from arelis.voice.smart_turn import _DEFAULT_MODEL, ensure_smart_turn_model

            raw = str(smart_cfg.get("model_path") or "").strip()
            target = Path(raw) if raw else _DEFAULT_MODEL
            if not target.is_file():
                report("Getting the turn…")
                try:
                    ensure_smart_turn_model(target, allow_download=True)
                    fetched.append("the turn")
                except Exception as exc:
                    log.warning("Could not get the turn: %s", exc)

    return fetched
