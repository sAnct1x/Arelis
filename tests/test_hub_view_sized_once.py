"""The switch into Filament gives her view one size: the settled hub.

On Windows, native tile windows pump messages in the middle of the switch, so
the 0 ms placement ran between the hub's steps and the view took 280x467 and
then 313x534 (Babbage, 125b0b4 trace: 17 dropped frames while it resized).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget


class _FakeScene(QWidget):
    ready = Signal()
    failed = Signal(str)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **k: None


class _Sizes(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.seen = []

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.Resize:
            self.seen.append(obj.size())
        return False


def test_switch_into_filament_resizes_her_view_once(arelis_window, qt_app, monkeypatch) -> None:
    from arelis.ui.persona_face import web_avatar

    monkeypatch.setattr(web_avatar, "unavailable_reason", lambda: None)
    monkeypatch.setattr(web_avatar, "WebAvatar", _FakeScene)
    w = arelis_window(
        {"ui": {"theme": "night", "filament_ack": True, "default_width": 1600, "default_height": 1000}}
    )
    w.show()
    QTest.qWait(400)
    face = w._sync_filament_face

    def pumping_face():  # what native tile windows do on Windows
        QApplication.processEvents()
        face()

    w._sync_filament_face = pumping_face
    sizes = _Sizes()
    web = w.persona_panel.web
    web.installEventFilter(sizes)
    w._choose_theme("filament", True)
    QTest.qWait(600)
    assert len(sizes.seen) == 1
    assert web.size() == w.persona_panel.loading.size()
