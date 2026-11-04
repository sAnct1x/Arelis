"""ARELIS_SURFACE=quick: frames.csv has one writer. Her host (QuickSurfaceAvatar) is a
QQ3DAvatar, and both it and the surface opened the file with "w", so each truncated the
other's lines and Atria's frame times mixed two windows."""

from __future__ import annotations


def test_her_host_and_the_surface_open_one_frame_log(qt_app, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ARELIS_SURFACE", "quick")
    monkeypatch.setenv("ARELIS_FRAMETIME_LOG", str(tmp_path / "frames.csv"))
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face import qq3d_avatar, quick_surface

    opened = []
    real = qq3d_avatar.FrameLog

    class Counting(real):
        def __init__(self, *a, **k) -> None:
            opened.append(1)
            super().__init__(*a, **k)

    monkeypatch.setattr(qq3d_avatar, "FrameLog", Counting)
    host = QWidget()
    av = quick_surface.QuickSurfaceAvatar(host)
    quick_surface.surface_for(host)
    assert len(opened) == 1
    av._fail("test over")
    host.deleteLater()
