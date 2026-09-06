"""Image desk polish: caption, rail chrome, copy, rubric."""

from __future__ import annotations

import os
import time
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QToolButton

from arelis.tools.confirm_copy import confirm_headline
from arelis.tools.image import clamp_n
from arelis.tools.image_copy import image_progress_line
from arelis.tools.image_edit import overlay_font_paths
from arelis.tools.image_polish import CHECKS, score
from arelis.ui.image_rail import (
    CAPTION_NAME,
    DESK_EMPTY_PICTURES,
    IMAGE_STRIP_CAP,
    STRIP_NAME,
    THUMB_NAME,
    WELL_NAME,
    load_fail_line,
    load_fitted_pixmap,
    load_square_thumb,
    recent_output_images,
    sidecar_caption,
    sidecar_tooltip,
)
from arelis.ui.status_copy import tool_errand, tool_status_line
from arelis.ui.theme_qss import stylesheet


def _save_rgb(path: Path, width: int = 240, height: int = 120) -> Path:
    from PySide6.QtGui import QColor, QImage

    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(200, 80, 20))
    assert image.save(str(path))
    return path


def test_caption_names_picture(tmp_path: Path) -> None:
    path = tmp_path / "cube.png"
    path.write_bytes(b"x")
    (tmp_path / "cube.json").write_text(
        '{"prompt": "a red cube on a desk"}',
        encoding="utf-8",
    )
    assert sidecar_caption(path) == "cube.png · a red cube on a desk"
    long = tmp_path / "long.png"
    long.write_bytes(b"x")
    (tmp_path / "long.json").write_text(
        '{"prompt": "' + ("very long prompt " * 12) + '"}',
        encoding="utf-8",
    )
    cap = sidecar_caption(long, limit=24)
    assert cap.startswith("long.png · ")
    assert cap.endswith("…")
    assert len(cap) < 50


def test_fail_is_sentence() -> None:
    assert load_fail_line(Path("gone") / "ghost.png") == "Could not load ghost.png."


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


def test_progress_lines() -> None:
    assert image_progress_line() == "✦ making a picture…"
    line = image_progress_line(index=2, n=4, step=3, total=10)
    assert "picture 2 of 4" in line
    assert "(3/10)" in line


def test_strip_cap_and_n_clamp(tmp_path: Path) -> None:
    folder = tmp_path / "images"
    folder.mkdir()
    base = time.time()
    for i in range(20):
        path = folder / f"img_{i:02d}.png"
        path.write_bytes(b"x")
        os.utime(path, (base + i, base + i))
    assert len(recent_output_images(folder)) == IMAGE_STRIP_CAP
    assert IMAGE_STRIP_CAP == 16
    assert clamp_n(9) == 4
    assert clamp_n(0) == 1


def test_thumbs_and_hero_decode_to_display_size(qt_app, tmp_path: Path) -> None:
    path = _save_rgb(tmp_path / "wide.png", 400, 200)
    thumb = load_square_thumb(path, 48)
    assert not thumb.isNull()
    assert thumb.width() == 48
    assert thumb.height() == 48
    fitted = load_fitted_pixmap(path, 80, 60)
    assert not fitted.isNull()
    assert fitted.width() <= 80
    assert fitted.height() <= 60
    assert fitted.width() < 400


def test_overlay_prefers_plex() -> None:
    paths = overlay_font_paths()
    assert "IBMPlexSans-SemiBold.ttf" in str(paths[0])
    assert "arial" not in str(paths[0]).lower()
    first_hit = next(path for path in paths if path.is_file())
    assert "Plex" in first_hit.name


def test_qss_names_each_role() -> None:
    qss = stylesheet()
    for name in (WELL_NAME, STRIP_NAME, THUMB_NAME, CAPTION_NAME):
        assert f"#{name}" in qss
    assert qss.count("#WorkspaceImageWell") == 1


def test_desk_face_chrome(qt_app, tmp_path: Path) -> None:
    from arelis.ui.panels.workspace import WorkspacePanel

    first = _save_rgb(tmp_path / "first.png", 120, 80)
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
        assert DESK_EMPTY_PICTURES in panel.desk_empty.text()
        panel.show_image(str(first))
        assert panel.image_label.objectName() == WELL_NAME
        assert panel.image_strip.objectName() == STRIP_NAME
        assert panel.image_caption.objectName() == CAPTION_NAME
        thumbs = panel.image_strip.findChildren(QToolButton)
        assert thumbs
        assert all(thumb.objectName() == THUMB_NAME for thumb in thumbs)
        assert {WELL_NAME, STRIP_NAME, THUMB_NAME} == {
            panel.image_label.objectName(),
            panel.image_strip.objectName(),
            thumbs[0].objectName(),
        }
        assert "sodium lamp" in sidecar_tooltip(first)
        assert "sodium lamp" in panel.image_label.toolTip()
        assert not panel.image_open_btn.isHidden()
        current = next(t for t in thumbs if t.accessibleName() == "first.png")
        assert current.isChecked()

        left = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Left,
            Qt.KeyboardModifier.NoModifier,
        )
        panel.keyPressEvent(left)
        qt_app.processEvents()
        assert Path(panel.path_edit.text()).name == "second.png"
        right = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Right,
            Qt.KeyboardModifier.NoModifier,
        )
        panel.keyPressEvent(right)
        qt_app.processEvents()
        assert Path(panel.path_edit.text()).name == "first.png"
    finally:
        panel.deleteLater()


def test_polish_rubric_is_complete() -> None:
    passed = {c.id for c in CHECKS}
    scores = score(passed)
    assert scores["intuitiveness"] == 10.0
    assert scores["usability"] == 10.0
    assert scores["visual"] == 10.0
    assert scores["scalability"] == 10.0
    assert scores["maintainability"] == 10.0
    assert {c.axis for c in CHECKS} == set(scores)
    assert len(CHECKS) == 29
