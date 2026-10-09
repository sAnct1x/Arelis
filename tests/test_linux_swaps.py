"""Off-Windows swaps stay behind a platform check. Windows keeps the old path."""

from __future__ import annotations

import json
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


def test_windows_runtime_dir_stays_localappdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "profile"))
    from arelis.setup.engine import runtime_dir

    assert runtime_dir() == tmp_path / "local" / "Arelis-runtime"


def test_linux_runtime_dir_uses_the_user_data_helper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "profile"))
    from arelis.setup.engine import runtime_dir

    got = runtime_dir()
    assert got == tmp_path / "Arelis-runtime"
    assert got != Path.home() / "AppData" / "Local" / "Arelis-runtime"


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
    assert "install script" in text
    assert "ollama" in text
    assert ".exe" not in text


def test_mac_setup_explains_the_app_or_homebrew(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
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
    text = failed[0].lower()
    assert "homebrew" in text or "ollama app" in text
    assert ".exe" not in text


def test_windows_setup_still_downloads_the_installer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, qt_app
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    from arelis.ui.setup_wizard import _PrepareWorker
    from tests.test_setup_worker import _patch_wizard, _run_worker

    names = _patch_wizard(
        monkeypatch,
        tmp_path,
        ollama_reachable=lambda: False,
        find_ollama_exe=lambda: Path(r"C:\Ollama\ollama.exe"),
    )
    # First lookup misses so the installer runs. Later lookups find the exe.
    seen = {"n": 0}

    def find_exe():
        seen["n"] += 1
        if seen["n"] == 1:
            return None
        return Path(r"C:\Ollama\ollama.exe")

    monkeypatch.setattr("arelis.ui.setup_wizard.find_ollama_exe", find_exe)
    names["run_ollama_setup"].return_value = None
    failed, ok, _progress = _run_worker(_PrepareWorker("qwen3.5:4b"))
    assert failed == []
    assert ok == [True]
    names["download_ollama_setup"].assert_called_once()
    dest = names["download_ollama_setup"].call_args.args[0]
    assert dest.name == "OllamaSetup.exe"


def test_windows_console_still_runs_powershell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("PySide6.QtCore.QProcess", _FakeProcess)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name: (
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
            if "powershell" in name
            else None
        ),
    )
    from arelis.ui.workspace_host import run_user_console

    window = _console_window(tmp_path)
    run_user_console(window, "Get-Date")
    proc = window._workspace_console
    assert proc.program.lower().endswith("powershell.exe")
    assert proc.arguments[:3] == ["-NoProfile", "-NonInteractive", "-Command"]
    assert proc.arguments[-1] == "Get-Date"


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


def test_linux_vram_uses_nvidia_smi_then_rocm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    from arelis.setup import hardware

    calls: list[list[str]] = []

    def which(name: str) -> str | None:
        if name == "nvidia-smi":
            return "/usr/bin/nvidia-smi"
        return None

    def hidden_run(args, **kwargs):
        calls.append(list(args))
        assert kwargs.get("timeout", 99) <= 8
        return SimpleNamespace(stdout="RTX 3060, 8192\n", returncode=0)

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr("arelis.hidden_proc.hidden_run", hidden_run)
    name, vram, _notes = hardware._probe_vram()
    assert calls[0][0] == "/usr/bin/nvidia-smi"
    assert "memory.total" in " ".join(calls[0])
    assert "3060" in name
    assert vram == 8192 * 1024 * 1024

    def which_rocm(name: str) -> str | None:
        if name == "rocm-smi":
            return "/usr/bin/rocm-smi"
        return None

    def hidden_rocm(args, **kwargs):
        calls.append(list(args))
        assert kwargs.get("timeout", 99) <= 8
        text = f"GPU[0] : Card series: Navi 21\nGPU[0] : VRAM Total Memory (B): {8 * 1024**3}\n"
        return SimpleNamespace(stdout=text, returncode=0)

    calls.clear()
    monkeypatch.setattr(shutil, "which", which_rocm)
    monkeypatch.setattr("arelis.hidden_proc.hidden_run", hidden_rocm)
    name, vram, _notes = hardware._probe_vram()
    assert calls[0][0] == "/usr/bin/rocm-smi"
    assert vram == 8 * 1024**3
    assert name

    def hidden_fail(args, **kwargs):
        raise OSError("probe down")

    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/bin/nvidia-smi" if name == "nvidia-smi" else None
    )
    monkeypatch.setattr("arelis.hidden_proc.hidden_run", hidden_fail)
    name, vram, _notes = hardware._probe_vram()
    assert name == ""
    assert vram is None


