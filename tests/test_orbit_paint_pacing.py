"""The orbit must not re-render its vector scene for repaints it did not cause."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

from arelis.ui import void_idle
from arelis.ui.void_idle import OrbitCanvas, orbit_interval_ms


def test_foreign_repaints_blit_cache_and_tick_is_cost_paced(qapp=None):
    app = QApplication.instance() or QApplication([])
    host = QWidget()
    host.resize(400, 400)
    orbit = OrbitCanvas(host)
    host.show()
    app.processEvents()
    first = orbit.renders
    # 30 repaints driven by something else (her avatar frames over the orbit).
    for _ in range(30):
        orbit.repaint()
    assert orbit.renders - first <= 1
    # A tick moves the orbit: one fresh render.
    orbit._tick()
    orbit.repaint()
    assert orbit.renders - first <= 2
    assert orbit._timer.isSingleShot()
    assert orbit_interval_ms(10.0) >= 8 * 10.0
    void_idle.set_avatar_warming(True)
    try:
        assert orbit_interval_ms(0.5) >= 250
    finally:
        void_idle.set_avatar_warming(False)
    host.deleteLater()
