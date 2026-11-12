"""GPU lease: pause llama-server for image work, then bring chat back.

Root cause: LlamaCppProvider.unload is a no-op, and nothing stopped
llama-server before an image job, so the 35B and the image model fought
for the same 12 GB card. This lease stops the process Arelis already
knows how to start, then starts it again with the same launch arguments.
"""

from __future__ import annotations

import atexit
import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Idle delay used only when a caller still schedules one. A successful
# picture restores chat right away so the next message is not left waiting.
_IDLE_S = 90.0

CHAT_PAUSED = (
    "Chat is paused while a picture is being made. "
    "This usually takes a couple of minutes, then about a minute to bring chat back."
)
CHAT_RESUMING = "Bringing chat back. This usually takes about a minute."
CHAT_RESTORE_FAILED = (
    "Chat could not come back after the picture. "
    "Try closing Arelis and opening it again."
)

StatusFn = Callable[[str], None]

_lock = threading.Lock()
_held = False
_generating = False
_stopped_server = False
# True while release() restarts llama-server and reloads the slot. _held is
# already False then, so this is what tells the UI chat is not back yet.
_restoring = False
_config: dict[str, Any] | None = None
_idle_timer: threading.Timer | None = None
_atexit_registered = False
_status: StatusFn | None = None
_marker_path: Path | None = None
# Injected in tests.
_stop_fn: Callable[[str], bool] | None = None
_ensure_fn: Callable[[str, list[str] | None], None] | None = None
_nowait_fn: Callable[[str, list[str] | None], None] | None = None
_args_fn: Callable[[dict[str, Any] | None], list[str] | None] | None = None


def set_status(fn: StatusFn | None) -> None:
    """Optional ``fn(line)`` so the UI can show the pause in plain words."""
    global _status
    _status = fn


def is_held() -> bool:
    with _lock:
        return _held


def is_generating() -> bool:
    with _lock:
        return _generating


def chat_blocked() -> bool:
    """True from acquire until llama-server is back and the slot reloaded."""
    with _lock:
        return _held or _restoring


def _base_url(config: dict[str, Any] | None) -> str:
    lc = (config or {}).get("llamacpp") if isinstance(config, dict) else None
    if not isinstance(lc, dict):
        return "http://127.0.0.1:8080"
    return str(lc.get("base_url") or "http://127.0.0.1:8080").rstrip("/")


def _launch_args(config: dict[str, Any] | None) -> list[str] | None:
    fn = _args_fn
    if fn is not None:
        return fn(config)
    from arelis.llm.llama_launch import restore_args

    return restore_args(config)


def _stop(base_url: str) -> bool:
    fn = _stop_fn
    if fn is not None:
        return bool(fn(base_url))
    from arelis.llm.llama_launch import stop_server

    return bool(stop_server(base_url))


def _ensure(
    base_url: str,
    args: list[str] | None,
    config: dict[str, Any] | None = None,
) -> None:
    fn = _ensure_fn
    if fn is not None:
        fn(base_url, args)
        return
    from arelis.llm.llama_launch import ensure_server

    ensure_server(base_url, args, config=config)


def _nowait(base_url: str, args: list[str] | None) -> None:
    fn = _nowait_fn
    if fn is not None:
        fn(base_url, args)
        return
    from arelis.llm.llama_launch import start_server_nowait

    start_server_nowait(base_url, args)


def _tell(line: str) -> None:
    cb = _status
    if cb is None:
        return
    try:
        cb(line)
    except Exception:
        # Status text is best effort; a UI callback must not break the lease.
        log.debug("Image lease status callback failed", exc_info=True)


def _register_atexit() -> None:
    global _atexit_registered
    if _atexit_registered:
        return
    atexit.register(release_on_quit)
    _atexit_registered = True


def _cancel_idle() -> None:
    global _idle_timer
    timer = _idle_timer
    _idle_timer = None
    if timer is not None:
        timer.cancel()


def acquire(config: dict[str, Any] | None = None) -> None:
    """Stop llama-server and mark chat as paused. Safe to call again."""
    global _held, _generating, _stopped_server, _config
    _register_atexit()
    with _lock:
        _cancel_idle()
        _generating = True
        if config is not None:
            _config = config
        already = _held
        _held = True
        cfg = _config
        url = _base_url(cfg)
    if already:
        _tell(CHAT_PAUSED)
        return
    try:
        from arelis.llm.llama_launch import save_slot

        save_slot(url)
    except Exception:
        # A failed save only means the next turn may be cold. Never block the picture.
        log.info("Could not save the chat slot before a picture", exc_info=True)
    try:
        stopped = _stop(url)
    except Exception:
        with _lock:
            _generating = False
            _held = False
        log.warning("Could not stop llama-server for image work", exc_info=True)
        _clear_slot_file()
        raise
    with _lock:
        _stopped_server = bool(stopped) or _stopped_server
        held_stop = _stopped_server
        cfg_now = _config
        url_now = url
    if held_stop:
        _write_marker(cfg_now, url_now)
    _tell(CHAT_PAUSED)
    log.info("Image GPU lease acquired (stopped_server=%s)", stopped)