def test_mac_vram_reads_unified_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    from arelis.setup import hardware

    calls: list[list[str]] = []

    def hidden_run(args, **kwargs):
        calls.append(list(args))
        assert kwargs.get("timeout", 99) <= 8
        return SimpleNamespace(stdout=f"{16 * 1024**3}\n", returncode=0)

    monkeypatch.setattr(
        shutil, "which", lambda name: "/usr/sbin/sysctl" if name == "sysctl" else None
    )
    monkeypatch.setattr("arelis.hidden_proc.hidden_run", hidden_run)
    name, vram, _notes = hardware._probe_vram()
    assert calls[0][:3] == ["/usr/sbin/sysctl", "-n", "hw.memsize"]
    assert vram == 16 * 1024**3
    assert name


def test_windows_vram_stays_on_powershell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    from arelis.setup import hardware

    calls: list[list[str]] = []

    def hidden_run(args, **kwargs):
        calls.append(list(args))
        payload = json.dumps({"name": "Test GPU", "vram": 4096})
        return SimpleNamespace(stdout=payload, returncode=0)

    monkeypatch.setattr("arelis.hidden_proc.hidden_run", hidden_run)
    name, vram, _notes = hardware._probe_vram()
    assert calls[0][0] == "powershell"
    assert "-Command" in calls[0]
    assert name == "Test GPU"
    assert vram == 4096


def _path_ends(self: Path, suffix: str) -> bool:
    return str(self).replace("\\", "/").endswith(suffix)


def test_windows_chrome_path_wins_over_later_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARELIS_CHROME", raising=False)
    chromium = "not-used"

    def which(name: str) -> str | None:
        if name == "chromium":
            return chromium
        return None

    def is_file(self: Path) -> bool:
        text = str(self).replace("\\", "/")
        return text.endswith("Program Files/Google/Chrome/Application/chrome.exe") or text.endswith(
            "not-used"
        )

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(Path, "is_file", is_file)
    from arelis.browser.launch import chrome_executable

    found = chrome_executable()
    assert found is not None
    assert found.replace("\\", "/").endswith("Program Files/Google/Chrome/Application/chrome.exe")


def test_chrome_finds_linux_and_mac_browsers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARELIS_CHROME", raising=False)
    from arelis.browser.launch import chrome_executable

    def resolve(self: Path, strict: bool = False) -> Path:
        # Do not follow a real symlink on the machine running the test.
        del strict
        return Path(str(self).replace("\\", "/"))

    monkeypatch.setattr(Path, "resolve", resolve)

    cases = (
        "/usr/bin/chromium",
        "/snap/bin/chromium",
        "/var/lib/flatpak/exports/bin/org.chromium.Chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    )
    for suffix in cases:

        def is_file(self: Path, suffix: str = suffix) -> bool:
            return str(self).replace("\\", "/") == suffix

        def which(name: str, suffix: str = suffix) -> str | None:
            if suffix.endswith("/usr/bin/chromium") and name == "chromium":
                return suffix
            if suffix.endswith("google-chrome-stable") and name == "google-chrome-stable":
                return suffix
            return None

        monkeypatch.setattr(Path, "is_file", is_file)
        monkeypatch.setattr(shutil, "which", which)
        found = chrome_executable()
        assert found is not None, suffix
        assert found.replace("\\", "/").endswith(suffix), (suffix, found)

    stable = "/usr/bin/google-chrome-stable"

    def which_stable(name: str) -> str | None:
        if name == "google-chrome-stable":
            return stable
        return None

    def stable_file(self: Path) -> bool:
        return str(self).replace("\\", "/") == stable

    monkeypatch.setattr(shutil, "which", which_stable)
    monkeypatch.setattr(Path, "is_file", stable_file)
    found = chrome_executable()
    assert found is not None
    assert found.replace("\\", "/").endswith(stable)


def test_tesseract_windows_path_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    def is_file(self: Path) -> bool:
        text = str(self).replace("\\", "/")
        return text.endswith("Program Files/Tesseract-OCR/tesseract.exe") or text.endswith(
            "/opt/homebrew/bin/tesseract"
        )

    monkeypatch.setattr(Path, "is_file", is_file)
    from arelis.tools.ocr import _tesseract_exe

    found = _tesseract_exe()
    assert found is not None
    assert found.replace("\\", "/").endswith("Program Files/Tesseract-OCR/tesseract.exe")


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


def test_title_bar_uses_system_move_off_windows(monkeypatch: pytest.MonkeyPatch, qt_app) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QWidget

    from arelis.ui.chrome import TitleBar

    monkeypatch.setattr(sys, "platform", "linux")
    host = QWidget()
    host.resize(400, 200)
    moved: list[object] = []
    calls = {"n": 0, "ok": True}

    def start_system_move() -> bool:
        calls["n"] += 1
        return calls["ok"]

    handle = SimpleNamespace(startSystemMove=start_system_move)
    host.windowHandle = lambda: handle  # type: ignore[method-assign]
    original_move = host.move

    def track_move(*args):
        moved.append(args)
        return original_move(*args)

    host.move = track_move  # type: ignore[method-assign]
    bar = TitleBar(host)
    host.show()
    qt_app.processEvents()
    moved.clear()
    try:
        bar.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 12, 12, grab=True))
        bar.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 40, 18, grab=True))
        assert calls["n"] >= 1
        assert moved == []

        calls["ok"] = False
        calls["n"] = 0
        moved.clear()
        bar.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 12, 12, grab=True))
        bar.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 80, 30, grab=True))
        assert calls["n"] >= 1
        assert moved
    finally:
        host.close()


