#!/usr/bin/env python3
"""Pre-flight check for voice sensing (Silero live VAD + openWakeWord).

Run before a headset soak:

  .\\.venv\\Scripts\\python.exe scripts\\check_voice_sensing.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from arelis.config import load_config
    from arelis.voice.openwake import default_wake_model_path, openwake_available
    from arelis.voice.silero_vad import default_model_path, silero_available
    from arelis.voice.vad import DetectorConfig, make_utterance_detector

    cfg = load_config()
    voice = cfg.get("voice") or {}
    vad = voice.get("vad") or {}
    wake = voice.get("wake") or {}
    stt = voice.get("stt") or {}

    print(f"python: {sys.executable}")
    print(f"voice.vad.backend (config): {vad.get('backend')}")
    print(f"voice.wake.engine (config): {wake.get('engine')}")
    print(f"voice.stt.vad_filter: {stt.get('vad_filter')}")
    print()

    ort_ok = importlib.util.find_spec("onnxruntime") is not None
    oww_pkg = importlib.util.find_spec("openwakeword") is not None
    fw_ok = importlib.util.find_spec("faster_whisper") is not None
    print(f"onnxruntime: {'OK' if ort_ok else 'MISSING'}")
    print(f"faster-whisper: {'OK' if fw_ok else 'MISSING'}")
    print(f"openwakeword pkg: {'OK' if oww_pkg else 'MISSING'}")
    print()

    silero_path = default_model_path()
    print(f"Silero model: {silero_path}")
    print(f"  exists: {silero_path.is_file()}  silero_available: {silero_available()}")
    det = make_utterance_detector(
        str(vad.get("backend") or "silero"),
        DetectorConfig(),
        allow_download=bool(vad.get("allow_download", True)),
    )
    print(f"  factory backend in use: {det.backend}")
    print()

    wake_path = default_wake_model_path()
    print(f"Wake model: {wake_path}")
    print(f"  exists: {wake_path.is_file()}  openwake_available: {openwake_available()}")
    engine = str(wake.get("engine") or "auto").strip().lower()
    if engine == "auto":
        effective = "openwakeword" if openwake_available() else "whisper"
    else:
        effective = engine
    print(f"  effective wake engine at boot: {effective}")
    if effective == "whisper":
        print(
            "  note: idle wake still uses Whisper until hey_arelis.onnx is trained "
            "(see models/wake/README.md)."
        )
    print()

    ok = det.backend == "silero" and fw_ok and ort_ok
    if ok:
        print("READY for Silero conversation soak (headset).")
        print("Focus test: after TTS + Listening again, quiet 'thanks' once.")
        return 0
    print("NOT READY — fix MISSING items above, then re-run.")
    print('  .\\.venv\\Scripts\\python.exe -m pip install -e ".[voice]"')
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
