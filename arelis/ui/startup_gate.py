"""Hold the launch splash until the open app is whole, then hand off in one step.

The window maps at opacity 0 behind the splash so her scene, the tree and the
first frame can render for real. Each wait is polled here: the model warmed,
Arelis drawn, the Filament tree built, then one full paint of the window. Only
then does the window turn opaque and the splash close, in the same tick.

Every step is logged as ``startup`` with the time since the splash opened, so
the slow parts of a launch can be found later.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QEvent, QObject, QTimer

log = logging.getLogger("arelis.startup")

POLL_MS = 50
# A cold 35B load can take minutes; past this the app opens anyway.
GIVE_UP_S = 300.0
_STATUS = {"model": "Loading model", "arelis": "Drawing Arelis", "tree": "Growing the tree"}


def startup_waits(window: Any) -> dict[str, Callable[[], bool]]:
    """What the open app needs before it is shown, by name, each a ready check."""
    from arelis.ui.theme import active_theme

    router = getattr(window, "router", None)
    panel = getattr(window, "persona_panel", None)
    waits: dict[str, Callable[[], bool]] = {
        "model": lambda: router is None or not router.warmup_pending(),
        "arelis": lambda: panel is None or not panel.scene_pending(),
    }
    field = getattr(window, "_filament", None)
    if active_theme() == "filament" and field is not None:
        waits["tree"] = field.tree_built
    return waits


class StartupGate(QObject):
    """Polls the waits, then waits for one paint, then shows the window."""

    def __init__(self, window: Any, splash: Any, t0: float | None = None) -> None:
        super().__init__(window)
        self._window = window
        self._splash = splash
        self._t0 = time.monotonic() if t0 is None else t0
        self._waits = startup_waits(window)
        self._painted = False
        self.done = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)

    def _mark(self, step: str) -> None:
        ms = int((time.monotonic() - self._t0) * 1000)
        log.info("startup %s at %d ms", step, ms)

    def start(self) -> None:
        self._mark("window built")
        self._window.setWindowOpacity(0.0)
        self._timer.start()
        self._poll()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._window and event.type() == QEvent.Type.Paint:
            self._painted = True
        return False

    def _poll(self) -> None:
        if self.done:
            return
        for name, ready in list(self._waits.items()):
            if ready():
                del self._waits[name]
                self._mark(f"{name} ready")
        late = time.monotonic() - self._t0 >= GIVE_UP_S
        if self._waits and not late:
            self._show_status(next(iter(self._waits)))
            return
        if late and self._waits:
            log.warning("startup gave up waiting on %s", ", ".join(self._waits))
            self._waits.clear()
        if not self._painted:
            if not getattr(self, "_watching", False):
                self._watching = True
                self._window.installEventFilter(self)
                self._window.update()
            if not late:
                return
        self._open()

    def _show_status(self, waiting_on: str) -> None:
        note = getattr(self._splash, "note", None)
        if callable(note):
            note(_STATUS.get(waiting_on, "Starting"))

    def _open(self) -> None:
        self.done = True
        self._timer.stop()
        self._window.removeEventFilter(self)
        self._mark("first frame painted")
        self._window.setWindowOpacity(1.0)
        if self._splash is not None:
            self._splash.finish()
        self._mark("open")


def hold_until_ready(window: Any, splash: Any, t0: float | None = None) -> StartupGate:
    gate = StartupGate(window, splash, t0)
    window._startup_gate = gate
    gate.start()
    return gate
