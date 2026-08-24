"""Composer attachment rail: Cursor-style tiles, not a grey filename slab."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import QToolButton

from arelis.attachments import format_attachments_block
from arelis.ui.attach_bar import (
    ATTACH_TILE,
    AttachBar,
    AttachmentTile,
    cover_crop_pixmap,
    tile_pixel_size,
)
from arelis.ui.panels.chat import ChatPanel, _user_bubble_html
from arelis.ui.theme import stylesheet


def _png(path: Path, width: int, height: int) -> Path:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(255, 80, 20))
    assert image.save(str(path), "PNG")
    return path


def test_tile_pixel_size_portrait_is_square() -> None:
    assert tile_pixel_size(40, 80) == (ATTACH_TILE, ATTACH_TILE)


def test_tile_pixel_size_landscape_is_wider() -> None:
    width, height = tile_pixel_size(80, 40)
    assert height == ATTACH_TILE
    assert width == round(ATTACH_TILE * 1.7)
    assert width > height


def test_cover_crop_pixmap_fills_the_tile(qt_app) -> None:
    source = QPixmap(80, 40)
    source.fill(QColor(255, 80, 20))
    cropped = cover_crop_pixmap(source, 95, 56)
    assert cropped.width() == 95
    assert cropped.height() == 56


def test_bar_is_hidden_when_empty(qt_app) -> None:
    bar = AttachBar()
    try:
        assert bar.count() == 0
        assert not bar.isVisible()
        assert bar.height() == 0
    finally:
        bar.deleteLater()


def test_image_tile_is_cover_cropped_not_a_filename_chip(qt_app, tmp_path: Path) -> None:
    png = _png(tmp_path / "wide.png", 80, 40)
    bar = AttachBar()
    try:
        bar.resize(800, 80)
        bar.add_many(
            [
                {
                    "id": "img-1",
                    "name": "wide.png",
                    "path": str(png),
                    "kind": "image",
                    "bytes": 12,
                    "source_path": "",
                }
            ]
        )
        bar.show()
        qt_app.processEvents()
        tiles = bar.findChildren(AttachmentTile)
        assert len(tiles) == 1
        tile = tiles[0]
        expect_w, expect_h = tile_pixel_size(80, 40)
        assert tile.height() == expect_h == ATTACH_TILE
        assert tile.width() == expect_w
        assert tile.width() < bar.width()
        assert tile._image
        assert not tile._pixmap.isNull()
        assert bar.isVisible()
        assert bar.height() == ATTACH_TILE + 10
    finally:
        bar.hide()
        bar.deleteLater()


def test_file_tile_is_square_and_the_same_height(qt_app, tmp_path: Path) -> None:
    note = tmp_path / "notes.txt"
    note.write_text("hi", encoding="utf-8")
    png = _png(tmp_path / "shot.png", 80, 40)
    bar = AttachBar()
    try:
        bar.resize(800, 80)
        bar.add_many(
            [
                {
                    "id": "file-1",
                    "name": "notes.txt",
                    "path": str(note),
                    "kind": "text",
                    "bytes": 2,
                    "source_path": "",
                },
                {
                    "id": "img-1",
                    "name": "shot.png",
                    "path": str(png),
                    "kind": "image",
                    "bytes": 12,
                    "source_path": "",
                },
            ]
        )
        bar.show()
        qt_app.processEvents()
        tiles = bar.findChildren(AttachmentTile)
        assert len(tiles) == 2
        file_tile, image_tile = tiles
        assert file_tile.height() == image_tile.height() == ATTACH_TILE
        assert file_tile.width() == ATTACH_TILE
        assert image_tile.width() > ATTACH_TILE
        assert not file_tile._image
        assert image_tile._image
    finally:
        bar.hide()
        bar.deleteLater()


def test_remove_clears_the_last_tile(qt_app, tmp_path: Path) -> None:
    note = tmp_path / "notes.txt"
    note.write_text("hi", encoding="utf-8")
    bar = AttachBar()
    try:
        bar.add_many(
            [
                {
                    "id": "file-1",
                    "name": "notes.txt",
                    "path": str(note),
                    "kind": "text",
                    "bytes": 2,
                    "source_path": "",
                }
            ]
        )
        qt_app.processEvents()
        tile = bar.findChildren(AttachmentTile)[0]
        button = tile.findChild(QToolButton)
        assert button is not None
        button.click()
        qt_app.processEvents()
        assert bar.count() == 0
        assert not bar.isVisible()
        assert bar.height() == 0
    finally:
        bar.hide()
        bar.deleteLater()


def test_stylesheet_does_not_fill_tiles(qt_app) -> None:
    css = stylesheet()
    assert "AttachmentChip" not in css
    assert "AttachmentTile" in css


def test_user_bubble_embeds_an_image(qt_app, tmp_path: Path) -> None:
    png = _png(tmp_path / "shot.png", 80, 40)
    html = _user_bubble_html(
        "what is this",
        attachments=[
            {
                "id": "img-1",
                "name": "shot.png",
                "path": str(png),
                "kind": "image",
            }
        ],
    )
    assert "<img " in html
    assert png.name in html or png.as_uri() in html.replace("&amp;", "&")
    assert "what is this" in html


def test_user_bubble_files_stay_names(qt_app, tmp_path: Path) -> None:
    note = tmp_path / "notes.txt"
    note.write_text("hi", encoding="utf-8")
    html = _user_bubble_html(
        "summarize",
        attachments=[
            {
                "id": "file-1",
                "name": "notes.txt",
                "path": str(note),
                "kind": "text",
            }
        ],
    )
    assert "<img " not in html
    assert "notes.txt" in html


def test_history_reload_renders_image_thumb_not_boilerplate(
    qt_app, tmp_path: Path
) -> None:
    png = _png(tmp_path / "shot.png", 80, 40)
    block = format_attachments_block(
        [{"path": png.as_posix(), "kind": "image"}],
        user_text="what is this",
    )
    turn = f"{block}\n\nwhat is this"
    panel = ChatPanel()
    try:
        panel.load_messages([{"role": "user", "content": turn}])
        html = panel.view.toHtml()
        text = panel.view.toPlainText()
        assert "what is this" in text
        assert "Attachments for this turn" not in text
        assert "<img " in html.lower() or "file:" in html.lower()
    finally:
        panel.hide()
        panel.deleteLater()
