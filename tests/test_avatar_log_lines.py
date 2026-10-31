"""Avatar events land in the app log as ``[avatar] ...`` lines, page console included."""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication


def test_lipsync_and_page_console_log_under_the_avatar_prefix(tmp_path, monkeypatch, caplog) -> None:
    monkeypatch.setenv("ARELIS_AVATAR_GLB", str(tmp_path / "missing.glb"))
    QApplication.instance() or QApplication([])
    from arelis.ui.persona_face import PersonaPanel
    from arelis.ui.persona_face.web_avatar import forward_console

    caplog.set_level(logging.INFO, logger="arelis.avatar")
    panel = PersonaPanel()
    panel.set_state("speaking")
    panel.set_state("done")
    forward_console(0, "[avatar] glb loaded ms=812", 1, "file:///x/aether.js")
    forward_console(2, "boom", 7, "file:///x/anim.js")
    lines = [(r.levelno, r.getMessage()) for r in caplog.records if r.name == "arelis.avatar"]
    assert lines == [
        (logging.INFO, "[avatar] unavailable reason='no model at " + str(tmp_path / "missing.glb") + "'"),
        (logging.INFO, "[avatar] lipsync start"),
        (logging.INFO, "[avatar] lipsync stop"),
        (logging.INFO, "[avatar] glb loaded ms=812"),
        (logging.ERROR, "[avatar] js boom (anim.js:7)"),
    ]
