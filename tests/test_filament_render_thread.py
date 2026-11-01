"""Filament's orbit paints on a worker thread, never the GUI thread her frames render on."""

from __future__ import annotations

import threading

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter
from PySide6.QtTest import QTest
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
    for _ in range(100):
        if render.frame() is not None:
            break
        QTest.qWait(20)
    frame = render.frame_for(rect, 1.0)
    render.stop()
    assert frame is not None
    assert painted_on and threading.get_ident() not in painted_on
    ref = QImage(640, 360, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(ref)
    real(field, p, rect)
    p.end()
    assert frame == ref
