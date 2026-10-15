"""Look stills are throwaways — not generated pictures."""

from __future__ import annotations

from pathlib import Path

import pytest

from arelis.look_scratch import (
    clear_look_pending,
    forget_look_scratch,
    is_look_scratch,
    keep_look_files,
    note_look_scratch,
    sweep_look_scratch,
)


@pytest.mark.no_ui
def test_look_scratch_prefixes(tmp_path: Path, monkeypatch) -> None:
    images = tmp_path / "images"
    images.mkdir()
    monkeypatch.setattr("arelis.look_scratch.images_dir", lambda: images)
    look = images / "browser_20260101T000000Z_abcd.png"
    desk = images / "desktop_20260101T000000Z_abcd.png"
    ocr = images / "ocr_screen_20260101T000000Z.png"
    made = images / "cat_watercolor.png"
    look.write_bytes(b"x")
    desk.write_bytes(b"x")
    ocr.write_bytes(b"x")
    made.write_bytes(b"x")
    assert is_look_scratch(look)
    assert is_look_scratch(desk)
    assert is_look_scratch(ocr)
    assert not is_look_scratch(made)
    assert not is_look_scratch(tmp_path / "other.png")


@pytest.mark.no_ui
def test_forget_and_sweep(tmp_path: Path, monkeypatch) -> None:
    images = tmp_path / "images"
    images.mkdir()
    monkeypatch.setattr("arelis.look_scratch.images_dir", lambda: images)
    clear_look_pending()
    shot = images / "browser_now.png"
    shot.write_bytes(b"png")
    keep = images / "portrait.png"
    keep.write_bytes(b"art")
    note_look_scratch(shot)
    assert forget_look_scratch(shot)
    assert not shot.exists()
    assert keep.exists()
    leftover = images / "desktop_later.png"
    leftover.write_bytes(b"png")
    note_look_scratch(leftover)
    assert sweep_look_scratch() == 1
    assert not leftover.exists()
    leftover.write_bytes(b"png")
    note_look_scratch(leftover)
    assert sweep_look_scratch(keep=True) == 0
    assert leftover.exists()
    clear_look_pending()


@pytest.mark.no_ui
def test_keep_ask() -> None:
    assert keep_look_files("save that screenshot")
    assert keep_look_files("keep the screen shot please")
    assert not keep_look_files("what's on the screen")
    assert not keep_look_files("open notepad and look at it")
    assert keep_look_files("take a screenshot of the page")
    assert keep_look_files("call the browser tool with action=screenshot")
    assert keep_look_files("capture a screenshot")
    assert keep_look_files("grab a screenshot of the current page")
    assert not keep_look_files("look at the page and tell me what you see")


