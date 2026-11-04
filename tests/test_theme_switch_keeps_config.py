"""Entering filament and opening a tile writes only the theme; a tile is saved when the user moves it."""

from __future__ import annotations

import yaml
from PySide6.QtTest import QTest

import arelis.config as cfg


def test_placing_tiles_does_not_rewrite_config_but_a_user_move_does(
    arelis_window, qt_app, tmp_path, monkeypatch
) -> None:
    local = tmp_path / "config.local.yaml"
    local.write_text("ui:\n  theme: night\n  filament_ack: true\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "LOCAL_CONFIG_PATH", local)
    w = arelis_window(
        {
            "ui": {
                "default_width": 1600,
                "default_height": 900,
                "theme": "night",
                "filament_ack": True,
            }
        }
    )
    w.show()
    qt_app.processEvents()
    w._choose_theme("filament", True)
    w.filament._filament_set_chat_open(True)
    QTest.qWait(1500)
    assert yaml.safe_load(local.read_text(encoding="utf-8")) == {
        "ui": {"theme": "filament", "filament_ack": True}
    }

    tile = w._filament_chat_tile
    tile.move(tile.x() + 40, tile.y() + 30)
    QTest.qWait(600)
    saved = yaml.safe_load(local.read_text(encoding="utf-8"))["ui"]
    assert saved["filament_tile_pos"]["chat"] == {
        "x": tile.frameGeometry().x(),
        "y": tile.frameGeometry().y(),
    }
