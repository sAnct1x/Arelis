"""Filament seats her as the bottom-left hub: no tile, threads start at her."""

from __future__ import annotations

import logging

from PySide6.QtCore import QPointF


def _filament(arelis_window, qt_app):
    w = arelis_window({"ui": {"default_width": 1200, "default_height": 800, "theme": "filament"}})
    w.show()
    qt_app.processEvents()
    return w


def test_filament_hosts_her_in_the_hub_not_a_tile(arelis_window, qt_app, caplog) -> None:
    from arelis.ui.persona_stage import persona_region

    caplog.set_level(logging.INFO, logger="arelis.avatar")
    w = _filament(arelis_window, qt_app)
    stage = w.persona_stage
    assert w.persona_panel.parentWidget() is stage
    assert stage.isVisible() and w.persona_dock.isHidden()
    parent = stage.parentWidget()
    assert stage.geometry() == persona_region(parent.rect(), None, mode="hub")
    assert stage.geometry().center().x() < parent.width() / 2
    from arelis.ui.filament_field import FLOATS

    assert "thinking" not in {f[0] for f in FLOATS}
    assert any("[avatar] resize mode=hub" in r.getMessage() for r in caplog.records)


def test_filament_threads_start_at_her_hub(arelis_window, qt_app) -> None:
    w = _filament(arelis_window, qt_app)
    field = w._filament
    stage = w.persona_stage
    hub = QPointF(stage.parentWidget().mapTo(w, stage.geometry().center()))
    assert field.hub == hub
    assert field.thread_start("chat", w.rect()) == hub
    threads = field.hub_threads(w.rect())
    assert threads and all(start == hub for start, _ in threads)


def test_painted_tethers_leave_from_her_hub(arelis_window, qt_app) -> None:
    from PySide6.QtGui import QImage, QPainter

    w = _filament(arelis_window, qt_app)
    field = w._filament
    field._tethers["probe"] = {"grow": 1.0, "end": QPointF(600, 200)}
    starts = []
    real = field._tether_point
    field._tether_point = lambda a, b, u: starts.append(QPointF(a)) or real(a, b, u)
    img = QImage(w.width(), w.height(), QImage.Format.Format_ARGB32_Premultiplied)
    painter = QPainter(img)
    try:
        field._paint_tethers(painter, w.rect())
    finally:
        painter.end()
        del field._tethers["probe"]
    assert starts and all(s == field.hub for s in starts)
