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

from PySide6.QtCore import QEvent, QObject, Qt, QTimer

log = logging.getLogger("arelis.startup")

POLL_MS = 50
# A cold 35B load can take minutes; past this the app opens anyway.
GIVE_UP_S = 300.0
_STATUS = {"model": "Loading model", "arelis": "Drawing Arelis", "tree": "Growing the tree"}


def startup_waits(window: Any) -> dict[str, Callable[[], bool]]:
    """What the open app needs before it is shown, by name, each a ready check."""
    from arelis.ui import theme

    router = getattr(window, "router", None)
    panel = getattr(window, "persona_panel", None)
    waits: dict[str, Callable[[], bool]] = {
        "model": lambda: router is None or not router.warmup_pending(),
        "arelis": lambda: panel is None or not panel.scene_pending(),
    }
    field = getattr(window, "_filament", None)
    if theme.active_theme() == "filament" and field is not None:
        # Leaving Filament mid-launch stops the tree, so it no longer counts.
        waits["tree"] = lambda: theme.active_theme() != "filament" or field.tree_built()
    return waits


def _pass_input_through(window: Any, on: bool) -> None:
    """Set the native window's click-through flag in place, without re-creating it."""
    handle = window.windowHandle()
    if handle is not None:
        handle.setFlag(Qt.WindowType.WindowTransparentForInput, on)


def _ready(name: str, check: Callable[[], bool]) -> bool:
    """A check that raises counts as ready, so it can never hold the window hidden."""
    try:
        return bool(check())
    except Exception:
        log.warning("startup %s check failed; not waiting on it", name, exc_info=True)
        return True


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
        # Invisible but still hit-tested: without this the hidden window took
        # clicks meant for other apps until the handoff.
        _pass_input_through(self._window, True)
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
            if _ready(name, ready):
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
        _pass_input_through(self._window, False)
        self._window.setWindowOpacity(1.0)
        if self._splash is not None:
            self._splash.finish()
        self._mark("open")


def hold_until_ready(window: Any, splash: Any, t0: float | None = None) -> StartupGate:
    gate = StartupGate(window, splash, t0)
    window._startup_gate = gate
    gate.start()
    return gate