def mark_generation_done(*, success: bool, idle_s: float | None = None) -> None:
    """End the active job. Restore chat now. success and idle_s are kept for callers.

    The slot file exists only if the save before the picture worked, and it
    holds the chat as it was then, so a Stop or crash reloads it too.
    """
    del success, idle_s
    global _generating
    with _lock:
        _generating = False
        held = _held
    if not held:
        return
    release(restore_slot=True)


def schedule_release(delay_s: float | None = None) -> None:
    """Bring chat back after a short idle, so a follow-up picture can reuse the card."""
    global _idle_timer
    try:
        wait = _IDLE_S if delay_s is None else float(delay_s)
    except (TypeError, ValueError):
        wait = _IDLE_S
    wait = max(0.0, wait)
    with _lock:
        _cancel_idle()
        if not _held:
            return
        if wait <= 0:
            should_run = True
        else:
            timer = threading.Timer(wait, _release_safe)
            timer.daemon = True
            _idle_timer = timer
            should_run = False
            timer.start()
    if should_run:
        release()


def _release_safe() -> None:
    try:
        release()
    except Exception:
        log.warning("Image GPU lease could not restore llama-server", exc_info=True)


def release(*, nowait: bool = False, restore_slot: bool = False) -> None:
    """Start llama-server again if this lease stopped it. Always clears the hold."""
    global _held, _generating, _stopped_server, _config, _restoring
    with _lock:
        _cancel_idle()
        if not _held:
            _generating = False
            return
        cfg = _config
        should_start = _stopped_server
        _held = False
        _generating = False
        _stopped_server = False
        _restoring = should_start
    try:
        _start_chat(cfg, nowait=nowait, restore_slot=restore_slot, should_start=should_start)
    finally:
        with _lock:
            _restoring = False


def _start_chat(
    cfg: dict[str, Any] | None,
    *,
    nowait: bool,
    restore_slot: bool,
    should_start: bool,
) -> None:
    url = _base_url(cfg)
    args = _launch_args(cfg)
    if not should_start:
        return
    if not args:
        _tell(CHAT_RESTORE_FAILED)
        log.warning("Image GPU lease has no llama-server command to restore")
        _clear_slot_file()
        return
    _tell(CHAT_RESUMING)
    try:
        if nowait:
            _nowait(url, args)
            if _server_up(url):
                _clear_marker()
            _clear_slot_file()
        else:
            _ensure(url, args, cfg)
            _clear_marker()
            if restore_slot:
                _restore_slot(url)
            else:
                _clear_slot_file()
        log.info("Image GPU lease released (nowait=%s)", nowait)
    except Exception:
        log.warning("Image GPU lease failed to restore llama-server", exc_info=True)
        # Last try: spawn without waiting so chat is not left dead.
        retry = args
        if _args_fn is None:
            try:
                from arelis.llm.llama_launch import launch_args_for

                built = launch_args_for(cfg)
                if built and list(built) != list(args):
                    retry = built
            except Exception:
                log.warning(
                    "Could not build fallback llama-server args",
                    exc_info=True,
                )
        try:
            _nowait(url, retry)
            _clear_slot_file()
        except Exception:
            log.warning(
                "Image GPU lease could not spawn llama-server after a failed restore",
                exc_info=True,
            )
            _tell(CHAT_RESTORE_FAILED)
            _clear_slot_file()
            raise


def yield_to_chat() -> None:
    """If a picture session is only idling, restore chat now.

    If a picture is still being made, wait until that job ends (it will
    restore chat on failure, or we restore it here after a successful
    batch) and then bring llama-server back so a queued turn can run.
    """
    while True:
        with _lock:
            if not _held:
                return
            generating = _generating
        if not generating:
            release()
            return
        # A picture is in flight. Wait briefly and look again. The image
        # tool will flip _generating off when it finishes or is cancelled.
        event = threading.Event()
        event.wait(0.25)


def release_on_quit() -> None:
    """Stop a live sd-cli process, then spawn llama-server without waiting."""
    try:
        from arelis.tools.sdcpp import stop_cli

        stop_cli()
    except Exception:
        log.warning("Could not stop sd-cli on quit", exc_info=True)
    try:
        release(nowait=True)
    except Exception:
        log.warning("Image GPU lease release on quit failed", exc_info=True)


