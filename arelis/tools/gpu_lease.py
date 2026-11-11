"""GPU lease: pause llama-server for image work, then bring chat back.

Root cause: LlamaCppProvider.unload is a no-op, and nothing stopped
llama-server before an image job, so the 35B and the image model fought
for the same 12 GB card. This lease stops the process Arelis already
knows how to start, then starts it again with the same launch arguments.
"""

from __future__ import annotations

import atexit
import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

# Keep the card for a follow-up picture, then bring chat back.
_IDLE_S = 90.0

CHAT_PAUSED = (
    "Chat is paused while a picture is being made. "
    "This usually takes a couple of minutes, then about a minute to bring chat back."
)
CHAT_RESUMING = "Bringing chat back. This usually takes about a minute."

StatusFn = Callable[[str], None]

_lock = threading.Lock()
_held = False
_generating = False
_stopped_server = False
_config: dict[str, Any] | None = None
_idle_timer: threading.Timer | None = None
_atexit_registered = False
_status: StatusFn | None = None
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


def _base_url(config: dict[str, Any] | None) -> str:
    lc = (config or {}).get("llamacpp") if isinstance(config, dict) else None
    if not isinstance(lc, dict):
        return "http://127.0.0.1:8080"
    return str(lc.get("base_url") or "http://127.0.0.1:8080").rstrip("/")


def _launch_args(config: dict[str, Any] | None) -> list[str] | None:
    fn = _args_fn
    if fn is not None:
        return fn(config)
    from arelis.llm.llama_launch import launch_args_for

    return launch_args_for(config)


def _stop(base_url: str) -> bool:
    fn = _stop_fn
    if fn is not None:
        return bool(fn(base_url))
    from arelis.llm.llama_launch import stop_server

    return bool(stop_server(base_url))


def _ensure(base_url: str, args: list[str] | None) -> None:
    fn = _ensure_fn
    if fn is not None:
        fn(base_url, args)
        return
    from arelis.llm.llama_launch import ensure_server

    ensure_server(base_url, args)


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
        stopped = _stop(url)
    except Exception:
        with _lock:
            _generating = False
            _held = False
        log.warning("Could not stop llama-server for image work", exc_info=True)
        raise
    with _lock:
        _stopped_server = bool(stopped) or _stopped_server
    _tell(CHAT_PAUSED)
    log.info("Image GPU lease acquired (stopped_server=%s)", stopped)


def mark_generation_done(*, success: bool) -> None:
    """End the active job. Restore chat now on failure, or after a short idle."""
    global _generating
    with _lock:
        _generating = False
        held = _held
    if not held:
        return
    if success:
        schedule_release()
    else:
        release()


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


def release(*, nowait: bool = False) -> None:
    """Start llama-server again if this lease stopped it. Always clears the hold."""
    global _held, _generating, _stopped_server, _config
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
    url = _base_url(cfg)
    args = _launch_args(cfg)
    if not should_start:
        return
    _tell(CHAT_RESUMING)
    try:
        if nowait:
            _nowait(url, args)
        else:
            _ensure(url, args)
        log.info("Image GPU lease released (nowait=%s)", nowait)
    except Exception:
        log.warning("Image GPU lease failed to restore llama-server", exc_info=True)
        # Last try: spawn without waiting so chat is not left dead.
        try:
            _nowait(url, args)
        except Exception:
            log.warning(
                "Image GPU lease could not spawn llama-server after a failed restore",
                exc_info=True,
            )
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
    """Stop any image process hold and spawn llama-server without waiting."""
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
    global _held, _generating, _stopped_server, _config
    global _stop_fn, _ensure_fn, _nowait_fn, _args_fn, _status
    with _lock:
        _cancel_idle()
        _held = False
        _generating = False
        _stopped_server = False
        _config = None
        _stop_fn = stop
        _ensure_fn = ensure
        _nowait_fn = nowait
        _args_fn = args
        _status = None
