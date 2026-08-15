"""Core-side helpers to foreground (or spawn) the glass UI via IPC."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from typing import Any

from arelis.presence.ipc_server import IpcServer
from arelis.presence.lock import lock_held_by_other, ui_lock_path

log = logging.getLogger(__name__)

# Avoid a burst of TOOL_CONFIRM events spawning N UIs while the first starts.
_LAST_SPAWN_MONO: float = 0.0
_SPAWN_COOLDOWN_S = 20.0


def ui_process_appears_running(config: dict[str, Any] | None = None) -> bool:
    """True when the UI single-instance lock is held by another process."""
    return lock_held_by_other(ui_lock_path(config))


def spawn_ui_subprocess() -> int | None:
    """Launch `python -m arelis` (UI) so it can attach to a running core."""
    global _LAST_SPAWN_MONO
    now = time.monotonic()
    if now - _LAST_SPAWN_MONO < _SPAWN_COOLDOWN_S:
        log.info(
            "Skipping UI spawn — cooldown (%.0fs remaining).",
            _SPAWN_COOLDOWN_S - (now - _LAST_SPAWN_MONO),
        )
        return None
    if ui_process_appears_running():
        log.info("Skipping UI spawn — arelis-ui.lock already held.")
        return None
    try:
        env = os.environ.copy()
        env["ARELIS_ATTACH_CORE"] = "1"
        kwargs: dict[str, Any] = {
            "args": [sys.executable, "-m", "arelis"],
            "close_fds": True,
            "env": env,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
        proc = subprocess.Popen(**kwargs)
        _LAST_SPAWN_MONO = now
        log.info("Spawned Arelis UI subprocess pid=%s", proc.pid)
        return int(proc.pid)
    except Exception as exc:
        log.warning("Could not spawn Arelis UI: %s", exc)
        return None


async def ensure_ui_open(
    server: IpcServer | None,
    *,
    spawn_if_detached: bool = True,
    config: dict[str, Any] | None = None,
    **payload: Any,
) -> dict[str, Any]:
    """Ask attached UIs to foreground; optionally spawn one if none attached."""
    if server is None:
        return {"attached": 0, "spawned": False, "pid": None}
    attached = await server.request_open_ui(**payload)
    if attached > 0:
        return {"attached": attached, "spawned": False, "pid": None}
    # Lock held → UI is alive (maybe tray-hidden) but not on IPC yet; do not
    # spawn a second glass. Caller already broadcast open_ui to zero clients.
    if ui_process_appears_running(config):
        log.info("UI lock held but no IPC client — not spawning another glass.")
        return {"attached": 0, "spawned": False, "pid": None, "ui_lock": True}
    pid: int | None = None
    spawned = False
    if spawn_if_detached:
        pid = spawn_ui_subprocess()
        spawned = pid is not None
    return {"attached": 0, "spawned": spawned, "pid": pid}
