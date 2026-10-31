"""After a switch into Filament her page is told to fit and draw at the settled size.

Babbage, 9434a47: the hub view was 313x534 and frames ran, but she was not
drawn in 5 of 8 Filament shots. The settled placement now always refits.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget


class _Scene(QWidget):
    ready = Signal()
    failed = Signal(str)
    fits: list = []

    def refit(self) -> None:
        _Scene.fits.append(self.size())

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


def test_her_page_refits_at_the_settled_size(arelis_window, monkeypatch) -> None:
    from arelis.ui.persona_face import web_avatar

    monkeypatch.setattr(web_avatar, "unavailable_reason", lambda: None)
    monkeypatch.setattr(web_avatar, "WebAvatar", _Scene)
    w = arelis_window({"ui": {"theme": "night", "filament_ack": True}})
    w.show()
    QTest.qWait(300)
    _Scene.fits.clear()
    w._choose_theme("filament", True)
    QTest.qWait(400)
    web = w.persona_panel.web
    assert _Scene.fits, "no refit after the switch"
    assert _Scene.fits[-1] == web.size()
