"""ARELIS_SURFACE=quick: the window builds one Quick surface and her readback path never runs."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from PySide6.QtTest import QTest


def test_flag_on_builds_one_quick_surface_without_readback(qt_app, monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_SURFACE", "quick")
    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "qq3d")
    from PySide6.QtQuickWidgets import QQuickWidget

    from arelis.ui.persona_face import qq3d_avatar
    from arelis.ui.persona_face.panel import PersonaPanel

    if qq3d_avatar.unavailable_reason():
        pytest.skip(qq3d_avatar.unavailable_reason())
    readback = []
    monkeypatch.setattr(qq3d_avatar._RenderThread, "frame", lambda *a: readback.append(a))
    monkeypatch.setattr(qq3d_avatar._RenderThread, "initialize", lambda *a: readback.append(a))
    monkeypatch.setattr(qq3d_avatar, "wanted", lambda theme=None: True)

    from arelis.ui.app import ArelisWindow

    bridge = Mock()
    win = ArelisWindow({"ui": {}}, bridge, None, Mock())
    win.resize(900, 600)
    win.show()
    panel = win.persona_panel
    assert isinstance(panel, PersonaPanel)
    host = panel.web
    seen = []  # the breathing loading state holds her slot until her scene is ready
    for _ in range(60):
        surface = getattr(host, "surface", None)
        quick_root = surface.rootObject() if surface is not None else None
        if quick_root is not None:
            seen.append(quick_root.property("loading"))
        if host is not None and host.is_ready():
            break
        QTest.qWait(100)
    assert host.is_ready(), "her scene on the surface never reported ready"
    surfaces = win.findChildren(QQuickWidget)
    assert len(surfaces) == 1 and surfaces[0].parentWidget() is win
    assert win.children().index(surfaces[0]) <= min(
        win.children().index(c) for c in win.findChildren(type(win.stage)) if c.parentWidget() is win
    )
    assert host.root is not None and host.root.parentItem().objectName() == "avatarSlot"
    QTest.qWait(200)
    assert True in seen and surfaces[0].rootObject().property("loading") is False, seen
    host.set_state("speaking")
    assert host.root.property("speaking") is True
    assert readback == []
    win.hide()


def test_night_backdrop_is_drawn_by_the_surface(qt_app, monkeypatch) -> None:
    """Qt punches a QQuickWidget's rect out of the window's own paint: the room must be on it."""
    monkeypatch.setenv("ARELIS_SURFACE", "quick")
    from PySide6.QtQuickWidgets import QQuickWidget

    from arelis.ui.app import ArelisWindow
    from arelis.ui.theme import apply_theme

    win = ArelisWindow({"ui": {}}, Mock(), None, Mock())
    win.resize(900, 600)
    win.show()
    apply_theme("night")
    surface = win.findChildren(QQuickWidget)[0]
    QTest.qWait(300)
    win.repaint()
    QTest.qWait(300)
    # Offscreen Qt has no QRhi to render the surface, so read what it was given to draw.
    source = surface.rootObject().property("backdropSource")
    win.hide()
    apply_theme("sodium")
    assert source.startswith("image://")
    shot = surface.engine().imageProvider("arelisorbit").requestImage(
        source.split("//", 1)[1].split("/", 1)[1], None, None
    )
    px = shot.pixelColor(shot.width() // 2, shot.height() // 2)
    assert px.alpha() == 255 and (px.red(), px.green(), px.blue()) != (0, 0, 0)


def test_frametime_log_records_surface_frames(qt_app, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ARELIS_SURFACE", "quick")
    path = tmp_path / "frames.csv"
    monkeypatch.setenv("ARELIS_FRAMETIME_LOG", str(path))
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face import quick_surface

    win = QWidget()
    surface = quick_surface.surface_for(win)
    for _ in range(3):  # offscreen Qt has no QRhi, so stand in for three rendered frames
        surface.quickWindow().afterRendering.emit()
    import shiboken6

    shiboken6.delete(surface)  # the log closes with its surface
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all(float(v) >= 0 for v in lines[0].split(","))


def test_the_cropped_overlay_is_placed_at_its_offset(qt_app, monkeypatch) -> None:
    """The worker's overlay covers only its box: the surface puts it there, not over the window."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QWidget

    from arelis.ui.persona_face.quick_surface import _quick_widget_class

    host = QWidget()
    host.resize(800, 500)
    s = _quick_widget_class()(host)
    s.resize(800, 500)
    host.show()
    QTest.qWait(100)
    img = QImage(400, 200, QImage.Format.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(2.0)
    img.setOffset(QPoint(120, 60))
    img.fill(0)
    s.set_orbit(img)
    r = s.rootObject().property("orbitRect")
    assert (r.x(), r.y(), r.width(), r.height()) == (120, 60, 200, 100)
    host.hide()


def test_her_view_has_its_camera_so_the_chest_strand_does_not_warn() -> None:
    """mapFrom3DScene (the chest strand, each frame) warns every call unless the View3D has a camera."""
    import re
    from pathlib import Path

    import arelis.ui.persona_face as pf

    src = (Path(pf.__file__).parent / "qq3d" / "Avatar.qml").read_text(encoding="utf-8")
    view = src[src.index("View3D {"):]
    assert re.search(r"^\s*camera:\s*cam\s*$", view, re.M)
