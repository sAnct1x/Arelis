"""Hardware E2E harness — CI-safe without ARELIS_HARDWARE_E2E."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "e2e_hardware_harness.py"


def _load_harness():
    name = "e2e_hardware_harness"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Dataclass evaluation needs the module registered first.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_harness_without_env_prints_checklist_and_exits_0() -> None:
    env = {k: v for k, v in os.environ.items() if k != "ARELIS_HARDWARE_E2E"}
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert "Operator hardware E2E checklist" in proc.stdout
    assert "barge-in" in proc.stdout.lower()


def test_hardware_e2e_enabled_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_harness()
    monkeypatch.delenv("ARELIS_HARDWARE_E2E", raising=False)
    assert mod.hardware_e2e_enabled() is False
    monkeypatch.setenv("ARELIS_HARDWARE_E2E", "1")
    assert mod.hardware_e2e_enabled() is True


def test_run_prereqs_with_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_harness()
    monkeypatch.setattr(mod, "probe_ollama", lambda: mod.Probe("ollama", True, "ok"))
    monkeypatch.setattr(
        mod, "probe_search", lambda: mod.Probe("search", True, "DuckDuckGo")
    )
    monkeypatch.setattr(
        mod, "probe_tesseract", lambda: mod.Probe("tesseract", False, "missing")
    )
    monkeypatch.setattr(
        mod, "probe_qt_audio", lambda: mod.Probe("audio", True, "inputs=1 outputs=1")
    )
    monkeypatch.setattr(
        mod,
        "probe_ingest_port",
        lambda port=8765: mod.Probe("notify", False, "down"),
    )
    probes = mod.run_prereqs()
    assert [p.key for p in probes] == [
        "ollama",
        "search",
        "tesseract",
        "audio",
        "notify",
    ]
    assert probes[0].ok and probes[3].ok


def test_force_json_main(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    mod = _load_harness()
    monkeypatch.setattr(
        mod,
        "run_prereqs",
        lambda include_notify=True: [
            mod.Probe("ollama", True, "ok"),
            mod.Probe("audio", True, "ok"),
        ],
    )
    code = mod.main(["--force", "--json", "--skip-notify"])
    assert code == 0
    out = capsys.readouterr().out
    assert '"ollama"' in out
