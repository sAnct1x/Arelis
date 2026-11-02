"""One failed worker paint must not wedge the orbit: later ticks still get frames."""

from __future__ import annotations

import time

from PySide6.QtCore import QCoreApplication, QRect
from PySide6.QtWidgets import QApplication


def _pump_until(cond, timeout_s: float = 5.0) -> bool:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    return False


def test_a_raising_paint_does_not_freeze_the_field(monkeypatch):
    QApplication.instance() or QApplication([])
    from arelis.ui.filament_field import FilamentField
    from arelis.ui.filament_render import FieldRenderer

    calls = {"n": 0}

    def paint(self, painter, rect):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("first paint fails")

    monkeypatch.setattr(FilamentField, "_paint", paint)
    render = FieldRenderer(FilamentField())
    try:
        rect = QRect(0, 0, 64, 48)
        render.request(rect, 1.5)
        assert _pump_until(lambda: not render._busy), "done never came: _busy wedged"
        render.request(rect, 1.5)
        assert _pump_until(lambda: render.frame_for(rect, 1.5) is not None)
    finally:
        render.stop()
