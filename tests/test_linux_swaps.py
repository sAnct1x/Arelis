"""Off-Windows swaps stay behind a platform check. Windows keeps the old path."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest


def _path_ends(self: Path, suffix: str) -> bool:
    return str(self).replace("\\", "/").endswith(suffix)


def test_tesseract_unix_paths_and_plain_message(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    def is_file(self: Path) -> bool:
        return _path_ends(self, "/opt/homebrew/bin/tesseract")

    monkeypatch.setattr(Path, "is_file", is_file)
    from arelis.tools.ocr import _tesseract_exe, run_tesseract_inspect

    found = _tesseract_exe()
    assert found is not None
    assert "homebrew" in found.replace("\\", "/")

    monkeypatch.setattr(sys, "platform", "linux")

    def usr(self: Path) -> bool:
        return _path_ends(self, "/usr/bin/tesseract")

    monkeypatch.setattr(Path, "is_file", usr)
    found = _tesseract_exe()
    assert found is not None
    assert found.replace("\\", "/").endswith("/usr/bin/tesseract")

    monkeypatch.setattr("arelis.tools.ocr._tesseract_exe", lambda: None)
    image = tmp_path / "page.png"
    image.write_bytes(b"")
    with pytest.raises(RuntimeError) as raised:
        run_tesseract_inspect(image)
    text = str(raised.value)
    assert "UB Mannheim" not in text
    assert "for Windows" not in text
    assert "tesseract" in text.lower()
    assert "install" in text.lower()
