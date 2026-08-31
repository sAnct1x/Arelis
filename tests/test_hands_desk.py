"""Desk mapping, chrome vs list, flick clamp, palm-scroll steps. No camera."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

from arelis.spatial.scene import image_to_world
from arelis.spatial.video import pick_preview_format
from arelis.ui.filament_field import FilamentField
from arelis.ui.hands_desk import (
    clamp_rect_to_desks,
    flick_rect,
    is_tile_chrome,
    on_span_edge,
    scroll_steps,
    span_pixel,
)


def test_span_pixel_centers_the_union() -> None:
    x, y = span_pixel(0.5, 0.5, 1920, 1080)
    assert x == 959
    assert y == 539


def test_span_edge_is_the_rim() -> None:
    assert on_span_edge(0.01, 0.5)
    assert on_span_edge(0.5, 0.99)
    assert not on_span_edge(0.5, 0.5)


def test_c920_maps_across_the_mirrored_span() -> None:
    nx, ny = image_to_world(0.25, 0.4, reach=1.0)
    x, y = span_pixel(nx, ny, 3000, 1000)
    assert x > 1500
    assert y == 399


def test_session_format_caps_at_640_when_tile_is_down() -> None:
    picked = pick_preview_format(
        [
            (1920, 1080, 30.0, "Format_Jpeg"),
            (1280, 720, 30.0, "Format_Jpeg"),
            (640, 480, 30.0, "Format_Jpeg"),
        ],
        max_width=640,
    )
    assert picked is not None
    assert picked[0] == 640


def test_flick_parks_on_a_live_desk() -> None:
    geo = QRect(100, 100, 320, 240)
    desks = [QRect(0, 0, 1920, 1080), QRect(1920, 0, 1920, 1080)]
    dest = flick_rect(geo, 8000.0, 0.0, desks=desks)
    assert any(d.intersects(dest) for d in desks)
    parked = clamp_rect_to_desks(QRect(-4000, 40, 320, 240), desks)
    assert desks[0].intersects(parked) or desks[1].intersects(parked)


def test_scroll_steps_follow_the_hand() -> None:
    assert scroll_steps(-0.05, 24) < 0
    assert scroll_steps(0.05, 24) > 0
    assert scroll_steps(0.0, 24) == 0


def test_tile_chrome_is_rim_not_the_list(qt_app) -> None:
    tile = QWidget()
    tile.resize(400, 300)
    layout = QVBoxLayout(tile)
    title = QLabel("chat")
    layout.addWidget(title)
    scroll = QScrollArea()
    scroll.setWidget(QLabel("body" * 40))
    layout.addWidget(scroll, stretch=1)
    tile.show()
    qt_app.processEvents()
    rim = tile.mapToGlobal(QPoint(8, 8))
    mid = scroll.viewport().mapToGlobal(scroll.viewport().rect().center())
    assert is_tile_chrome(tile, rim)
    assert not is_tile_chrome(tile, mid)
    tile.close()


def test_hot_bead_is_a_set() -> None:
    field = FilamentField()
    field.set_hot({"chat", "history"})
    assert "chat" in field._hot
    field.set_hot(set())
    assert not field._hot
