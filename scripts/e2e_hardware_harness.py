"""Operator UI/voice hardware E2E harness.

Default (no env): print the checklist and exit 0 — safe for CI / plain pytest.
With ``ARELIS_HARDWARE_E2E=1``: run local prereq probes, optionally the desktop
bus smoke, then print the remaining human voice/Notify steps.

Does not fake headset audio. Voice barge-in and Notify still need a person.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENV_FLAG = "ARELIS_HARDWARE_E2E"


@dataclass
class Probe:
    key: str
    ok: bool
    detail: str


def hardware_e2e_enabled() -> bool:
    raw = (os.environ.get(ENV_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def probe_ollama(base_url: str = "http://127.0.0.1:11434") -> Probe:
    try:
        import httpx

        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=2.0)
        if response.status_code >= 400:
            return Probe("ollama", False, f"HTTP {response.status_code}")
        return Probe("ollama", True, f"ok ({base_url})")
    except Exception as exc:
        return Probe("ollama", False, str(exc))


def probe_search() -> Probe:
    """DuckDuckGo needs no local service; chip is config-enabled only."""
    return Probe("search", True, "DuckDuckGo (no local search container)")


def probe_tesseract() -> Probe:
    path = shutil.which("tesseract")
    if path:
        return Probe("tesseract", True, path)
    return Probe("tesseract", False, "not on PATH (ocr soft-fails)")


def probe_qt_audio() -> Probe:
    """List input/output devices when QtMultimedia is available."""
    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtMultimedia import QMediaDevices

        app = QCoreApplication.instance()
        owns = False
        if app is None:
            app = QCoreApplication([])
            owns = True
        try:
            inputs = QMediaDevices.audioInputs()
            outputs = QMediaDevices.audioOutputs()
            in_n = len(inputs)
            out_n = len(outputs)
            ok = in_n > 0 and out_n > 0
            detail = f"inputs={in_n} outputs={out_n}"
            if inputs:
                detail += f" default_in={inputs[0].description()!r}"
            if outputs:
                detail += f" default_out={outputs[0].description()!r}"
            return Probe("audio", ok, detail)
        finally:
            if owns:
                app.quit()
    except Exception as exc:
        return Probe("audio", False, f"QtMultimedia unavailable: {exc}")


def probe_ingest_port(port: int = 8765) -> Probe:
    try:
        from arelis.presence.lock import probe_ingest_health

        if probe_ingest_health(port=port):
            return Probe("notify", True, f"ingest listening on :{port}")
        return Probe(
            "notify",
            False,
            f"nothing on :{port} — start UI/core with inbound enabled",
        )
    except Exception as exc:
        return Probe("notify", False, str(exc))


def run_prereqs(*, include_notify: bool = True) -> list[Probe]:
    probes = [
        probe_ollama(),
        probe_search(),
        probe_tesseract(),
        probe_qt_audio(),
    ]
    if include_notify:
        probes.append(probe_ingest_port())
    return probes


def checklist() -> list[str]:
    return [
        "Start UI (or core+UI). Confirm readiness chips: Ollama, Search, OCR.",
        "Typed: invent 17*19 -> calculator (or hard refuse).",
        "Typed: news ask -> web_search + scrape + Sources http(s) only.",
        "Voice: speak a short question; provisional STT supersede / barge-in once.",
        "Headset (if available): same barge-in path with headset default device.",
        "Research follow-up within ~45s stays warm (no cold TTFT spike).",
        "Notify companion: View -> Phone Notify URL...; send a test inbound SMS.",
        "Tray Quit returns in <5s.",
        "Optional: scripts/e2e_desktop_smoke.py for bus+Ollama cases without Qt clicks.",
    ]


def print_checklist() -> None:
    print("Operator hardware E2E checklist")
    print(f"(set {ENV_FLAG}=1 to run automated prereq probes)\n")
    for i, step in enumerate(checklist(), start=1):
        print(f"  {i}. {step}")


def main(argv: list[str] | None = None) -> int:
    # Windows consoles are often cp1252; keep checklist ASCII-safe and soft-fail.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"Run probes even without {ENV_FLAG}=1",
    )
    parser.add_argument(
        "--with-desktop-smoke",
        action="store_true",
        help="After probes, run scripts/e2e_desktop_smoke.py (needs Ollama).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit probe results as JSON on stdout",
    )
    parser.add_argument(
        "--skip-notify",
        action="store_true",
        help="Do not require inbound ingest on :8765",
    )
    args = parser.parse_args(argv)

    if not args.force and not hardware_e2e_enabled():
        print_checklist()
        return 0

    probes = run_prereqs(include_notify=not args.skip_notify)
    if args.json:
        print(json.dumps([asdict(p) for p in probes], indent=2))
    else:
        print("Hardware E2E prereqs\n")
        for p in probes:
            mark = "OK " if p.ok else "FAIL"
            print(f"  [{mark}] {p.key}: {p.detail}")
        print()
        print_checklist()

    hard_fail = [p for p in probes if not p.ok and p.key in {"ollama", "audio"}]
    if hard_fail:
        print("\nHard prereqs failed:", ", ".join(p.key for p in hard_fail))
        return 2

    if args.with_desktop_smoke:
        smoke = ROOT / "scripts" / "e2e_desktop_smoke.py"
        print(f"\nRunning {smoke.name} …")
        proc = subprocess.run([sys.executable, str(smoke)], cwd=str(ROOT))
        return int(proc.returncode)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
