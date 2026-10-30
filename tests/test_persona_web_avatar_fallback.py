"""With no avatar model on disk the panel keeps the painted face."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from arelis.ui.persona_face import PersonaPanel


def test_missing_glb_keeps_painted_face(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARELIS_AVATAR_GLB", str(tmp_path / "ellah.glb"))
    QApplication.instance() or QApplication([])
    panel = PersonaPanel()
    assert panel.web is None
    assert "no model" in (panel.web_avatar_reason or "")
    assert not panel.avatar.isHidden()
    panel.set_state("speaking")
    panel.set_listening(True)
    panel.tick()
    assert panel.caption_text() == "speaking"