def test_title_bar_windows_drag_does_not_ask_the_system(
    monkeypatch: pytest.MonkeyPatch, qt_app
) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QWidget

    from arelis.ui.chrome import TitleBar

    monkeypatch.setattr(sys, "platform", "win32")
    host = QWidget()
    host.resize(400, 200)
    moved: list[object] = []
    calls = {"n": 0}

    def start_system_move() -> bool:
        calls["n"] += 1
        return True

    host.windowHandle = lambda: SimpleNamespace(startSystemMove=start_system_move)  # type: ignore[method-assign]
    original_move = host.move

    def track_move(*args):
        moved.append(args)
        return original_move(*args)

    host.move = track_move  # type: ignore[method-assign]
    bar = TitleBar(host)
    host.show()
    qt_app.processEvents()
    moved.clear()
    try:
        bar.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 12, 12, grab=True))
        bar.mouseMoveEvent(_mouse(QEvent.Type.MouseMove, 48, 20, grab=True))
        assert calls["n"] == 0
        assert moved
    finally:
        host.close()


def test_ci_jobs_that_install_arelis_use_the_qt_constraint() -> None:
    import yaml

    loaded = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    for job_name in ("eval", "installed", "test"):
        steps = loaded["jobs"][job_name]["steps"]
        blob = "\n".join(str(step.get("run") or "") for step in steps)
        assert "qt_constraints_from_installer_lock.py" in blob, job_name
        assert "pip install" in blob, job_name
        assert "-c " in blob, job_name


def test_pyside6_has_an_upper_bound_below_6_12() -> None:
    import tomllib

    from packaging.requirements import Requirement
    from packaging.version import Version

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = list(data["project"]["dependencies"])
    extras = data["project"].get("optional-dependencies") or {}
    for group in extras.values():
        deps.extend(group)
    named = {
        "pyside6": "PySide6",
        "pyside6-essentials": "PySide6-Essentials",
        "pyside6-addons": "PySide6-Addons",
        "shiboken6": "shiboken6",
    }
    seen = {key: False for key in named}
    for raw in deps:
        req = Requirement(raw)
        key = req.name.lower()
        if key not in seen:
            continue
        seen[key] = True
        upper = [
            spec
            for spec in req.specifier
            if spec.operator in {"<", "<="} and Version(spec.version) <= Version("6.12")
        ]
        assert upper, raw
        assert all(
            Version(spec.version) < Version("6.12") or spec.operator == "<" for spec in upper
        )
        if any(
            spec.operator == "<=" and Version(spec.version) >= Version("6.12")
            for spec in req.specifier
        ):
            raise AssertionError(raw)
    assert seen["pyside6"] is True
