"""Filament load: she appears first, the ring grows out of her hub, tiles grow from their filament."""

from __future__ import annotations

import logging
import math

import pytest
from PySide6.QtCore import QPoint, QPointF, QRect

from arelis.ui.filament_field import RING_GROW_S, FilamentField


def _filament(arelis_window, qt_app):
    w = arelis_window({"ui": {"default_width": 1200, "default_height": 800, "theme": "filament"}})
    w.show()
    qt_app.processEvents()
    return w


def _on_ring(p: QPointF, ring: tuple[float, float, float, float]) -> bool:
    cx, cy, rx, ry = ring
    return abs(((p.x() - cx) / rx) ** 2 + ((p.y() - cy) / ry) ** 2 - 1.0) < 1e-6


def test_ring_waits_until_she_is_up() -> None:
    field = FilamentField()
    up = {"v": False}
    field.begin_ring_growth(lambda: up["v"])
    for _ in range(20):
        field.tick(0.05)
    assert field.ring_grow == 0.0
    up["v"] = True
    field.tick(0.05)
    field.tick(0.05)
    assert 0.0 < field.ring_grow < 1.0


def test_entering_filament_grows_the_ring_out_of_her_hub(arelis_window, qt_app, caplog) -> None:
    caplog.set_level(logging.INFO, logger="arelis.avatar")
    w = _filament(arelis_window, qt_app)
    field, rect = w._filament, w.rect()
    hub = QPointF(field.hub)
    field.ring_grow, field._ring_phase = 0.0, "wait"
    cx, cy, rx, _ry = field.ellipse(rect)
    assert math.hypot(cx - hub.x(), cy - hub.y()) < 1.0 and rx < 10.0
    last_rx = rx
    for _ in range(int(RING_GROW_S / 0.05) + 4):
        field.tick(0.05)
        ring = field.ellipse(rect)
        assert ring[2] >= last_rx
        last_rx = ring[2]
        assert all(start == hub and _on_ring(end, ring) for start, end in field.hub_threads(rect))
    assert field.ring_grow == 1.0
    text = caplog.text
    assert "[avatar] filament load step=she appears" in text
    assert "[avatar] filament load step=ring grows origin=" in text
    assert "[avatar] filament load step=ring settled" in text


@pytest.mark.parametrize("parked", [False, True])
def test_a_tile_grows_from_the_end_of_its_filament(
    arelis_window, qt_app, monkeypatch, parked
) -> None:
    import arelis.ui.filament_desk as desk

    w = _filament(arelis_window, qt_app)
    calls = []

    def grow(wid, o, d, **k):  # the real grow ends with the tile on d
        calls.append((o, d))
        wid.setGeometry(d)

    monkeypatch.setattr(desk, "play_tile_grow", grow)
    if parked:
        top = w.mapToGlobal(QPoint(500, 300))
        w._filament_tile_pos["history"] = (top.x(), top.y())
    w._toggle_history(True)
    qt_app.processEvents()
    assert len(calls) == 1
    origin, dest = calls[0]
    local = QRect(w.mapFromGlobal(dest.topLeft()), dest.size())
    seed = w._filament.spawn_origin("history", local, w.rect())
    assert origin == w.mapToGlobal(QPoint(int(seed.x()), int(seed.y())))
    assert w._filament._tethers["history"]["end"] == seed


def test_the_seed_is_centred_on_the_spawn_origin() -> None:
    from arelis.ui.filament_tile import tile_grow_rects

    seed, plate = tile_grow_rects(QPoint(400, 300), QRect(380, 200, 320, 280))
    assert seed.center() == QPoint(400, 300)
    assert plate == QRect(380, 200, 320, 280)
