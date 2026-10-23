"""Quitting must stop the Chrome Arelis started, not leave it behind."""

from __future__ import annotations

import subprocess
import time
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
    real_signal = launch_mod._signal_owned_pid

    def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        argv = [str(part) for part in args]
        image_kills.append(argv)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(launch_mod, "_pids_using_arelis_profile", lambda **_k: [9001])
    monkeypatch.setattr(
        launch_mod,
        "_signal_owned_pid",
        lambda pid, force=False, timeout_s=0.0: signaled.append(
            (int(pid), bool(force))
        ),
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

    scan_timeouts: list[float | None] = []

    def _slow_scan(*, timeout_s: float | None = None) -> list[int]:
        scan_timeouts.append(timeout_s)
        delay = 2.0 if timeout_s is None else min(2.0, max(0.0, float(timeout_s)))
        time.sleep(delay)
        return [9001]

    monkeypatch.setattr(launch_mod, "_pids_using_arelis_profile", _slow_scan)
    launch_mod._last_arelis_proc = _AliveProc()  # type: ignore[assignment]
    started = time.monotonic()
    launch_mod.stop_owned_browser(timeout_s=0.5)
    elapsed = time.monotonic() - started
    if not scan_timeouts or scan_timeouts[-1] is None or float(scan_timeouts[-1]) > 0.51:
        failures.append(f"scan: leftover pid scan was not bound: {scan_timeouts!r}")
    if elapsed >= 1.5:
        failures.append(f"scan: stop_owned_browser(0.5) took {elapsed:.2f}s")

    scan_timeouts.clear()
    launch_mod._last_arelis_proc = _AliveProc()  # type: ignore[assignment]
    launch_mod.stop_owned_browser(timeout_s=0.0)
    if scan_timeouts:
        failures.append(f"scan: ran with no deadline left: {scan_timeouts!r}")

    sub_timeouts: list[float] = []

    def _check_output(args: list[str], **kwargs: Any) -> str:
        del args
        sub_timeouts.append(float(kwargs.get("timeout") or 0.0))
        raise subprocess.TimeoutExpired(cmd="scan", timeout=0)

    monkeypatch.setattr(launch_mod.sys, "platform", "win32")
    monkeypatch.setattr(launch_mod.subprocess, "check_output", _check_output)
    launch_mod._chrome_cmdlines(timeout_s=0.4)
    if len(sub_timeouts) < 2:
        failures.append(f"scan: powershell or wmic was not bound: {sub_timeouts!r}")
    else:
        if sub_timeouts[0] > 0.41:
            failures.append(f"scan: powershell timeout {sub_timeouts[0]} over deadline")
        if sub_timeouts[1] > 0.41:
            failures.append(f"scan: wmic timeout {sub_timeouts[1]} over deadline")
    sub_timeouts.clear()
    launch_mod._chrome_cmdlines(timeout_s=0.0)
    if sub_timeouts:
        failures.append(f"scan: subprocess ran with no budget: {sub_timeouts!r}")

    monkeypatch.setattr(launch_mod, "_signal_owned_pid", real_signal)
    monkeypatch.setattr(launch_mod, "_pids_using_arelis_profile", lambda **_k: [])
    image_kills.clear()
    launch_mod._last_arelis_proc = _AliveProc()  # type: ignore[assignment]
    launch_mod.stop_owned_browser(timeout_s=1.0)
    tree = [
        a
        for a in image_kills
        if "taskkill" in " ".join(a).lower()
        and "/pid" in " ".join(a).lower()
        and "4242" in a
        and "/t" in " ".join(a).lower()
        and "/f" in " ".join(a).lower()
    ]
    if not tree:
        failures.append(f"windows: owned pid was not tree-killed: {image_kills!r}")
    for argv in image_kills:
        joined = " ".join(argv).lower()
        if "/im" in joined and "chrome" in joined:
            failures.append(f"windows: killed chrome by image name: {argv}")

    slept: list[float] = []
    monkeypatch.setattr(launch_mod.time, "sleep", lambda s: slept.append(float(s)))
    launch_mod._last_arelis_proc = _AliveProc()  # type: ignore[assignment]
    launch_mod.terminate_arelis_browser()
    if not any(abs(s - 0.6) < 1e-9 for s in slept):
        failures.append(f"relaunch: missing 0.6s settle: {slept!r}")

    assert not failures, "\n".join(failures)
