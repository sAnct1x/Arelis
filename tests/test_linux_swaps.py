"""Off-Windows swaps stay behind a platform check. Windows keeps the old path."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _mouse(kind, x: float, y: float, *, grab: bool):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    buttons = Qt.MouseButton.LeftButton if grab else Qt.MouseButton.NoButton
    pos = QPointF(x, y)
    return QMouseEvent(
        kind,
        pos,
        pos,
        Qt.MouseButton.LeftButton,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


class _Signal:
    def connect(self, _fn) -> None:
        return None


class _FakeProcess:
    def __init__(self, *_args, **_kwargs) -> None:
        self.program = ""
        self.arguments: list[str] = []
        self.finished = _Signal()
        self.errorOccurred = _Signal()

    def setWorkingDirectory(self, _path: str) -> None:
        return None

    def setProgram(self, program: str) -> None:
        self.program = program

    def setArguments(self, args: list[str]) -> None:
        self.arguments = list(args)

    def start(self) -> None:
        return None

    def deleteLater(self) -> None:
        return None


def _console_window(root: Path):
    return SimpleNamespace(
        workspace_roots=SimpleNamespace(active_root=lambda: SimpleNamespace(path=root)),
        workspace=SimpleNamespace(
            show_log=lambda *_a, **_k: None,
            set_console_busy=lambda *_a, **_k: None,
        ),
        _workspace_console=None,
    )


def test_linux_setup_explains_ollama_instead_of_downloading_the_exe(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    from arelis.ui.setup_wizard import _PrepareWorker
    from tests.test_setup_worker import _patch_wizard, _run_worker

    download = _patch_wizard(
        monkeypatch,
        tmp_path,
        ollama_reachable=lambda: False,
        find_ollama_exe=lambda: None,
    )["download_ollama_setup"]
    failed, ok, _progress = _run_worker(_PrepareWorker("qwen3.5:4b"))
    assert ok == []
    assert download.called is False
    assert failed
    text = failed[0].lower()
    assert "ollama.com" in text
    assert "install script" not in text
    assert "ollama" in text
    assert ".exe" not in text


def test_linux_console_uses_shell_then_pwsh_then_bash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("PySide6.QtCore.QProcess", _FakeProcess)
    from arelis.ui.workspace_host import run_user_console

    shell = tmp_path / "zsh"
    shell.write_text("", encoding="utf-8")
    monkeypatch.setenv("SHELL", str(shell))

    def is_file(self: Path) -> bool:
        return self == shell

    monkeypatch.setattr(Path, "is_file", is_file)
    window = _console_window(tmp_path)
    run_user_console(window, "date")
    proc = window._workspace_console
    assert proc.program == str(shell)
    assert proc.arguments == ["-c", "date"]

    monkeypatch.delenv("SHELL", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/pwsh" if name == "pwsh" else None)
    window = _console_window(tmp_path)
    run_user_console(window, "date")
    assert window._workspace_console.program == "/usr/bin/pwsh"
    assert window._workspace_console.arguments[-1] == "date"
    assert "-Command" in window._workspace_console.arguments

    monkeypatch.setattr(shutil, "which", lambda _name: None)

    def bash_exists(self: Path) -> bool:
        return self.as_posix() == "/bin/bash"

    monkeypatch.setattr(Path, "is_file", bash_exists)
    window = _console_window(tmp_path)
    run_user_console(window, "date")
    assert window._workspace_console.program == "/bin/bash"
    assert window._workspace_console.arguments == ["-c", "date"]

    monkeypatch.setattr(Path, "is_file", lambda _self: False)
    window = _console_window(tmp_path)
    run_user_console(window, "date")
    assert window._workspace_console.program == "/bin/sh"
    assert window._workspace_console.arguments == ["-c", "date"]


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


