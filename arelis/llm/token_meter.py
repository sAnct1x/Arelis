"""How fast the model is producing tokens right now, for the Overseer readout.

llama-server streams one delta per token, so every streamed delta (reasoning,
reply text or tool-call arguments) is one tick. ``rate`` is ticks per second
over the last two seconds, and 0 once nothing has arrived for a second, so a
finished or stalled reply never leaves a frozen number behind.
"""

from __future__ import annotations

import threading
import time
from collections import deque

WINDOW_S = 2.0
STALE_S = 1.0

_lock = threading.Lock()
_ticks: deque[float] = deque(maxlen=4096)


def note_token(now: float | None = None) -> None:
    t = time.monotonic() if now is None else now
    with _lock:
        _ticks.append(t)


def rate(now: float | None = None) -> float:
    """Tokens per second now, or 0.0 when no tokens are flowing."""
    t = time.monotonic() if now is None else now
    with _lock:
        while _ticks and _ticks[0] < t - WINDOW_S:
            _ticks.popleft()
        if not _ticks or t - _ticks[-1] > STALE_S:
            return 0.0
        # A stream younger than the window is measured over its own age.
        span = max(0.5, min(WINDOW_S, t - _ticks[0]))
        return len(_ticks) / span
