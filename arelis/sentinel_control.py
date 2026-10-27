"""Arelis owns the Sentinel child. start and stop only. No model-facing ops."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
_CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)

_lock = threading.Lock()
_process: subprocess.Popen[bytes] | None = None
_token: str | None = None
_stopped = False

_TOKEN_WAIT_S = 8.0
_TOKEN_POLL_S = 0.05
_STOP_WAIT_S = 1.5


def _sentinel_root() -> Path | None:
    checkout = Path(__file__).resolve().parents[1] / "sentinel"
    if (checkout / "sentinel" / "__main__.py").is_file():
        return checkout
    return None


def _runtime_root() -> Path:
    from arelis.paths import user_data_dir

    root = user_data_dir() / "sentinel"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _child_env(data_root: Path, sentinel_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    extra = str(sentinel_root)
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = extra if not current else extra + os.pathsep + current
    env["SENTINEL_RUNTIME_ROOT"] = str(data_root)
    return env


def _spawn(
    argv: list[str],
    *,
    env: dict[str, str],
    cwd: Path,
) -> subprocess.Popen[bytes]:
    kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_NO_WINDOW | _CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["process_group"] = 0
    return subprocess.Popen(argv, **kwargs)


def _token_path(data_root: Path) -> Path:
    return data_root / "data" / "session_token"


def _read_token(path: Path, *, timeout_s: float) -> str | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _stopped:
            return None
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError:
            raw = ""
        if len(raw) >= 32:
            return raw
        time.sleep(_TOKEN_POLL_S)
    return None


def _kill(proc: subprocess.Popen[bytes], *, timeout_s: float) -> None:
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            try:
                os.killpg(int(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.terminate()
    except Exception:
        log.warning("Sentinel child could not be signalled")
        return
    try:
        proc.wait(timeout=max(0.1, timeout_s))
    except subprocess.TimeoutExpired:
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                try:
                    os.killpg(int(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    proc.kill()
            proc.wait(timeout=max(0.1, timeout_s))
        except Exception:
            log.warning("Sentinel child did not exit")


def start() -> None:
    """Launch headless Sentinel as a child. Fail soft. Leave a tripped EMP flag."""
    global _process, _token, _stopped
    with _lock:
        _stopped = False
        if _process is not None and _process.poll() is None:
            return
        _token = None
        sentinel_root = _sentinel_root()
        if sentinel_root is None:
            log.warning("Sentinel did not start")
            return
        data_root = _runtime_root()
        argv = [sys.executable, "-m", "sentinel", "--headless"]
        env = _child_env(data_root, sentinel_root)
        try:
            proc = _spawn(argv, env=env, cwd=sentinel_root)
        except Exception:
            log.warning("Sentinel did not start")
            return
        if _stopped:
            _kill(proc, timeout_s=_STOP_WAIT_S)
            return
        _process = proc
    token = _read_token(_token_path(data_root), timeout_s=_TOKEN_WAIT_S)
    with _lock:
        if _stopped or _process is not proc:
            if proc.poll() is None:
                _kill(proc, timeout_s=_STOP_WAIT_S)
            return
        if not token:
            log.warning("Sentinel did not start")
            _kill(proc, timeout_s=_STOP_WAIT_S)
            if _process is proc:
                _process = None
            _token = None
            return
        _token = token
        log.info("Sentinel child is up")


def stop(*, timeout_s: float = _STOP_WAIT_S) -> None:
    """Stop the child Arelis started. Safe to call more than once."""
    global _process, _token, _stopped
    with _lock:
        _stopped = True
        proc = _process
        _process = None
        _token = None
    if proc is None:
        return
    _kill(proc, timeout_s=timeout_s)
