"""Desk image rail: recent outputs, readable thumbs, sidecar prompt/seed."""

from __future__ import annotations

import os
import time
from pathlib import Path

from arelis.ui.panels.workspace import (
    _THUMB_LONG,
    _recent_output_images,
    _sidecar_tooltip,
)


def _touch(path: Path, when: float) -> Path:
    path.write_bytes(b"x")
    os.utime(path, (when, when))
    return path


def test_recent_output_images_newest_first_skips_sidecars(tmp_path: Path) -> None:
    folder = tmp_path / "outputs" / "images"
    folder.mkdir(parents=True)
    base = time.time()
    _touch(folder / "old.png", base)
    _touch(folder / "mid.jpg", base + 10)
    _touch(folder / "new.webp", base + 20)
    (folder / "new.json").write_text('{"prompt": "skip me"}', encoding="utf-8")
    (folder / "notes.txt").write_text("not an image", encoding="utf-8")
    (folder / "nested").mkdir()
    (folder / "nested" / "deep.png").write_bytes(b"x")

    names = [p.name for p in _recent_output_images(folder)]
    assert names == ["new.webp", "mid.jpg", "old.png"]


def test_recent_output_images_caps_at_sixteen(tmp_path: Path) -> None:
    folder = tmp_path / "images"
    folder.mkdir()
    base = time.time()
    for i in range(20):
        _touch(folder / f"img_{i:02d}.png", base + i)

    found = _recent_output_images(folder)
    assert len(found) == 16
    assert found[0].name == "img_19.png"
    assert found[-1].name == "img_04.png"


def test_recent_output_images_missing_or_empty(tmp_path: Path) -> None:
    assert _recent_output_images(tmp_path / "gone") == []
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _recent_output_images(empty) == []
    assert _recent_output_images(tmp_path / "file.png") == []


def test_sidecar_tooltip_filename_only(tmp_path: Path) -> None:
    path = tmp_path / "shot.png"
    path.write_bytes(b"x")
    assert _sidecar_tooltip(path) == "shot.png"


def test_sidecar_tooltip_prompt_and_seed(tmp_path: Path) -> None:
    path = tmp_path / "cube.png"
    path.write_bytes(b"x")
    (tmp_path / "cube.json").write_text(
        '{"prompt": "a red cube on a desk", "seed": 42}',
        encoding="utf-8",
    )
    tip = _sidecar_tooltip(path)
    assert tip.splitlines()[0] == "cube.png"
    assert "a red cube on a desk" in tip
    assert "seed 42" in tip


def test_sidecar_tooltip_seed_only_and_bad_json(tmp_path: Path) -> None:
    seed_only = tmp_path / "plain.png"
    seed_only.write_bytes(b"x")
    (tmp_path / "plain.json").write_text('{"seed": 7}', encoding="utf-8")
    tip = _sidecar_tooltip(seed_only)
    assert tip == "plain.png\nseed 7"

    broken = tmp_path / "broken.png"
    broken.write_bytes(b"x")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert _sidecar_tooltip(broken) == "broken.png"

    listed = tmp_path / "listed.png"
    listed.write_bytes(b"x")
    (tmp_path / "listed.json").write_text('["not", "an", "object"]', encoding="utf-8")
    assert _sidecar_tooltip(listed) == "listed.png"


def _save_rgb(path: Path, width: int = 120, height: int = 80) -> Path:
    from PySide6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(200, 80, 20))
    assert image.save(str(path))
    return path


def test_image_strip_hidden_until_show_image(qt_app, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QToolButton

    from arelis.ui.panels.workspace import WorkspacePanel

    first = _save_rgb(tmp_path / "first.png")
    second = _save_rgb(tmp_path / "second.png", 80, 120)
    base = time.time()
    os.utime(first, (base, base))
    os.utime(second, (base + 10, base + 10))
    (tmp_path / "first.json").write_text(
        '{"prompt": "sodium lamp", "seed": 11}',
        encoding="utf-8",
    )

    panel = WorkspacePanel()
    try:
        assert panel.image_strip.isHidden()
        panel.show_image(str(first))
        assert not panel.image_strip.isHidden()
        thumbs = panel.image_strip.findChildren(QToolButton)
        assert [thumb.accessibleName() for thumb in thumbs] == [
            "second.png",
            "first.png",
        ]
        assert all(thumb.width() == thumb.height() == _THUMB_LONG for thumb in thumbs)
        first_thumb = next(t for t in thumbs if t.accessibleName() == "first.png")
        assert "sodium lamp" in first_thumb.toolTip()
        assert "seed 11" in first_thumb.toolTip()
        assert first_thumb.isChecked()
        assert "sodium lamp" in panel.image_label.toolTip()
        assert "first.png" in panel.image_caption.text()
        assert "sodium lamp" in panel.image_caption.text()
        assert not panel.image_open_btn.isHidden()

        other = next(t for t in thumbs if t.accessibleName() == "second.png")
        other.click()
        qt_app.processEvents()
        assert panel.path_edit.text() == str(second)
        assert not panel.image_strip.isHidden()
        thumbs = [
            thumb
            for thumb in panel._image_strip_host.findChildren(QToolButton)
            if thumb.parent() is panel._image_strip_host
        ]
        current = next(t for t in thumbs if t.accessibleName() == "second.png")
        assert current.isChecked()
        assert not next(t for t in thumbs if t.accessibleName() == "first.png").isChecked()

        panel._set_image_mode(False)
        assert panel.image_strip.isHidden()
    finally:
        panel.deleteLater()


def test_image_strip_stays_hidden_when_folder_has_no_images(qt_app, tmp_path: Path) -> None:
    from arelis.ui.panels.workspace import WorkspacePanel

    missing = tmp_path / "gone" / "ghost.png"
    panel = WorkspacePanel()
    try:
        panel.show_image(str(missing))
        assert not panel.image_label.isHidden()
        assert panel.image_strip.isHidden()
        assert panel.image_label.text() == "Could not load ghost.png."
    finally:
        panel.deleteLater()
