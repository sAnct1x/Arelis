"""Mac source run: launchd jobs, login start, caches, and browser paths.

Windows Task Scheduler stays the Windows backend. Linux stays unsupported.
Tests redirect LaunchAgents at a temp folder and mock launchctl. They never
write ~/Library.
"""

from __future__ import annotations

import plistlib
import sys
from pathlib import Path

import pytest

from arelis.jobs.store import Job


class _Done:
    def __init__(self, code: int = 0, out: str = "", err: str = "") -> None:
        self.returncode = code
        self.stdout = out
        self.stderr = err


def _job(**kwargs: object) -> Job:
    base: dict[str, object] = {
        "id": "news",
        "name": "News",
        "prompt": "What happened today",
        "times": ["19:00"],
    }
    base.update(kwargs)
    return Job(**base)  # type: ignore[arg-type]


def _agents(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    folder = tmp_path / "LaunchAgents"
    folder.mkdir()
    monkeypatch.setenv("ARELIS_LAUNCH_AGENTS", str(folder))
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "data"))
    return folder


def test_windows_scheduling_still_uses_schtasks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("ARELIS_DATA_DIR", str(tmp_path / "data"))
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> _Done:
        calls.append(list(args))
        return _Done()

    monkeypatch.setattr("arelis.jobs.schedule.subprocess.run", fake_run)
    from arelis.jobs.schedule import register, supported

    assert supported() is True
    register(_job())
    assert calls
    assert calls[0][0] == "schtasks"
    assert all(item[0] != "launchctl" for item in calls)


def test_linux_scheduling_stays_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    from arelis.jobs.schedule import ScheduleError, register, supported

    assert supported() is False
    with pytest.raises(ScheduleError):
        register(_job())


def test_mac_scheduling_is_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    from arelis.jobs.schedule import supported

    assert supported() is True


