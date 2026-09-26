"""Look stills are throwaways — not generated pictures."""

from __future__ import annotations

import os
from pathlib import Path

from arelis.look_scratch import (
    clear_look_pending,
    forget_look_scratch,
    hold_look_files,
    is_look_scratch,
    keep_look_files,
    note_look_scratch,
    prune_look_scratch,
    sweep_look_scratch,
)


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


def test_hold_skips_forget(tmp_path: Path, monkeypatch) -> None:
    images = tmp_path / "images"
    images.mkdir()
    monkeypatch.setattr("arelis.look_scratch.images_dir", lambda: images)
    clear_look_pending()
    shot = images / "browser_keep.png"
    shot.write_bytes(b"png")
    note_look_scratch(shot)
    hold_look_files(True)
    assert not forget_look_scratch(shot)
    assert shot.exists()
    clear_look_pending()


def test_sweep_means_followup_needs_a_new_grab(
    tmp_path: Path, monkeypatch
) -> None:
    """A later 'third paragraph' cannot reuse the deleted still."""
    images = tmp_path / "images"
    images.mkdir()
    monkeypatch.setattr("arelis.look_scratch.images_dir", lambda: images)
    clear_look_pending()
    shot = images / "desktop_book.png"
    shot.write_bytes(b"png")
    note_look_scratch(shot)
    assert sweep_look_scratch() == 1
    assert not shot.exists()
    assert not keep_look_files("now the third paragraph")
    clear_look_pending()


def test_keep_ask() -> None:
    assert keep_look_files("save that screenshot")
    assert keep_look_files("keep the screen shot please")
    assert not keep_look_files("what's on the screen")
    assert not keep_look_files("open notepad and look at it")


def test_prune_keeps_newest(tmp_path: Path) -> None:
    images = tmp_path / "images"
    images.mkdir()
    paths = []
    for i in range(6):
        p = images / f"browser_{i:02d}.png"
        p.write_bytes(b"x")
        paths.append(p)
    for i, p in enumerate(paths):
        os.utime(p, (1_000 + i, 1_000 + i))
    cam_old = images / "camera_old.jpg"
    cam_new = images / "camera_new.jpg"
    cam_old.write_bytes(b"j")
    cam_new.write_bytes(b"j")
    os.utime(cam_old, (1_000, 1_000))
    os.utime(cam_new, (1_010, 1_010))
    art = images / "cat_watercolor.png"
    art.write_bytes(b"art")
    removed = prune_look_scratch(directory=images, keep=2, camera_keep=1)
    assert removed == 5
    left = sorted(p.name for p in images.iterdir())
    assert left == ["browser_04.png", "browser_05.png", "camera_new.jpg", "cat_watercolor.png"]
