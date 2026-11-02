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
    for _ in range(60):
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
