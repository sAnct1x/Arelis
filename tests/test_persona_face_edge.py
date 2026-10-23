"""The painted face fades out before the edge of her frame. No hard rectangle."""

from __future__ import annotations

import time

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from arelis.ui.persona_face.panel import BLOOM_S, PersonaPanel

BACKDROP = QColor(30, 28, 46)


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
    clock = {"t": 0.0}
    panel = PersonaPanel()
    panel.resize(370, 520)
    panel.set_bake_delay(60.0)
    panel.set_clock(lambda: clock["t"])
    panel.show()
    qt_app.processEvents()
    panel._timer.stop()
    panel.set_state("speaking")
    # Bake is still pending. The bloom clock finishes mid-reply.
    clock["t"] = BLOOM_S + 26.0
    panel.tick()
    panel.avatar.request_bake(0)
    deadline = time.monotonic() + 40
    while not panel.bake_ready and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.02)
    assert panel.bake_ready
    panel.tick()
    panel.avatar.repaint()
    qt_app.processEvents()
    assert _face_body_drawn(panel)

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
