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
    turn's thought block. Status and model lines show on her caption when the
    dock is open, in that thought block while a turn runs, and on the chat
    status line for a few seconds when she is closed and idle.
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
                # A window with no face has nowhere else to show the line.
                # Location redaction is checked on that thought text.
                if getattr(window, "persona_panel", None) is None:
                    window.chat.add_thought_line(line, keep_internal=True)
                    return
                self._show_aside(window, line)
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
            self._show_aside(self._window, chunk.strip())
            return
        self._window.chat.extend_thought(chunk)

    def clear(self) -> None:
        self._last_status = ""
        self._last_essay = ""

    def _show_aside(self, window, line: str) -> None:
        """Internal lines stay on her caption, or the chat status line when she is closed."""
        dock = getattr(window, "persona_dock", None)
        panel = getattr(window, "persona_panel", None)
        open_dock = dock is not None and not dock.isHidden()
        if open_dock and panel is not None:
            panel.show_status(line)
            return
        window.chat.show_idle_note(line)

    def _route_status(self, window, line: str) -> None:
        dock = getattr(window, "persona_dock", None)
        panel = getattr(window, "persona_panel", None)
        open_dock = dock is not None and not dock.isHidden()
        if open_dock and panel is not None:
            panel.show_status(line)
        busy = bool(getattr(window, "_turn_busy", False))
        if busy:
            window.chat.add_thought_line(line)
            return
        if not open_dock:
            window.chat.show_idle_note(line)
