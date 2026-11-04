"""A Filament paint works out the current's shape once, not once per point.

The field paints on the UI thread that also hands her frames to the screen.
At 2560 px a paint asked for the ellipse about 1600 times (once per strand
segment and dust grain), about half of a 17 ms paint, so her frames stuttered.
"""

from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter


def test_one_paint_asks_for_the_ellipse_a_few_times(qt_app) -> None:
    from arelis.ui.filament_field import FilamentField

    field = FilamentField()
    calls = 0
    real = field.ellipse

    def counted(rect):
        nonlocal calls
        calls += 1
        return real(rect)

    field.ellipse = counted
    img = QImage(2560, 1392, QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(img)
    field.paint(painter, QRect(0, 0, 2560, 1392))
    painter.end()
    assert 0 < calls < 100
