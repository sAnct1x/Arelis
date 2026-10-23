"""The painted face fades out before the edge of her frame. No hard rectangle."""

from __future__ import annotations

import time

from PySide6.QtGui import QColor
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


def _face_body_drawn(panel: PersonaPanel) -> bool:
    """True when the skin plate is still on the grab, not an empty halo."""
    image = panel.avatar.grab().toImage()
    pixel = image.pixelColor(image.width() // 2, int(image.height() * 0.38))
    return pixel.alpha() > 200 and pixel.blue() > 180 and pixel.blue() >= pixel.red() - 20


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

    clock = {"t": 10.0}
    panel.set_clock(lambda: clock["t"])
    panel._last = 10.0
    panel.set_state("speaking")
    panel._mode = "face"
    panel.avatar.reveal = 1.0
    for _ in range(8):
        clock["t"] += 0.033
        panel.tick()
        panel.avatar.repaint()
    qt_app.processEvents()
    assert _face_body_drawn(panel)
    # A late speaking wake can ask for bloom again. The body must stay drawn.
    panel._mode = "orb"
    panel.set_state("speaking")
    panel.tick()
    panel.avatar.repaint()
    qt_app.processEvents()
    assert _face_body_drawn(panel)

    panel.close()
    QApplication.processEvents()


