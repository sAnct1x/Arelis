"""Quitting must stop the Chrome Arelis started, not leave it behind."""

from __future__ import annotations

import subprocess
from typing import Any

from arelis.ui.launch import _flush_pending_writes


class _AliveProc:
    pid = 4242

    def __init__(self) -> None:
        self.signals: list[str] = []
        self._code: int | None = None

    def poll(self) -> int | None:
        return self._code

    def terminate(self) -> None:
        self.signals.append("terminate")
        self._code = 0

    def kill(self) -> None:
        self.signals.append("kill")
        self._code = 1

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self._code is None:
            raise subprocess.TimeoutExpired(cmd="chrome", timeout=0)
        return self._code


def test_quit_stops_the_chrome_arelis_started(monkeypatch: Any) -> None:
    """Tray Quit must stop every Chrome Arelis started.

    Browser tool, scrape that then opens the page, and Google sign-in in
    her window all go through launch_chromium_cdp. The owner stops that
    process on the same quit deadline as the memory flush. Calendar OAuth
    opens the system browser and is not ours. Never taskkill by image name.
    """
    from arelis.browser import launch as launch_mod

    signaled: list[tuple[int, bool]] = []
    image_kills: list[list[str]] = []

    def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        argv = [str(part) for part in args]
        image_kills.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(launch_mod, "_pids_using_arelis_profile", lambda: [9001])
    monkeypatch.setattr(
        launch_mod,
        "_signal_owned_pid",
        lambda pid, force=False: signaled.append((int(pid), bool(force))),
    )
    monkeypatch.setattr(launch_mod, "_pid_is_alive", lambda pid: False)
    monkeypatch.setattr(launch_mod.subprocess, "run", _run)

    failures: list[str] = []
    for label in ("browser", "scrape_open", "google_in_her_window"):
        signaled.clear()
        image_kills.clear()
        proc = _AliveProc()
        launch_mod._last_arelis_proc = proc  # type: ignore[assignment]
        _flush_pending_writes(
            store=None,
            indexer=None,
            backup_thread=None,
            timeout_s=1.0,
        )
        if "terminate" not in proc.signals:
            failures.append(f"{label}: owned chrome was not stopped")
        if launch_mod._last_arelis_proc is not None:
            failures.append(f"{label}: owner still held a process after quit")
        extra = {(9001, False), (9001, True)}
        if not extra.intersection(signaled):
            failures.append(f"{label}: leftover profile chrome was not signaled")
        for argv in image_kills:
            joined = " ".join(argv).lower()
            if "/im" in joined and "chrome" in joined:
                failures.append(f"{label}: killed chrome by image name: {argv}")
    assert not failures, "\n".join(failures)
