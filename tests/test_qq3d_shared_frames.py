"""ARELIS_SURFACE=quick: once frames are shared, her render thread hands the surface the
texture it drew and never reads a frame back. The readback made every frame wait for the
GPU and the surface upload it again: on Atria her thread ran at 13 to 14 fps and the
surface took 34 to 37 ms a frame against 18 on base."""

from __future__ import annotations

import pytest
from PySide6.QtTest import QTest


def test_shared_frames_reach_the_surface_with_no_readback(qt_app) -> None:
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face import qq3d_avatar, quick_surface

    if qq3d_avatar.unavailable_reason():
        pytest.skip(qq3d_avatar.unavailable_reason())

    class Surface:  # stands in for the QQuickWidget, which renders nothing offscreen
        def __init__(self) -> None:
            self.frames, self.images = [], 0

        def set_loading(self, on: bool) -> None:
            pass

        def set_figure(self, image) -> None:
            self.images += image is not None

        def set_figure_frame(self, frame, kind, on_shown, on_fail) -> None:
            before = self.frames[-1] if self.frames else None
            self.frames.append(frame)
            on_shown(frame, before)

    host = QWidget()
    host.resize(320, 240)
    av = quick_surface.QuickSurfaceAvatar(host)
    render = av._render
    if av.control.rhi() is None or av.control.rhi().backendName() != "OpenGL":
        host.deleteLater()
        pytest.skip("shared frames are tested on OpenGL here")
    av.surface = surface = Surface()
    av._share_kind = "gl"
    render.share("gl")
    reads = []
    real = render._queue_readback
    render._queue_readback = lambda: (reads.append(1), real())[1]
    av.setGeometry(0, 0, 320, 240)
    host.show()
    for _ in range(200):
        av._request()
        if len({f.seq for f in surface.frames}) >= 4:
            break
        QTest.qWait(25)
    seqs = [f.seq for f in surface.frames]
    av._fail("test over")
    host.close()
    host.deleteLater()
    assert render.share_failed is None
    assert len(set(seqs)) >= 4 and seqs == sorted(seqs)
    assert len({f.index for f in surface.frames}) >= 2  # the ring turns over
    assert reads == [] and surface.images == 0
