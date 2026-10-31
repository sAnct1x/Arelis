"""A native resize of her window rebuilds the view surface once it settles.

Babbage, 89751d3: in Filament she was blank after a restore to 1100x800 and
after the later resize small (180x268) while the same size drew fine in q5:
the hub view was in place and frames ran, but nothing reached the screen.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget


class _Scene(QWidget):
    ready = Signal()
    failed = Signal(str)
    rearms = 0

    def rearm_surface(self) -> None:
        _Scene.rearms += 1

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


def test_her_surface_is_rearmed_once_after_a_window_resize(arelis_window, monkeypatch) -> None:
    from arelis.ui.persona_face import web_avatar

    monkeypatch.setattr(web_avatar, "unavailable_reason", lambda: None)
    monkeypatch.setattr(web_avatar, "WebAvatar", _Scene)
    w = arelis_window({"ui": {"theme": "filament", "filament_ack": True}})
    w.show()
    QTest.qWait(400)
    _Scene.rearms = 0
    for step in range(3):  # a restore arrives as several native resize steps
        w.resize(1100 - 40 * step, 800 - 30 * step)
        QTest.qWait(20)
    QTest.qWait(400)
    assert _Scene.rearms == 1
