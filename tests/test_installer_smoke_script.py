"""Pure helpers from scripts/installer_smoke.py (no Windows required)."""

from __future__ import annotations

import importlib.util
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
