"""Per-phase timing for a UI switch, as one INFO line.

A theme switch costs 263-499 ms on Atria and a language switch 600-775 ms, and
the log only showed the frame stall. This splits the switch into its phases so
the next run says which one it is. The last phase runs to the next event-loop
pass after the switch, which is where the window repaints.
"""

from __future__ import annotations

import logging
import time

LOG = logging.getLogger("arelis.ui.timing")


class PhaseTrace:
    def __init__(self, name: str) -> None:
        self.name = name
        self._t0 = self._last = time.perf_counter()
        self._phases: list[tuple[str, float]] = []

    def mark(self, phase: str) -> None:
        now = time.perf_counter()
        self._phases.append((phase, (now - self._last) * 1000.0))
        self._last = now

    def line(self) -> str:
        total = (self._last - self._t0) * 1000.0
        parts = " ".join(f"{p}={ms:.1f}ms" for p, ms in self._phases)
        return f"[timing] {self.name} {parts} total={total:.1f}ms"

    def finish_after_repaint(self, phase: str = "repaint") -> None:
        """Log once the event loop has had its pass (the repaint), or now without one."""
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        def _done() -> None:
            self.mark(phase)
            LOG.info(self.line())

        if QApplication.instance() is None:
            _done()
            return
        QTimer.singleShot(0, _done)
