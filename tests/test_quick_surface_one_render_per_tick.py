"""ARELIS_SURFACE=quick: a frame of the animating orbit asks for no second frame.

The window's surface is a QQuickWidget: it renders on the GUI thread, and a render
requested while it renders is a whole second render and composite 5 ms later. Fiber
caches regrabbed every frame asked for one each frame, so the surface rendered twice per tick.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, QSize, QSizeF, QUrl
from PySide6.QtTest import QTest


def test_rendering_an_animating_orbit_frame_requests_no_extra_frame(qt_app) -> None:
    from PySide6.QtGui import (
        QRhiColorAttachment,
        QRhiTexture,
        QRhiTextureRenderTargetDescription,
    )
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuick import QQuickRenderControl, QQuickRenderTarget, QQuickWindow

    from arelis.ui.filament_field import FilamentField
    from arelis.ui.persona_face.orbit_state import OrbitState
    from arelis.ui.persona_face.quick_surface import SURFACE_QML

    if QQuickWindow.sceneGraphBackend() in ("", "software"):
        QQuickWindow.setSceneGraphBackend("rhi")
    control = QQuickRenderControl()
    window = QQuickWindow(control)
    window.resize(480, 320)
    if not control.initialize() or control.rhi() is None:
        pytest.skip("no QRhi for a render control here")
    rhi = control.rhi()
    tex = rhi.newTexture(QRhiTexture.Format.RGBA8, QSize(480, 320), 1,
                         QRhiTexture.Flag.RenderTarget)
    tex.create()
    rt = rhi.newTextureRenderTarget(QRhiTextureRenderTargetDescription(QRhiColorAttachment(tex)))
    rp = rt.newCompatibleRenderPassDescriptor()
    rt.setRenderPassDescriptor(rp)
    rt.create()
    window.setRenderTarget(QQuickRenderTarget.fromRhiRenderTarget(rt))

    engine = QQmlEngine()
    state = OrbitState()
    state.update(FilamentField(), QRect(0, 0, 480, 320), now=0.0)
    state.set_active(True)
    engine.rootContext().setContextProperty("orbitState", state)
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(SURFACE_QML)))
    root = component.create()
    assert root is not None, [e.toString() for e in component.errors()]
    root.setParentItem(window.contentItem())
    root.setSize(QSizeF(480, 320))  # an unshown window gets no resize event

    in_frame = [False]
    asked = []
    for sig in (control.renderRequested, control.sceneChanged):
        sig.connect(lambda: asked.append(1) if in_frame[0] else None)

    def frame() -> None:
        in_frame[0] = True
        control.polishItems()
        control.beginFrame()
        control.sync()
        control.render()
        control.endFrame()
        in_frame[0] = False

    try:
        for _ in range(4):  # first frames build pipelines and fill the scene
            QTest.qWait(20)
            frame()
        asked.clear()
        for _ in range(12):  # each wait lets the orbit's animation tick
            QTest.qWait(20)
            frame()
        assert asked == [], f"{len(asked)} extra frames asked for in 12 frames"
    finally:
        root.setParentItem(None)
        root.deleteLater()
        for res in (rt, rp, tex):
            res.destroy()
        window.deleteLater()
        control.deleteLater()
