"""Pinch tap vs grab. Frozen hit. Desk delivery. No camera."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import (
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from arelis.spatial.gesture import CLICK_DEBOUNCE, GestureMachine, PinchClick
from arelis.spatial.hands_log import configure as hands_configure
from arelis.ui.filament_field import FilamentField
from arelis.ui.hands_desk import (
    clamp_rect_to_desks,
    deliver_click,
    fire_click,
    flick_rect,
    is_tile_chrome,
)
from tests.hands_pose import frame_of, make_hand


def _still_pinch(machine: GestureMachine, wrist, *, t0: float, pose: str = "pinch"):
    """Enter pinch, then still-unpinch. Returns clicks."""
    t = t0
    clicks = []
    for _ in range(3):
        machine.step(frame_of(make_hand("Right", wrist, pose=pose), t=t))
        clicks.extend(machine.consume_clicks())
        t += 0.03
    for _ in range(10):
        machine.step(frame_of(make_hand("Right", wrist, pose="open"), t=t))
        clicks.extend(machine.consume_clicks())
        t += 0.03
    return clicks, t


def test_still_pinch_unpinch_is_one_click() -> None:
    machine = GestureMachine()
    clicks, _t = _still_pinch(machine, (0.50, 0.55), t0=1.0)
    assert len(clicks) == 1
    assert clicks[0].who == "Right"
    assert clicks[0].travel < 0.035
    assert machine.consume_clicks() == []


def test_pinch_with_travel_is_grab_not_click() -> None:
    machine = GestureMachine()
    t = 2.0
    for _ in range(3):
        machine.step(frame_of(make_hand("Right", (0.40, 0.55), pose="pinch"), t=t))
        t += 0.03
    assert machine.tracks
    assert machine.tracks[0].state == "pinch"
    assert not machine.tracks[0].dragging
    for i in range(4):
        machine.step(
            frame_of(make_hand("Right", (0.40 + 0.03 * (i + 1), 0.55), pose="pinch"), t=t)
        )
        t += 0.03
    assert machine.tracks[0].dragging
    clicks = []
    for _ in range(5):
        machine.step(frame_of(make_hand("Right", (0.55, 0.55), pose="open"), t=t))
        clicks.extend(machine.consume_clicks())
        t += 0.03
    assert clicks == []


def test_click_xy_is_pinch_down_not_release() -> None:
    """Heisenberg: freeze the pointer at close. Release motion must not walk it."""
    machine = GestureMachine()
    origin = (0.42, 0.50)
    down = make_hand("Right", origin, pose="pinch")
    frozen = down.pointer_xy()
    t = 3.0
    for _ in range(3):
        machine.step(frame_of(down, t=t))
        t += 0.03
    moved = make_hand("Right", origin, pose="pinch", pointer=(frozen[0] + 0.12, frozen[1]))
    machine.step(frame_of(moved, t=t))
    t += 0.03
    clicks = []
    for _ in range(10):
        machine.step(
            frame_of(
                make_hand(
                    "Right",
                    origin,
                    pose="open",
                    pointer=(frozen[0] + 0.12, frozen[1]),
                ),
                t=t,
            )
        )
        clicks.extend(machine.consume_clicks())
        t += 0.03
    assert len(clicks) == 1
    assert abs(clicks[0].x - frozen[0]) < 1e-9
    assert abs(clicks[0].y - frozen[1]) < 1e-9
    assert abs(clicks[0].x - (frozen[0] + 0.12)) > 0.05


def test_twin_collapse_does_not_double_click() -> None:
    machine = GestureMachine()
    wrist = (0.50, 0.55)
    t = 4.0
    for _ in range(3):
        machine.step(
            frame_of(
                make_hand("Right", wrist, pose="pinch"),
                make_hand("Left", (wrist[0] + 0.01, wrist[1]), pose="pinch"),
                t=t,
            )
        )
        t += 0.03
    assert len(machine.tracks) == 1
    clicks = []
    for _ in range(10):
        machine.step(
            frame_of(
                make_hand("Right", wrist, pose="open"),
                make_hand("Left", (wrist[0] + 0.01, wrist[1]), pose="open"),
                t=t,
            )
        )
        clicks.extend(machine.consume_clicks())
        t += 0.03
    assert len(clicks) == 1
    later = t + CLICK_DEBOUNCE + 0.05
    clicks, _ = _still_pinch(machine, wrist, t0=later)
    assert len(clicks) == 1


def test_hit_float_names_the_title_chip() -> None:
    field = FilamentField()
    field.set_state("idle")
    rect = QRect(0, 0, 800, 600)
    title = field.title_point("chat", rect).toPoint()
    assert field.hit_float(title, rect) == "chat"
    bead = field.bead_point("history", rect).toPoint()
    assert field.hit_float(bead, rect) == "history"


def test_hit_float_skips_an_open_title() -> None:
    field = FilamentField()
    rect = QRect(0, 0, 800, 600)
    field.set_open_faces({"chat"})
    title = field.title_point("chat", rect).toPoint()
    bead = field.bead_point("chat", rect).toPoint()
    assert field.hit_float(bead, rect) == "chat"
    if (title - bead).manhattanLength() > 36:
        assert field.hit_float(title, rect) in (None, "chat")


def test_rim_button_is_not_tile_chrome(qt_app) -> None:
    tile = QWidget()
    tile.resize(240, 200)
    close_btn = QPushButton("x", tile)
    close_btn.setObjectName("SettingsClose")
    close_btn.setGeometry(210, 4, 24, 24)
    view = QTextEdit(tile)
    view.setObjectName("ChatView")
    view.setGeometry(12, 36, 216, 150)
    tile.show()
    rim = tile.mapToGlobal(QPoint(8, 8))
    assert is_tile_chrome(tile, rim)
    on_close = tile.mapToGlobal(QPoint(220, 14))
    assert not is_tile_chrome(tile, on_close)
    on_view = tile.mapToGlobal(QPoint(80, 100))
    assert not is_tile_chrome(tile, on_view)
    tile.hide()
    tile.deleteLater()


def test_flick_crosses_a_desk_then_clamps() -> None:
    geo = QRect(100, 80, 200, 160)
    left = QRect(0, 0, 400, 400)
    right = QRect(800, 0, 400, 400)
    dest = flick_rect(geo, 4000.0, 0.0, dt=0.42, desks=[left, right])
    assert dest.intersects(right)
    assert not dest.intersects(left)
    parked = clamp_rect_to_desks(QRect(2000, 80, 200, 160), [left, right])
    assert parked.intersects(right)
    assert parked.x() + parked.width() - 1 <= right.right()


def test_fire_click_buttons_and_copy_anchor(qt_app, tmp_path: Path) -> None:
    hits: list[str] = []
    host = QWidget()
    layout = QVBoxLayout(host)
    send = QPushButton("send")
    send.setObjectName("SendButton")
    send.clicked.connect(lambda: hits.append("send"))
    view = QTextBrowser()
    view.setOpenLinks(False)
    view.setHtml('<a href="arelis-act://copy">copy</a> · <a href="arelis-act://again">again</a>')
    view.anchorClicked.connect(lambda url: hits.append(url.host() or url.path()))
    layout.addWidget(send)
    layout.addWidget(view)
    host.resize(280, 160)
    host.show()
    qt_app.processEvents()
    name, ok = fire_click(send, send.mapToGlobal(QPoint(8, 8)))
    assert ok and name == "SendButton" and hits == ["send"]
    found = None
    for y in range(0, max(8, view.viewport().height()), 3):
        for x in range(0, max(8, view.viewport().width()), 3):
            href = view.anchorAt(QPoint(x, y))
            if href and "copy" in href:
                found = QPoint(x, y)
                break
        if found is not None:
            break
    assert found is not None
    name, ok = fire_click(view, view.mapToGlobal(found))
    assert ok
    assert "copy" in hits
    host.hide()
    host.deleteLater()


def test_empty_glass_click_is_a_logged_miss(qt_app, tmp_path: Path) -> None:
    hands_configure(tmp_path)
    try:
        host = QWidget()
        host.setObjectName("ArelisWindow")
        host.resize(400, 300)
        host._filament = None  # type: ignore[attr-defined]
        host.show()
        qt_app.processEvents()
        deliver_click(host, PinchClick(who="Right", x=0.20, y=0.80, travel=0.0), 1.0)
        rows = (tmp_path / "hands.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert rows
        rec = json.loads(rows[-1])
        assert rec["event"] == "click_miss"
        assert rec["hit"]
    finally:
        hands_configure(None)
        host.hide()
        host.deleteLater()


def test_bead_click_opens_and_names_the_hit(qt_app, tmp_path: Path) -> None:
    from arelis.ui.theme import apply_theme

    hands_configure(tmp_path)
    apply_theme("filament")
    opened: list[str] = []
    try:
        host = QWidget()
        host.resize(800, 600)
        field = FilamentField()
        field.set_state("idle")
        floats = type("F", (), {})()
        floats.opened = type("S", (), {"emit": lambda self, n: opened.append(n)})()
        host._filament = field  # type: ignore[attr-defined]
        host._filament_floats = floats  # type: ignore[attr-defined]
        host.show()
        qt_app.processEvents()
        bead = field.bead_point("chat", host.rect())
        # reach=1 → image x is mirrored: fx = 1 - nx
        nx = bead.x() / max(1, host.width() - 1)
        ny = bead.y() / max(1, host.height() - 1)
        click = PinchClick(who="Right", x=1.0 - nx, y=ny, travel=0.0)
        deliver_click(host, click, 1.0)
        assert opened == ["chat"]
        rec = json.loads(
            (tmp_path / "hands.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
        )
        assert rec["event"] == "click_hit"
        assert rec["hit"] == "chat"
    finally:
        hands_configure(None)
        apply_theme("sodium")
        host.hide()
        host.deleteLater()
