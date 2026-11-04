"""Her page loads shown and sized under the veil, so Chromium does not hold it back as hidden."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QWidget


class _FakeScene(QWidget):
    ready = Signal()
    failed = Signal(str)

    def set_state(self, state: str) -> None:
        pass

    def set_level(self, level) -> None:
        pass


def test_scene_view_is_shown_at_full_size_before_ready(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    from arelis.ui.persona_face import PersonaPanel, web_avatar

    monkeypatch.setattr(web_avatar, "unavailable_reason", lambda: None)
    monkeypatch.setattr(web_avatar, "WebAvatar", _FakeScene)
    host = QWidget()
    host.resize(400, 700)
    panel = PersonaPanel(host)
    panel.setGeometry(0, 0, 300, 600)
    host.show()
    QApplication.processEvents()

    assert panel.is_loading()
    assert panel.web.isVisible()
    assert panel.web.geometry() == panel.loading.geometry()
    assert panel.web.width() == 300 and panel.web.height() > 300
    kids = panel.children()
    assert kids.index(panel.loading) > kids.index(panel.web)  # the veil stays on top until ready
    host.close()