def test_mac_register_writes_a_plist_and_bootstraps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    folder = _agents(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def fake_run(args: list[str], **kwargs: object) -> _Done:
        calls.append(list(args))
        assert kwargs.get("timeout") == 30
        return _Done()

    monkeypatch.setattr("arelis.jobs.launchd.hidden_run", fake_run)
    from arelis.jobs.schedule import register

    register(_job(days=["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]))
    plist_path = folder / "app.arelis.job.news.plist"
    assert plist_path.is_file()
    with plist_path.open("rb") as handle:
        loaded = plistlib.load(handle)
    assert loaded["Label"] == "app.arelis.job.news"
    args = loaded["ProgramArguments"]
    assert args[0] == sys.executable
    assert args[1:4] == ["-m", "arelis", "--run-job"]
    assert args[4] == "news"
    interval = loaded["StartCalendarInterval"]
    assert {"Hour": 19, "Minute": 0} in interval
    assert all("Weekday" not in item for item in interval)
    assert calls[0][0] == "launchctl"
    assert calls[0][1] == "bootstrap"
    assert calls[0][2].startswith("gui/")
    assert calls[0][3] == str(plist_path)


def test_mac_weekday_and_one_off_intervals(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    folder = _agents(monkeypatch, tmp_path)
    monkeypatch.setattr("arelis.jobs.launchd.hidden_run", lambda *_a, **_k: _Done())
    from arelis.jobs.schedule import register

    register(_job(id="stand", days=["monday"], times=["07:30"]))
    with (folder / "app.arelis.job.stand.plist").open("rb") as handle:
        weekly = plistlib.load(handle)
    assert weekly["StartCalendarInterval"] == [{"Weekday": 1, "Hour": 7, "Minute": 30}]

    register(
        _job(
            id="once",
            repeat="once",
            date="2026-10-08",
            times=["08:00"],
            every_minutes=120,
        )
    )
    with (folder / "app.arelis.job.once.plist").open("rb") as handle:
        once = plistlib.load(handle)
    slots = once["StartCalendarInterval"]
    assert {"Month": 10, "Day": 8, "Hour": 8, "Minute": 0} in slots
    assert {"Month": 10, "Day": 8, "Hour": 10, "Minute": 0} in slots


def test_mac_bootstrap_falls_back_to_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    _agents(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> _Done:
        calls.append(list(args))
        if args[1] == "bootstrap":
            return _Done(code=1, err="failed")
        return _Done()

    monkeypatch.setattr("arelis.jobs.launchd.hidden_run", fake_run)
    from arelis.jobs.schedule import register

    register(_job())
    assert ["launchctl", "load", "-w"] == [calls[1][0], calls[1][1], calls[1][2]]


def test_mac_unregister_boots_out_then_unloads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    folder = _agents(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> _Done:
        calls.append(list(args))
        if args[1] == "bootout":
            return _Done(code=1, err="not loaded")
        return _Done()

    monkeypatch.setattr("arelis.jobs.launchd.hidden_run", fake_run)
    from arelis.jobs.schedule import register, unregister

    register(_job())
    calls.clear()
    assert unregister("news") is True
    assert calls[0][1] == "bootout"
    assert calls[1][1] == "unload"
    assert calls[1][2] == "-w"
    assert not (folder / "app.arelis.job.news.plist").exists()
    assert unregister("news") is False


def test_mac_login_start_uses_the_current_interpreter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    folder = _agents(monkeypatch, tmp_path)
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> _Done:
        calls.append(list(args))
        return _Done()

    monkeypatch.setattr("arelis.jobs.launchd.hidden_run", fake_run)
    from arelis.login_start import install_login_start, remove_login_start

    text = install_login_start()
    assert "log in" in text.lower()
    plist_path = folder / "app.arelis.core.plist"
    with plist_path.open("rb") as handle:
        loaded = plistlib.load(handle)
    assert loaded["Label"] == "app.arelis.core"
    assert loaded["RunAtLoad"] is True
    assert loaded["ProgramArguments"] == [sys.executable, "-m", "arelis", "--core"]
    assert calls[0][1] == "bootstrap"
    gone = remove_login_start()
    assert "no longer" in gone.lower()
    assert not plist_path.exists()


def test_windows_login_flag_does_not_schedule(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    folder = _agents(monkeypatch, tmp_path)
    from arelis.main import main

    assert main(["--install-login-start"]) == 0
    assert list(folder.glob("*.plist")) == []


def test_installed_mac_uses_library_folders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("ARELIS_DATA_DIR", raising=False)
    monkeypatch.setattr("arelis.paths.is_source_checkout", lambda: False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    from arelis.browser.launch import browsers_path
    from arelis.paths import cache_dir, models_dir, temp_dir, user_data_dir

    home = tmp_path / "home"
    assert user_data_dir() == home / "Library" / "Application Support" / "Arelis"
    assert cache_dir() == home / "Library" / "Caches" / "Arelis"
    assert models_dir() == home / "Library" / "Caches" / "Arelis" / "models"
    assert temp_dir() == home / "Library" / "Caches" / "Arelis" / "temp"
    assert browsers_path() == home / "Library" / "Caches" / "Arelis" / "browsers"


def test_windows_cache_stays_under_local_appdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("ARELIS_DATA_DIR", raising=False)
    monkeypatch.setattr("arelis.paths.is_source_checkout", lambda: False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    from arelis.paths import cache_dir, models_dir, user_data_dir

    assert user_data_dir() == tmp_path / "Local" / "Arelis"
    assert cache_dir() == tmp_path / "Local" / "Arelis" / "cache"
    assert models_dir() == tmp_path / "Local" / "Arelis" / "models"


def test_mac_uninstall_clears_cache_and_only_our_agents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("ARELIS_DATA_DIR", raising=False)
    home = tmp_path / "home"
    support = home / "Library" / "Application Support" / "Arelis"
    cache = home / "Library" / "Caches" / "Arelis"
    support.mkdir(parents=True)
    cache.mkdir(parents=True)
    (support / "keep.txt").write_text("x", encoding="utf-8")
    (cache / "weights.bin").write_text("x", encoding="utf-8")
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    ours = agents / "app.arelis.job.news.plist"
    core = agents / "app.arelis.core.plist"
    other = agents / "com.example.keep.plist"
    for path, label in (
        (ours, "app.arelis.job.news"),
        (core, "app.arelis.core"),
        (other, "com.example.keep"),
    ):
        with path.open("wb") as handle:
            plistlib.dump({"Label": label}, handle)

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("ARELIS_LAUNCH_AGENTS", str(agents))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setattr("arelis.paths.is_source_checkout", lambda: False)
    monkeypatch.setattr("arelis.uninstall.is_source_checkout", lambda: False)
    monkeypatch.setattr("arelis.jobs.launchd.hidden_run", lambda *_a, **_k: _Done())
    from arelis.uninstall import purge_user_state, residue_dirs

    leftover = {path.resolve() for path in residue_dirs()}
    assert support.resolve() in leftover
    assert cache.resolve() in leftover
    gone = purge_user_state()
    assert not support.exists()
    assert not cache.exists()
    assert not ours.exists()
    assert not core.exists()
    assert other.is_file()
    assert any("news" in item for item in gone)


def test_mac_ollama_message_names_the_website_and_brew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    from arelis.setup.engine import ollama_install_help

    text = ollama_install_help() or ""
    lowered = text.lower()
    assert "ollama website" in lowered
    assert "brew install ollama" in lowered
    assert "try again" in lowered


def test_chrome_checks_the_home_applications_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ARELIS_CHROME", raising=False)
    home = tmp_path / "home"
    expected = (
        home
        / "Applications"
        / "Google Chrome.app"
        / "Contents"
        / "MacOS"
        / "Google Chrome"
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("shutil.which", lambda _name: None)

    def is_file(self: Path) -> bool:
        return str(self).replace("\\", "/") == expected.as_posix()

    monkeypatch.setattr(Path, "is_file", is_file)
    from arelis.browser.launch import chrome_executable

    found = chrome_executable()
    assert found is not None
    assert found.replace("\\", "/") == expected.as_posix()


def test_tesseract_checks_explicit_paths_when_path_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("shutil.which", lambda _name: None)

    def is_file(self: Path) -> bool:
        return str(self).replace("\\", "/") == "/usr/local/bin/tesseract"

    monkeypatch.setattr(Path, "is_file", is_file)
    from arelis.tools.ocr import _tesseract_exe

    found = _tesseract_exe()
    assert found is not None
    assert found.replace("\\", "/") == "/usr/local/bin/tesseract"
