"""Pure helpers from scripts/installer_smoke.py (no Windows required)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "installer_smoke.py"


def _mod():
    spec = importlib.util.spec_from_file_location("installer_smoke", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parse_version_from_filename() -> None:
    m = _mod()
    assert m.parse_version_from_filename("Arelis-0.2.9-win64-setup.exe") == "0.2.9"
    assert m.parse_version_from_filename("Arelis-0.3.0-win64-setup.exe") == "0.3.0"


def test_parse_sha256_file() -> None:
    m = _mod()
    digest, name = m.parse_sha256_file(
        "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899  "
        "Arelis-0.3.0-win64-setup.exe\n"
    )
    assert digest.startswith("aabbcc")
    assert name.endswith("setup.exe")


def test_classify_qtopengl_failure() -> None:
    m = _mod()
    assert m.classify_qtopengl_failure("ModuleNotFoundError: No module named 'PySide6.QtOpenGL'")
    assert not m.classify_qtopengl_failure("some other ImportError")


def test_window_title_filter() -> None:
    m = _mod()
    assert m.window_title_ok("Arelis")
    assert not m.window_title_ok("")
    assert not m.window_title_ok("   ")


def test_welcome_title_ok() -> None:
    m = _mod()
    assert m.welcome_title_ok("Welcome to Arelis")
    assert not m.welcome_title_ok("Arelis")
    assert not m.welcome_title_ok("")


def test_seed_completed_first_run_profile(tmp_path: Path) -> None:
    m = _mod()
    data_dir = tmp_path / "profile"
    root = m.seed_completed_first_run_profile(data_dir, tag="qwen3.5:9b")
    marker = json.loads((data_dir / "data" / "first-run.json").read_text(encoding="utf-8"))
    assert marker["model_setup"]["complete"] is True
    assert marker["model_setup"]["tag"] == "qwen3.5:9b"
    assert marker["workspace_root"] == str(root)
    local = (data_dir / "data" / "config.local.yaml").read_text(encoding="utf-8")
    assert "qwen3.5:9b" in local
    assert json.dumps(str(root)) in local
    # Welcome title is a separate check; seeding is for the main window only.
    assert not m.welcome_title_ok("Arelis")

