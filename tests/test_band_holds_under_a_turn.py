"""Her band holds still through a turn: no resize storm on send, stream and finish."""

from __future__ import annotations

import logging

from arelis.core.events import Event, EventType
from arelis.ui.event_host import dispatch_event


def test_streaming_thoughts_do_not_resize_her_band(arelis_window, qt_app, caplog) -> None:
    w = arelis_window({"ui": {"default_width": 1600, "default_height": 900, "theme": "night"}})
    w.show()
    qt_app.processEvents()
    before = w.persona_stage.geometry()
    caplog.set_level(logging.INFO, logger="arelis.avatar")
    caplog.clear()
    w._set_busy(True)
    for i in range(12):
        dispatch_event(w, Event(EventType.THINKING, {"text": f"step {i} ", "stream": True}))
        qt_app.processEvents()
    w._set_busy(False)
    qt_app.processEvents()
    resizes = [r for r in caplog.records if "[avatar] resize" in r.getMessage()]
    assert [r.getMessage() for r in resizes] == []
    assert w.persona_stage.geometry() == before
