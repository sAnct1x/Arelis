"""Hands session telemetry. Always on while the session is live.

One line per event in logs/hands.log, one JSON object in
logs/hands.jsonl. Local only. Nothing is sent anywhere.

Frames never land here — only numbers. Pytest writes nothing unless a
test points us at a temp dir.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

from arelis.paths import logs_dir

log = logging.getLogger("arelis.hands.trace")

_HANDLER_TAG = "arelis-hands-trace"
_lock = threading.Lock()
_log_dir: Path | None = None
_attached = False
_last_sample = 0.0
_SAMPLE_S = 1.0


def configure(log_dir: Path | None) -> None:
    """Tests point this at tmp. None restores the real logs/ tree."""
    global _log_dir, _attached
    with _lock:
        _log_dir = Path(log_dir) if log_dir is not None else None
        _attached = False
        for existing in list(log.handlers):
            if getattr(existing, "_arelis_tag", "") == _HANDLER_TAG:
                log.removeHandler(existing)
                existing.close()


def emit(event: str, **fields: Any) -> None:
    """Record one hands event. Cheap no-op under pytest without configure()."""
    if os.environ.get("PYTEST_CURRENT_TEST") and _log_dir is None:
        return
    clean = {key: _sanitize(key, value) for key, value in fields.items()}
    line = _format(event, clean)
    record = {
        "ts": time.time(),
        "event": event,
        **{key: _jsonable(value) for key, value in clean.items()},
    }
    with _lock:
        _ensure_handler()
        log.info(line)
        _append_jsonl(record)


def sample(event: str, **fields: Any) -> None:
    """At most once a second. Pose / FPS."""
    global _last_sample
    now = time.monotonic()
    if now - _last_sample < _SAMPLE_S:
        return
    _last_sample = now
    emit(event, **fields)


def _directory() -> Path:
    return _log_dir if _log_dir is not None else logs_dir()


def _ensure_handler() -> None:
    global _attached
    if _attached:
        return
    directory = _directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        handler = RotatingFileHandler(
            directory / "hands.log",
            maxBytes=4 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
    except OSError:
        return
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._arelis_tag = _HANDLER_TAG  # type: ignore[attr-defined]
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    _attached = True


def _append_jsonl(record: dict[str, Any]) -> None:
    path = _directory() / "hands.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except OSError:
        return


def _format(event: str, fields: dict[str, Any]) -> str:
    stamp = time.strftime("%H:%M:%S", time.localtime())
    millis = int((time.time() % 1) * 1000)
    body = " ".join(f"{key}={_render(value)}" for key, value in fields.items())
    return f"hands   {stamp}.{millis:03d} {event:<16} {body}".rstrip()


def _render(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value)
    return str(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)


def _sanitize(key: str, value: Any) -> Any:
    name = key.lower()
    if any(
        bit in name
        for bit in (
            "url",
            "source",
            "token",
            "secret",
            "password",
            "key",
            "cite",
            "stream",
            "rtsp",
            "look",
            "frame",
            "rgb",
            "image",
        )
    ):
        return "-"
    return value
