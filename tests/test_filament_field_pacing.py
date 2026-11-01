"""The orbit ticks at 60 Hz: its paint runs on filament_render's worker, so a costly paint
drops frames there instead of slowing the tick."""

from __future__ import annotations

from arelis.ui.filament_field import FilamentField


def test_orbit_ticks_at_60_hz_whatever_its_paint_costs(qt_app) -> None:
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter

    field = FilamentField()
    img = QImage(2560, 1440, QImage.Format.Format_ARGB32_Premultiplied)
    for _ in range(20):
        p = QPainter(img)
        field.paint(p, QRect(0, 0, 2560, 1440))
        p.end()
    assert field.atmosphere_ms() <= 17
