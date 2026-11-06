"""Arelis owns the Sentinel child. start, stop, and the Overseer URL. No model-facing ops."""

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
_endpoint: tuple[str, int] | None = None
_endpoint_file: Path | None = None
_stopped = False

_TOKEN_WAIT_S = 8.0
_TOKEN_POLL_S = 0.05
_STOP_WAIT_S = 1.5
_LOOPBACK = frozenset({"127.0.0.1", "::1"})


def _sentinel_root() -> Path | None:
    checkout = Path(__file__).resolve().parents[1] / "sentinel"
    if (checkout / "sentinel" / "__main__.py").is_file():
        return checkout
    # Installed copy: the wheel ships `sentinel` beside `arelis` in site-packages.
    installed = Path(__file__).resolve().parents[1]
    if (installed / "sentinel" / "__main__.py").is_file():
        return installed
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


def _endpoint_path(data_root: Path) -> Path:
    return data_root / "data" / "bridge_endpoint.json"


def _read_endpoint(path: Path) -> tuple[str, int] | None:
    """Host and port the child bound, from the file it writes after bind."""
    import json

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        host = str(raw["host"])
        port = int(raw["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not 0 < port < 65536:
        return None
    return host, port


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


_THEME_CHOICES = frozenset({"sodium", "filament", "night", "matrix"})


def headless_argv(executable: str | None = None, theme: str | None = None) -> list[str]:
    """Build the child argv. Passes Arelis's active theme without writing prefs."""
    argv = [executable or sys.executable, "-m", "sentinel", "--headless"]
    chosen = theme
    if chosen is None:
        try:
            from arelis.ui.theme_tokens import active_theme
            chosen = active_theme()
        except Exception:
            chosen = None
    if chosen in _THEME_CHOICES:
        argv.extend(["--theme", str(chosen)])
    return argv


def start() -> None:
    """Launch headless Sentinel as a child. Fail soft. Leave a tripped EMP flag."""
    global _process, _token, _endpoint, _endpoint_file, _stopped
    with _lock:
        _stopped = False
        if _process is not None and _process.poll() is None:
            return
        _token = None
        _endpoint = None
        _endpoint_file = None
        sentinel_root = _sentinel_root()
        if sentinel_root is None:
            log.warning("Sentinel did not start")
            return
        data_root = _runtime_root()
        # A file left by an earlier run could point at a port someone else now holds.
        try:
            _endpoint_path(data_root).unlink(missing_ok=True)
        except OSError:
            log.warning("Sentinel endpoint file could not be cleared")
        argv = headless_argv()
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
        _endpoint_file = _endpoint_path(data_root)
        log.info("Sentinel child is up")


def stop(*, timeout_s: float = _STOP_WAIT_S) -> None:
    """Stop the child Arelis started. Safe to call more than once."""
    global _process, _token, _endpoint, _endpoint_file, _stopped
    with _lock:
        _stopped = True
        proc = _process
        _process = None
        _token = None
        _endpoint = None
        _endpoint_file = None
    if proc is None:
        return
    _kill(proc, timeout_s=timeout_s)


def overseer_url() -> str | None:
    """Overseer page on loopback, token in the fragment only. None when down.

    Host and port are the ones the child reported after binding, never a
    guessed default: a guess could hand the token to whatever else holds it.

    The fragment never reaches the server or its access log, and
    telemetry_ws.js reads ``#token=`` then strips it from history. Never log
    the returned value.
    """
    target = bridge_target()
    if target is None:
        return None
    host, port, token = target
    netloc = f"[{host}]" if ":" in host else host
    return f"http://{netloc}:{int(port)}/overseer#token={token}"


def bridge_target() -> tuple[str, int, str] | None:
    """(host, port, token) of the live child's bridge, loopback only, else None.

    One gate for every caller that talks to the bridge (the Overseer URL and
    sentinel_client). Never log the token.
    """
    global _endpoint
    with _lock:
        proc = _process
        token = _token
        if _endpoint is None and _endpoint_file is not None and token:
            _endpoint = _read_endpoint(_endpoint_file)
        endpoint = _endpoint
    if proc is None or not token or endpoint is None:
        return None
    host, port = endpoint
    if host not in _LOOPBACK:
        return None
    if proc.poll() is not None:
        return None
    return host, int(port), token
