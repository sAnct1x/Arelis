"""Filament load: she appears first, the ring grows out of her hub, tiles grow from their filament."""

from __future__ import annotations

import logging
import math

import pytest
from PySide6.QtCore import Q_ARG, QMetaObject, QPoint, QPointF, QRect, Qt

from arelis.ui.filament_field import (
    FLOATS,
    FREE_FLOATS,
    RING_GROW_S,
    TITLE_FADE_S,
    FilamentField,
)


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
    # She is up: under qq3d offscreen her scene never reports ready, so the gate would hold
    # the ring for RING_WAIT_MAX_S, past this loop. The gate has its own path in the app.
    field._ring_gate = None
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


def test_tile_titles_fade_in_at_their_spot_once_the_ring_settles(arelis_window, qt_app) -> None:
    w = _filament(arelis_window, qt_app)
    field, rect = w._filament, w.rect()
    field.crown = True  # the tree's crown (OrbitState): titles ride the ring itself
    field.begin_ring_growth(None)
    name = next(n for n, _t, _p in FLOATS if n not in FREE_FLOATS)
    spot = field.float_points(name, rect)[1]
    layers = _quick_orbit_layers(field, rect)
    shows = []
    for _ in range(int((RING_GROW_S + TITLE_FADE_S) / 0.05) + 6):
        field.tick(0.05)
        if layers:  # the GPU's pulses and node rings (reality's light) on the titles' value
            st, orbit, flares, pulses = layers
            st.update(field, rect)
            for _f in range(3):  # its own ring clock runs ahead, as when the field's frames stall
                QMetaObject.invokeMethod(
                    orbit, "step", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", 0.05)
                )
            show = field.title_show()
            assert abs(flares.property("opacity") - show) < 1e-6
            assert abs(pulses.property("opacity") - show) < 1e-6
        here = field.float_points(name, rect)[1]
        assert math.hypot(here.x() - spot.x(), here.y() - spot.y()) < 12.0  # its drift, never the trip from her hub
        shows.append((field.ring_grow, field.title_show()))
        if 0.0 < shows[-1][1] < 0.15:
            early = _reality_ink(field, rect)
    assert all(show == 0.0 for grow, show in shows if grow < 1.0)
    assert shows[-1][1] == 1.0
    assert early < 0.25 * _reality_ink(field, rect)  # reality's rings fade in with the rest


def _quick_orbit_layers(field, rect):
    from PySide6.QtCore import QObject, QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    from arelis.ui.persona_face.orbit_state import OrbitState
    from arelis.ui.persona_face.qq3d_avatar import QML_DIR

    st = OrbitState()
    st.update(field, rect)
    engine = QQmlEngine()
    engine.rootContext().setContextProperty("orbitState", st)
    comp = QQmlComponent(engine)
    comp.setData(
        b"import QtQuick\nQuickOrbit { st: orbitState }\n",
        QUrl.fromLocalFile(str(QML_DIR / "_t.qml")),
    )
    orbit = comp.create()
    if orbit is None:
        return None
    _quick_orbit_layers.keep = (engine, comp)
    find = orbit.findChild
    return st, orbit, find(QObject, "orbitFlares"), find(QObject, "orbitPulses")


def _reality_ink(field, rect) -> float:
    from PySide6.QtGui import QImage, QPainter

    img = QImage(rect.size(), QImage.Format.Format_ARGB32)
    img.fill(0)
    hidden, field._hidden = field._hidden, {n for n, _t, _p in FLOATS if n not in FREE_FLOATS}
    painter = QPainter(img)
    field._paint_beads(painter, rect)
    painter.end()
    field._hidden = hidden
    return sum(img.constBits().tobytes()[3::4])


