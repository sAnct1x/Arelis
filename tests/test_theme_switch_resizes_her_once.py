"""Her page takes one size per settled layout, not one per step on the way.

A theme switch hides the chrome bars one at a time, so her panel stepped through
three sizes in one switch and the page reallocated its canvas for each: a 116 ms
frame right after the switch into Filament on the GPU run.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget


class _FakeScene(QWidget):
    ready = Signal()
    failed = Signal(str)

    def set_state(self, state: str) -> None:
        pass

    def set_level(self, level) -> None:
        pass


class _Sizes(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.seen = []

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.Resize:
            self.seen.append(obj.size())
        return False


def test_steps_in_one_switch_resize_her_page_once(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    from arelis.ui.persona_face import PersonaPanel, web_avatar

    monkeypatch.setattr(web_avatar, "unavailable_reason", lambda: None)
    monkeypatch.setattr(web_avatar, "WebAvatar", _FakeScene)
    host = QWidget()
    host.resize(400, 800)
    panel = PersonaPanel(host)
    panel.setGeometry(0, 0, 278, 555)
    host.show()
    QApplication.processEvents()
    sizes = _Sizes()
    panel.web.installEventFilter(sizes)
    for w, h in ((300, 600), (313, 626)):  # the steps Babbage logged in one switch
        panel.setGeometry(0, 0, w, h)
    QApplication.processEvents()
    assert len(sizes.seen) == 1
    assert panel.web.size() == panel.loading.size()
    assert panel.web.width() == 313
