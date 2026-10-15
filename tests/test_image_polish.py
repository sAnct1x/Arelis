"""Image desk polish: caption, rail chrome, copy, rubric."""

from __future__ import annotations

from pathlib import Path

from arelis.tools.confirm_copy import confirm_headline
from arelis.ui.status_copy import tool_errand, tool_status_line


def _save_rgb(path: Path, width: int = 240, height: int = 120) -> Path:
    from PySide6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(200, 80, 20))
    assert image.save(str(path))
    return path


def test_status_and_confirm_are_human() -> None:
    assert tool_errand("image") == "making a picture"
    assert "calling" not in tool_errand("image")
    assert tool_status_line("image").startswith("✦ making a picture")
    assert tool_errand("image", {"n": 4}) == "making 4 pictures"
    assert tool_errand("image", {"path": "a.png"}) == "restyling the picture"
    assert tool_errand("image_edit", {"scale": 2}) == "resizing the picture"
    assert confirm_headline("image", {}) == "make a picture"
    assert confirm_headline("image", {"path": "a.png", "style": "watercolor"}) == (
        "restyle this as watercolor"
    )
    assert confirm_headline("image", {"remove_background": True}) == (
        "cut out the background"
    )
    assert confirm_headline("image_edit", {"crop": "left"}) == "crop this picture"
    assert confirm_headline("image_edit", {"scale": 2}) == "enlarge this picture"
    assert confirm_headline("image_edit", {"text": "Arelis"}) == (
        'add "Arelis" to this picture'
    )


