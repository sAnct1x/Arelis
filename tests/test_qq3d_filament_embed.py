"""ARELIS_AVATAR_ENGINE=qq3d puts the Quick 3D host in Filament and Night; other rooms keep WebEngine."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QWidget


class _Fake(QWidget):
    ready = Signal()
    failed = Signal(str)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


class _Web(_Fake):
    pass


class _QQ3D(_Fake):
    pass


@pytest.mark.parametrize(
    ("engine", "theme", "want"),
    [("qq3d", "filament", _QQ3D), ("", "filament", _Web), ("qq3d", "night", _QQ3D), ("qq3d", "sodium", _Web)],
)
def test_engine_switch_picks_quick3d_only_in_its_rooms(monkeypatch, engine, theme, want) -> None:
    QApplication.instance() or QApplication([])
    from arelis.ui import theme_tokens
    from arelis.ui.persona_face import PersonaPanel, qq3d_avatar, web_avatar

    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", engine)
    monkeypatch.setattr(theme_tokens, "active_theme", lambda: theme)
    for mod in (web_avatar, qq3d_avatar):
        monkeypatch.setattr(mod, "unavailable_reason", lambda: None)
    monkeypatch.setattr(web_avatar, "WebAvatar", _Web)
    monkeypatch.setattr(qq3d_avatar, "QQ3DAvatar", _QQ3D)
    panel = PersonaPanel()
    assert type(panel.web) is want


def test_quick3d_engine_asks_for_an_alpha_surface(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    from PySide6.QtGui import QSurfaceFormat

    from arelis.ui.persona_face.qq3d_avatar import surface_format

    before = QSurfaceFormat.defaultFormat()
    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "")
    assert surface_format() is None
    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "qq3d")
    surface_format()
    try:
        assert QSurfaceFormat.defaultFormat().alphaBufferSize() == 8
    finally:
        QSurfaceFormat.setDefaultFormat(before)


def test_theme_switch_swaps_the_host(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    from arelis.ui import theme_tokens
    from arelis.ui.persona_face import PersonaPanel, qq3d_avatar, web_avatar

    room = {"name": "sodium"}
    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "qq3d")
    monkeypatch.setattr(theme_tokens, "active_theme", lambda: room["name"])
    for mod in (web_avatar, qq3d_avatar):
        monkeypatch.setattr(mod, "unavailable_reason", lambda: None)
    monkeypatch.setattr(web_avatar, "WebAvatar", _Web)
    monkeypatch.setattr(qq3d_avatar, "QQ3DAvatar", _QQ3D)
    panel = PersonaPanel()
    assert type(panel.web) is _Web
    room["name"] = "filament"
    panel.refresh_theme_icons()
    assert type(panel.web) is _QQ3D
    host = panel.web
    room["name"] = "night"
    panel.refresh_theme_icons()
    assert panel.web is host
    room["name"] = "sodium"
    panel.refresh_theme_icons()
    assert type(panel.web) is _Web
