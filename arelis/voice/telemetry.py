"""Tracing for the conversation loop, off unless voice.debug is set.

The voice loop is a state machine spread over three threads: Qt owns the
microphone and the speaker, asyncio owns transcription and synthesis, and the
bus is the seam between them. When it wedges, the symptom is always the same
uninformative one -- she stops hearing you -- and the cause is whichever of
about six flags is stuck. Reproducing it by hand is slow because it needs real
speech and real silences.

So every transition records the whole state vector rather than a message. One
line per event, fixed field order, so a stuck state can be read off the last
few lines instead of inferred:

    voice 14:22:31.402 speech_end        mode=conversation listening=1 ...

Off by default. Arelis configures no logging at all, so turning this on also
attaches the file handler that makes it visible, at logs/voice.log, rather than
depending on how the app was launched.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from pathlib import Path
from typing import Any

from arelis.paths import logs_dir

log = logging.getLogger("arelis.voice.trace")

# Enough to cover several turns of back and forth, which is as far back as a
# stuck state is ever worth reading. This is a debugging aid, not a log.
_RING = 400

_HANDLER_TAG = "arelis-voice-trace"


class VoiceTrace:
    """Records voice state transitions to a ring buffer and, optionally, a file.

    Cheap enough to call unconditionally from the audio path: when disabled
    every method returns before touching the arguments, so the caller does not
    have to guard the call sites and the enabled path is the only one that
    formats anything.
    """

    def __init__(self, enabled: bool = False, *, log_dir: Path | None = None) -> None:
        self.enabled = bool(enabled)
        self._log_dir = log_dir
        self._entries: deque[str] = deque(maxlen=_RING)
        if self.enabled:
            _attach_file_handler(self._log_dir or logs_dir())

    def record(self, event: str, **state: Any) -> None:
        if not self.enabled:
            return
        self._write(event, state)

    def record_always(self, event: str, **state: Any) -> None:
        """Conversation decisions always hit the ring and logs/voice.log.

        Full debug stays opt-in for every VAD tick. Wake, barge-in, Smart Turn,
        live STT, dropped utterances, and engine fallbacks have to be countable
        without turning the rest of the loop into a firehose.
        """
        _attach_file_handler(self._log_dir or logs_dir())
        self._write(event, state)

    def record_wake(self, event: str, **state: Any) -> None:
        """Wake decisions always hit logs/voice.log (alias of record_always)."""
        self.record_always(event, **state)

    def _write(self, event: str, state: dict[str, Any]) -> None:
        line = _format(event, state)
        self._entries.append(line)
        log.info(line)

    def recent(self, limit: int = 40) -> list[str]:
        """The last few transitions, oldest first."""
        if limit <= 0:
            return []
        return list(self._entries)[-limit:]

    def clear(self) -> None:
        self._entries.clear()


def _format(event: str, state: dict[str, Any]) -> str:
    stamp = time.strftime("%H:%M:%S", time.localtime())
    millis = int((time.time() % 1) * 1000)
    fields = " ".join(f"{key}={_render(value)}" for key, value in state.items())
    return f"voice {stamp}.{millis:03d} {event:<18} {fields}".rstrip()


def _render(value: Any) -> str:
    # Booleans as 1/0 so a row of flags lines up and can be scanned vertically.
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _attach_file_handler(log_dir: Path) -> None:
    """Send trace lines to logs/voice.log, once per process.

    Handlers are tagged rather than counted: the window rebuilds its controller
    when voice recovers from a capture failure, and a second handler would
    double every line for the rest of the session. If the path changes (tests
    pass a tmp dir), retarget instead of keeping the first process handler.
    """
    target = Path(log_dir) / "voice.log"
    for existing in list(log.handlers):
        if getattr(existing, "_arelis_tag", "") != _HANDLER_TAG:
            continue
        current = Path(getattr(existing, "baseFilename", "") or "")
        try:
            same = current.resolve() == target.resolve()
        except OSError:
            same = current == target
        if same:
            return
        log.removeHandler(existing)
        existing.close()
        break
    try:
        from logging.handlers import RotatingFileHandler

        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            target,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        # A read-only install should not lose voice, only its trace file. The
        # ring buffer still works and still answers "what was the last state".
        return
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._arelis_tag = _HANDLER_TAG  # type: ignore[attr-defined]
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    # The trace is its own stream. Letting it reach the root logger would put
    # it on stderr as well, which is where the app's own output goes.
    log.propagate = False


def trace_enabled(config: dict[str, Any]) -> bool:
    return bool((config.get("voice") or {}).get("debug", False))