def reset_for_tests(
    *,
    stop: Callable[[str], bool] | None = None,
    ensure: Callable[[str, list[str] | None], None] | None = None,
    nowait: Callable[[str, list[str] | None], None] | None = None,
    args: Callable[[dict[str, Any] | None], list[str] | None] | None = None,
) -> None:
    """Clear lease state and optionally install fakes. Tests only."""
    global _held, _generating, _stopped_server, _config, _restoring
    global _stop_fn, _ensure_fn, _nowait_fn, _args_fn, _status
    global _marker_path
    with _lock:
        _cancel_idle()
        _held = False
        _restoring = False
        _generating = False
        _stopped_server = False
        _config = None
        _stop_fn = stop
        _ensure_fn = ensure
        _nowait_fn = nowait
        _args_fn = args
        _status = None
        _marker_path = None


def set_marker_path(path: Path | None) -> None:
    """Tests only: write the lease marker to a temp file."""
    global _marker_path
    _marker_path = path


def marker_path() -> Path:
    if _marker_path is not None:
        return _marker_path
    from arelis.paths import state_dir

    return state_dir() / "gpu-lease.json"


def _restore_slot(base_url: str) -> None:
    """Reload the saved chat slot. Failures stay silent; the next turn may be cold."""
    try:
        from arelis.llm.llama_launch import restore_slot

        restore_slot(base_url)
    except Exception:
        # A failed reload only means the next turn may be cold. No user error.
        log.info("Could not restore the chat slot after a picture", exc_info=True)
        _clear_slot_file()


def _clear_slot_file() -> None:
    try:
        from arelis.llm.llama_launch import clear_slot_file

        clear_slot_file()
    except Exception:
        # Cleanup is best effort; a leftover file is overwritten next time.
        log.info("Could not clear the saved chat slot file", exc_info=True)


def _server_up(base_url: str) -> bool:
    try:
        from arelis.llm.llama_launch import _health_ok

        return bool(_health_ok(base_url))
    except Exception:
        # A down or unreadable port is treated as not up, so restore can run.
        return False


def _write_marker(config: dict[str, Any] | None, base_url: str) -> None:
    import os

    # Tests must opt in with set_marker_path so a suite run cannot rewrite
    # the user's leftover-lease marker.
    if _marker_path is None and os.environ.get("PYTEST_CURRENT_TEST"):
        return
    args = _launch_args(config)
    if not args:
        return
    cwd = None
    try:
        from arelis.llm.llama_launch import restore_cwd

        cwd = restore_cwd()
    except Exception:
        # cwd is optional; the saved command can still start from a default folder.
        cwd = None
    payload = {"args": list(args), "cwd": cwd, "base_url": base_url}
    path = marker_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.warning("Could not write the GPU lease marker", exc_info=True)


def _clear_marker() -> None:
    path = marker_path()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.warning("Could not clear the GPU lease marker", exc_info=True)


def _load_marker() -> dict[str, Any] | None:
    path = marker_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        log.warning("Could not read the GPU lease marker", exc_info=True)
        return None
    return data if isinstance(data, dict) else None


def recover_paused_server(config: dict[str, Any] | None = None) -> bool:
    """If a picture left llama-server stopped, start it again on launch.

    A hard kill mid-picture skips quit restore, so the saved command is
    written to a marker when the lease stops the server, and this replays it
    when the next Arelis starts and the port is still down.
    """
    data = _load_marker()
    if not data:
        return False
    url = str(data.get("base_url") or _base_url(config)).rstrip("/")
    raw_args = data.get("args")
    args = [str(item) for item in raw_args] if isinstance(raw_args, list) and raw_args else None
    cwd = str(data.get("cwd") or "") or None
    if _server_up(url):
        _clear_marker()
        return False
    if not args:
        args = _launch_args(config)
    if not args:
        log.warning("GPU lease marker has no llama-server command to restore")
        _tell(CHAT_RESTORE_FAILED)
        return False
    try:
        from arelis.llm.llama_launch import remember_launch

        remember_launch(args, cwd=cwd)
    except Exception:
        log.warning("Could not apply the saved llama-server command", exc_info=True)
    try:
        _ensure(url, args, config)
        _clear_marker()
        log.info("Restored llama-server from a leftover picture lease")
        return True
    except Exception:
        log.warning("Could not restore llama-server from the picture lease marker", exc_info=True)
        _tell(CHAT_RESTORE_FAILED)
        return False
