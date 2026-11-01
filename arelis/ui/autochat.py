"""Measurement only: send one typed chat turn with no keyboard, mouse or focus.

Inert unless ``ARELIS_AUTOCHAT_PROMPT`` is set. Then the prompt goes through the chat box's own
submit path (the same as Enter), either once ``ARELIS_AUTOCHAT_TRIGGER`` (a file path) exists or,
without a trigger, ``ARELIS_AUTOCHAT_DELAY_S`` seconds (default 30) after start-up. Progress is
appended to ``ARELIS_AUTOCHAT_LOG`` as ``<event> <epoch_ms>`` lines: ``sent``, then ``done`` once
the turn is no longer busy (the reply finished streaming), or ``never_busy``.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from PySide6.QtCore import QTimer

_log = logging.getLogger("arelis.autochat")
_POLL_MS = 250
_BUSY_WITHIN_S = 30.0


class AutoChat:
    def __init__(self, window, prompt: str, trigger: str, delay_s: float, log_path: str) -> None:
        self._window = window
        self._prompt = prompt
        self._trigger = Path(trigger) if trigger else None
        self._log_path = Path(log_path) if log_path else None
        self._sent_at = 0.0
        self._seen_busy = False
        self._timer = QTimer(window)
        self._timer.setInterval(_POLL_MS)
        self._timer.timeout.connect(self._tick)
        self._due = time.monotonic() + delay_s
        self._timer.start()

    def _note(self, event: str) -> None:
        _log.info("[autochat] %s", event)
        if self._log_path is not None:
            with self._log_path.open("a", encoding="ascii") as fh:
                fh.write(f"{event} {int(time.time() * 1000)}\n")

    def _busy(self) -> bool:
        return bool(getattr(self._window, "_turn_busy", False))

    def _tick(self) -> None:
        if not self._sent_at:
            ready = self._trigger.exists() if self._trigger else time.monotonic() >= self._due
            conv = getattr(self._window, "conversation", None)
            if not ready or conv is None or self._busy():
                return
            conv.input.setText(self._prompt)
            conv._submit()
            self._sent_at = time.monotonic()
            self._note("sent")
            return
        if self._busy():
            self._seen_busy = True
        elif self._seen_busy:
            self._timer.stop()
            self._note("done")
        elif time.monotonic() - self._sent_at > _BUSY_WITHIN_S:
            self._timer.stop()
            self._note("never_busy")


def install(window, env=os.environ) -> AutoChat | None:
    prompt = env.get("ARELIS_AUTOCHAT_PROMPT", "").strip()
    if not prompt:
        return None
    try:
        delay = float(env.get("ARELIS_AUTOCHAT_DELAY_S", "") or 30)
    except ValueError:
        delay = 30.0
    window._autochat = AutoChat(
        window,
        prompt,
        env.get("ARELIS_AUTOCHAT_TRIGGER", "").strip(),
        delay,
        env.get("ARELIS_AUTOCHAT_LOG", "").strip(),
    )
    return window._autochat
