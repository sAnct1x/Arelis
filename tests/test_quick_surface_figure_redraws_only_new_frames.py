"""ARELIS_SURFACE=quick: her figure asks the surface to render only for a new frame.

Her render thread signals the GUI thread again when the surface's draw of her frame frees a
ring slot, with the same frame. Drawing it again asked for another surface render, whose draw
freed a slot again: the window rendered back to back with nothing new, as fast as it could
present (about 91 renders/s on a 180 Hz display, against a 60/s animation tick).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSize, QSizeF
from PySide6.QtTest import QTest


def test_the_same_frame_handed_again_after_its_draw_asks_for_no_render(qt_app, monkeypatch):
    from PySide6.QtGui import (
        QColor,
        QImage,
        QRhiColorAttachment,
        QRhiTexture,
        QRhiTextureRenderTargetDescription,
    )
    from PySide6.QtQuick import QQuickItem, QQuickRenderControl, QQuickRenderTarget, QQuickWindow

    from arelis.ui.persona_face import quick_surface, shared_frame

    if QQuickWindow.sceneGraphBackend() in ("", "software"):
        QQuickWindow.setSceneGraphBackend("rhi")
    control = QQuickRenderControl()
    window = QQuickWindow(control)
    window.resize(64, 64)
    if not control.initialize() or control.rhi() is None:
        pytest.skip("no QRhi for a render control here")
    rhi = control.rhi()
    tex = rhi.newTexture(QRhiTexture.Format.RGBA8, QSize(64, 64), 1, QRhiTexture.Flag.RenderTarget)
    tex.create()
    rt = rhi.newTextureRenderTarget(QRhiTextureRenderTargetDescription(QRhiColorAttachment(tex)))
    rp = rt.newCompatibleRenderPassDescriptor()
    rt.setRenderPassDescriptor(rp)
    rt.create()
    window.setRenderTarget(QQuickRenderTarget.fromRhiRenderTarget(rt))

    class Consumer:  # her shared texture, as a plain one: the surface side is what is tested
        def __init__(self, _kind, win) -> None:
            img = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
            img.fill(QColor("violet"))
            self.tex = win.createTextureFromImage(img)

        def texture(self, _frame):
            return self.tex

        def forget_before(self, _generation) -> None:
            pass

        def close(self) -> None:
            pass

    monkeypatch.setattr(shared_frame, "Consumer", Consumer)
    slot = QQuickItem(window.contentItem())
    slot.setSize(QSizeF(64, 64))
    shown = []
    item = quick_surface._figure_item_class()(
        slot, "gl", lambda frame, before: shown.append(frame), lambda reason: None
    )

    asked = []
    for sig in (control.renderRequested, control.sceneChanged):
        sig.connect(lambda: asked.append(1))

    def frame() -> None:
        control.polishItems()
        control.beginFrame()
        control.sync()
        control.render()
        control.endFrame()

    first = shared_frame.Frame(0, 0, 0, (64, 64), 1, False)
    try:
        item.show(first)
        frame()
        assert shown == [first]  # drawn: her thread is told, and signals back with it
        QTest.qWait(10)
        asked.clear()
        item.show(first)
        assert asked == [], "the same frame asked for another surface render"
        item.show(shared_frame.Frame(0, 1, 0, (64, 64), 2, False))
        assert asked, "a new frame must still ask for a render"
    finally:
        item.close()
        slot.setParentItem(None)
        slot.deleteLater()
        for res in (rt, rp, tex):
            res.destroy()
        window.deleteLater()
        control.deleteLater()
