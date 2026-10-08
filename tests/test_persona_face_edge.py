"""The painted face fades out before the edge of her frame. No hard rectangle."""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from arelis.ui.persona_face.motion import Frame
from arelis.ui.persona_face.panel import PersonaPanel

BACKDROP = QColor(30, 28, 46)


def _ready_panel(qt_app, width: int, height: int) -> PersonaPanel:
    panel = PersonaPanel()
    panel.resize(width, height)
    panel.set_bake_delay(0)
    panel.show()
    qt_app.processEvents()
    deadline = time.monotonic() + 40
    while not panel.bake_ready and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    assert panel.bake_ready
    panel._timer.stop()
    panel._mode = "face"
    panel._state = "rest"
    panel._speaking = False
    panel._status = ""
    panel.avatar.reveal = 1.0
    panel.avatar.frame = Frame(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 0, False, 0, 0)
    panel.repaint()
    qt_app.processEvents()
    return panel


def _gap_to_backdrop(image, x: int, y: int) -> int:
    pixel = image.pixelColor(x, y)
    return max(
        abs(pixel.red() - BACKDROP.red()),
        abs(pixel.green() - BACKDROP.green()),
        abs(pixel.blue() - BACKDROP.blue()),
    )


def test_the_painted_face_fades_before_the_frame_edge(qt_app) -> None:
    """Outside her frame is pure backdrop, and just inside it is within a couple of levels.

    A hard rectangle shows up as a lit band right at the frame edge, so that
    band is what this reads. The old plate sat 30 or more levels above the
    backdrop there.
    """
    for width, height in ((370, 520), (375, 890)):
        panel = _ready_panel(qt_app, width, height)
        pix = QPixmap(panel.size())
        pix.fill(BACKDROP)
        painter = QPainter(pix)
        panel.render(painter, QPoint(0, 0))
        painter.end()
        image = pix.toImage()
        rect = panel.avatar._face_rect()
        left, top = int(rect.left()), int(rect.top())
        right, bottom = int(rect.right()), int(rect.bottom())
        inset_x = max(2, int(rect.width() * 0.03))
        inset_y = max(2, int(rect.height() * 0.03))
        plate_h = panel.avatar.height()
        worst_out = 0
        worst_band = 0
        for y in range(plate_h):
            for x in range(width):
                inside = left <= x <= right and top <= y <= bottom
                if not inside:
                    worst_out = max(worst_out, _gap_to_backdrop(image, x, y))
                    continue
                deep = (
                    left + inset_x <= x <= right - inset_x
                    and top + inset_y <= y <= bottom - inset_y
                )
                if not deep:
                    worst_band = max(worst_band, _gap_to_backdrop(image, x, y))
        assert worst_out < 1, (width, height, worst_out)
        assert worst_band <= 3, (width, height, worst_band)
        panel.close()
        QApplication.processEvents()


def test_the_edge_fade_is_built_once_per_size(qt_app) -> None:
    """The fade is a cached mask. Frames reuse it, and only a resize builds a new one."""
    panel = _ready_panel(qt_app, 370, 520)
    built = panel.avatar.mask_builds
    assert built >= 1
    for _ in range(20):
        panel.avatar.repaint()
    assert panel.avatar.mask_builds == built
    panel.resize(330, 600)
    qt_app.processEvents()
    panel.avatar.repaint()
    assert panel.avatar.mask_builds == built + 1
    panel.close()
    QApplication.processEvents()
