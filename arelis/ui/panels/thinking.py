"""Routes thinking lines into the chat, and status onto her dock when she is open."""

from __future__ import annotations

import logging
import re

from PySide6.QtCore import QObject

from arelis.location.privacy import redact

log = logging.getLogger(__name__)

# Model traffic and turn bookkeeping. Her reasoning is everything else.
_INTERNAL = re.compile(
    r"thinking(?:\.\.\.|\u2026)\s*\(fast:"
    r"|Role ['\"]"
    r"|\bRole "
    r"|round \d+/"
    r"|phase="
    r"|timing\s+total"
    r"|loading the model"
    r"|waiting for the conversation model"
    r"|Ready for the first reply",
    re.IGNORECASE,
)


def internal_status(line: str) -> bool:
    """True when a line is status or a model note, not her own reasoning."""
    return _INTERNAL.search(line or "") is not None


class ThinkingPanel(QObject):
    """Same append / extend_stream / clear entry the rest of the window already calls.

    Nothing is painted in a dock anymore. Trace and tool lines go to the current
    turn's thought block. Other status goes into that block while a turn runs,
    and onto the welcome screen when she is idle. Internal lines are logged only.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._window = None
        self._last_status = ""
        self._last_essay = ""

    def bind(self, window) -> None:
        self._window = window

    def append(self, text: str, kind: str = "trace") -> None:
        line = redact((text or "").strip())
        if not line:
            return
        window = self._window
        if window is None:
            return
        if kind in {"status", "model"} or internal_status(line):
            if line == self._last_status:
                return
            self._last_status = line
            if internal_status(line):
                log.info("%s", line)
                return
            self._route_status(window, line)
            return
        if line == self._last_essay:
            return
        self._last_essay = line
        window.chat.add_thought_line(line)

    def extend_stream(self, chunk: str) -> None:
        if not chunk:
            return
        chunk = redact(chunk)
        if not chunk or self._window is None:
            return
        if internal_status(chunk):
            log.info("%s", chunk.strip())
            return
        self._window.chat.extend_thought(chunk)

    def clear(self) -> None:
        self._last_status = ""
        self._last_essay = ""

    def _route_status(self, window, line: str) -> None:
        busy = bool(getattr(window, "_turn_busy", False))
        if busy:
            window.chat.add_thought_line(line)
            return
        window.chat.show_idle_note(line)
