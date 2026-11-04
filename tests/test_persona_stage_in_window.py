"""Her base-UI place exists in the window: on the stage, click-through, in her band, under the chat."""

from __future__ import annotations

from PySide6.QtCore import Qt

from arelis.ui.persona_stage import persona_region


def test_window_builds_her_stage_in_the_right_band(arelis_window, qt_app) -> None:
    w = arelis_window({"ui": {"default_width": 1200, "default_height": 800, "theme": "night"}})
    w.show()
    qt_app.processEvents()
    ps = w.persona_stage
    assert ps.parentWidget() is w.stage
    assert ps.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert ps.geometry() == persona_region(w.stage.rect())
    kids = w.stage.children()
    assert kids.index(ps) < kids.index(w.conversation)
