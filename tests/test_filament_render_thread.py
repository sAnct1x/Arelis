"""Filament's orbit paints on a worker thread, never the GUI thread her frames render on."""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QCoreApplication, QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication


def test_the_orbit_is_painted_off_the_gui_thread_and_matches_an_in_place_paint(monkeypatch):
    QApplication.instance() or QApplication([])
    from arelis.ui.filament_field import FilamentField
    from arelis.ui.filament_render import FieldRenderer

    field = FilamentField()
    field.tick(0.03)
    painted_on = []
    real = FilamentField._paint

    def spy(self, painter, rect):
        painted_on.append(threading.get_ident())
        real(self, painter, rect)

    monkeypatch.setattr(FilamentField, "_paint", spy)
    render = FieldRenderer(field)
    rect = QRect(0, 0, 640, 360)
    assert render.frame_for(rect, 1.0) is None  # first ask starts a paint
    # Not QTest.qWait: it holds the GIL while it waits, so the worker's Python paint
    # only runs in the gaps (a 2 ms paint took 0.8 s locally, over 2 s on CI).
    deadline = time.monotonic() + 10.0
    while render.frame() is None and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    frame = render.frame_for(rect, 1.0)
    render.stop()
    assert frame is not None
    assert painted_on and threading.get_ident() not in painted_on
    ref = QImage(640, 360, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(ref)
    real(field, p, rect)
    p.end()
    assert frame == ref