@pytest.mark.parametrize("parked", [False, True])
def test_a_tile_grows_from_its_node_on_the_tree(
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
    node = w.mapToGlobal(w._filament.bead_point("history", w.rect()).toPoint())
    w._toggle_history(True)
    qt_app.processEvents()
    assert len(calls) == 1
    origin, dest = calls[0]
    local = QRect(w.mapFromGlobal(dest.topLeft()), dest.size())
    # its own spot on the tree (the node drifts a few px with the sim's clock)
    assert (origin - node).manhattanLength() <= 8, (origin, node)
    seed = w._filament.spawn_origin("history", local, w.rect())
    assert w._filament._tethers["history"]["end"] == seed


def test_a_tile_reopens_at_its_saved_size_and_spot_even_past_the_window(
    arelis_window, qt_app, monkeypatch
) -> None:
    import arelis.ui.filament_desk as desk

    w = _filament(arelis_window, qt_app)
    calls = []

    def grow(wid, o, d, **k):
        calls.append(QRect(d))
        wid.setGeometry(d)

    monkeypatch.setattr(desk, "play_tile_grow", grow)
    # bigger than the old 720x800 cap, and hanging off the window's right edge
    spot = w.mapToGlobal(QPoint(w.width() - 300, 40))
    w._filament_tile_sizes["history"] = (1100, 760)
    w._filament_tile_pos["history"] = (spot.x(), spot.y())
    w._toggle_history(True)
    qt_app.processEvents()
    assert calls == [QRect(spot.x(), spot.y(), 1100, 760)]


def test_the_seed_is_centred_on_the_spawn_origin() -> None:
    from arelis.ui.filament_tile import tile_grow_rects

    seed, plate = tile_grow_rects(QPoint(400, 300), QRect(380, 200, 320, 280))
    assert seed.center() == QPoint(400, 300)
    assert plate == QRect(380, 200, 320, 280)


def test_a_tile_is_never_on_screen_at_its_saved_spot_before_it_grows(
    arelis_window, qt_app, monkeypatch
) -> None:
    from PySide6.QtCore import QEvent, QObject

    import arelis.ui.filament_desk as desk

    w = _filament(arelis_window, qt_app)
    dock = w.camera_dock
    dock.setFloating(True)  # a Filament tile is its own window once it has been opened
    dock.hide()
    qt_app.processEvents()
    seen: list[tuple[str, float]] = []

    class Spy(QObject):
        def eventFilter(self, obj, event):
            if obj is self.target and event.type() == QEvent.Type.Show:
                seen.append(("show", obj.windowOpacity()))
            return False

    Spy.target = dock
    spy = Spy()
    dock.installEventFilter(spy)
    monkeypatch.setattr(desk, "play_tile_grow", lambda *a, **k: seen.append(("grow", 0.0)))
    # Anything that lets frames through before the grow (as on Windows) must find it unseen.
    monkeypatch.setattr(w.camera, "start", qt_app.processEvents)
    w._toggle_camera(True)
    qt_app.processEvents()
    dock.removeEventFilter(spy)
    assert ("grow", 0.0) in seen
    before = seen[: seen.index(("grow", 0.0))]
    assert all(opacity == 0.0 for _kind, opacity in before), seen
    # Notify, on its second open too: the grow is its first show, so no full-size frame
    # (a fresh native window on Windows could carry the saved opacity on it).
    inbox = w.notify_inbox
    for _ in range(2):
        seen.clear()
        inbox.installEventFilter(spy)
        Spy.target = inbox
        w._toggle_notifications(True)
        qt_app.processEvents()
        inbox.removeEventFilter(spy)
        assert seen and seen[0][0] == "grow", seen
        w._toggle_notifications(False)
        qt_app.processEvents()


def test_the_splash_stays_until_model_arelis_tree_and_a_paint_are_ready(
    arelis_window, qt_app, monkeypatch
) -> None:
    from types import SimpleNamespace

    from arelis.ui.startup_gate import hold_until_ready

    w = _filament(arelis_window, qt_app)
    warming = {"v": True}
    monkeypatch.setattr(w, "router", SimpleNamespace(warmup_pending=lambda: warming["v"]))
    built = {"v": False}
    monkeypatch.setattr(w._filament, "tree_built", lambda: built["v"])
    splash = SimpleNamespace(closed=0, note=lambda _t: None)
    splash.finish = lambda: setattr(splash, "closed", splash.closed + 1)
    gate = hold_until_ready(w, splash)
    gate._poll()
    assert (splash.closed, w.windowOpacity()) == (0, 0.0)
    warming["v"] = False
    gate._poll()
    assert splash.closed == 0  # the tree is still growing
    built["v"] = True
    gate._poll()
    assert splash.closed == 0  # no full frame painted yet
    w.repaint()
    gate._poll()
    assert (splash.closed, w.windowOpacity()) == (1, 1.0)
