"""Her page waits for the layout to settle before it takes a size.

On the switch into Filament the title bar drops from 40 to 32 px after her
panel has already moved, and that step reaches her through a posted layout
request. The page took the first size on the next turn and then the settled
one: two canvas reallocations (280x467, then 313x534) on the GPU run.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Signal
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget


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


def test_a_posted_layout_step_lands_before_her_page_takes_a_size(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    from arelis.ui.persona_face import PersonaPanel, web_avatar

    monkeypatch.setattr(web_avatar, "unavailable_reason", lambda: None)
    monkeypatch.setattr(web_avatar, "WebAvatar", _FakeScene)
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    bar = QWidget()
    bar.setFixedHeight(40)
    lay.addWidget(bar)
    panel = PersonaPanel()
    lay.addWidget(panel, 1)
    host.resize(300, 600)
    host.show()
    QApplication.processEvents()
    sizes = _Sizes()
    panel.web.installEventFilter(sizes)
    host.resize(313, 640)  # her panel moves now
    bar.setFixedHeight(32)  # the slim title bar: a posted layout step
    for _ in range(5):
        QApplication.processEvents()
    assert panel.height() == 608
    assert len(sizes.seen) == 1
    assert panel.web.size() == panel.loading.size()
