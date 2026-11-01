"""Filament seats her full height in the right band: no tile, threads start at her centre."""

from __future__ import annotations

import logging

from PySide6.QtCore import QPointF


def _filament(arelis_window, qt_app):
    w = arelis_window({"ui": {"default_width": 1200, "default_height": 800, "theme": "filament"}})
    w.show()
    qt_app.processEvents()
    return w


def test_filament_hosts_her_full_height_not_a_tile(arelis_window, qt_app, caplog) -> None:
    from arelis.ui.persona_stage import _chat_min, persona_region

    caplog.set_level(logging.INFO, logger="arelis.avatar")
    w = _filament(arelis_window, qt_app)
    stage = w.persona_stage
    assert w.persona_panel.parentWidget() is stage
    assert stage.isVisible()
    parent = stage.parentWidget()
    # The base layer: all of the stage, full height; she stands right of centre.
    assert stage.geometry() == persona_region(parent.rect(), None, chat_min=_chat_min(w), base_layer=True)
    assert stage.geometry() == parent.rect()
    assert w._filament.hub.x() > parent.mapTo(w, parent.rect().center()).x()
    from arelis.ui.filament_field import FLOATS

    assert "thinking" not in {f[0] for f in FLOATS}
    assert any("[avatar] resize" in r.getMessage() for r in caplog.records)


def test_filament_threads_start_at_her_hub(arelis_window, qt_app) -> None:
    w = _filament(arelis_window, qt_app)
    field = w._filament
    stage = w.persona_stage
    hub = QPointF(field.hub)
    zone = stage.zone()
    assert zone.contains(stage.parentWidget().mapFrom(w, hub.toPoint()))
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


def test_across_two_desks_she_stands_on_the_home_desk(arelis_window, qt_app, monkeypatch) -> None:
    """A 2 desk span seats her and the orbit on the home desk, not across the union."""
    from PySide6.QtCore import QRect

    from arelis.ui import filament_desk

    w = _filament(arelis_window, qt_app)
    w.resize(1600, 800)
    qt_app.processEvents()
    home = QRect(0, 0, 800, 800)
    union = QRect(0, 0, 1600, 800)
    monkeypatch.setattr(filament_desk.FilamentDesk, "_filament_can_claim_desk", lambda self: True)
    monkeypatch.setattr(filament_desk.FilamentDesk, "_filament_pin_home", lambda self: home)
    monkeypatch.setattr(
        filament_desk,
        "filament_chosen_desks",
        lambda *a, **k: (union, home, [home, QRect(800, 0, 800, 800)]),
    )
    filament_desk.filament_apply_shape(w)
    stage = w.persona_stage
    base = QRect(stage.parentWidget().mapTo(w, stage.geometry().topLeft()), stage.size())
    assert base == home
    assert home.contains(w._filament.hub.toPoint())
    cx, _cy, rx, _ry = w._filament.ellipse(w.rect(), settled=True)
    assert home.left() <= cx - rx and cx + rx < w._filament.hub.x()
