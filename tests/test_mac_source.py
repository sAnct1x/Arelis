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


def test_linux_scheduling_stays_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    from arelis.jobs.schedule import ScheduleError, register, supported

    assert supported() is False
    with pytest.raises(ScheduleError):
        register(_job())


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


