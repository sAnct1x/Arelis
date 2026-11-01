"""Filament: a ring word that drifts across the edge of her figure stays whole (it read "da")."""

from __future__ import annotations

from PySide6.QtCore import QPoint


def test_a_ring_word_across_her_edge_is_not_cut(arelis_window, qt_app) -> None:
    w = arelis_window({"ui": {"default_width": 1600, "default_height": 900, "theme": "filament"}})
    w.show()
    qt_app.processEvents()
    stage = w.persona_stage
    edge = stage.parentWidget().mapTo(w, stage.zone().topLeft()).x()
    btn = w._filament_floats._buttons["days"]
    btn.show()
    btn.adjustSize()
    at = QPoint(edge - btn.width() // 2, 300)
    btn.move(btn.parentWidget().mapFrom(w, at))
    qt_app.processEvents()
    assert btn.visibleRegion().boundingRect().width() == btn.width()
