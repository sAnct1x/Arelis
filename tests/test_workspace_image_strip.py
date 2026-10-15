"""Desk image rail: recent outputs, readable thumbs, sidecar prompt/seed."""

from __future__ import annotations

import os
import time
from pathlib import Path

from arelis.ui.panels.workspace import (
    _THUMB_LONG,
    _recent_output_images,
)


def _touch(path: Path, when: float) -> Path:
    path.write_bytes(b"x")
    os.utime(path, (when, when))
    return path


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


