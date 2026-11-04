"""She takes her speaking pose when the reply starts streaming and leaves it when the turn ends."""

from __future__ import annotations

from arelis.core.events import Event, EventType
from arelis.ui.event_host import dispatch_event


def test_streaming_reply_is_speaking_then_done(arelis_window, qt_app) -> None:
    w = arelis_window({"ui": {"default_width": 1200, "default_height": 800, "theme": "sodium"}})
    w.show()
    qt_app.processEvents()
    w._set_busy(True)
    assert w.persona_panel._state == "thinking"
    dispatch_event(w, Event(EventType.ASSISTANT_DELTA, {"text": "The sky "}))
    dispatch_event(w, Event(EventType.ASSISTANT_DELTA, {"text": "is blue."}))
    assert w.persona_panel._state == "speaking"
    dispatch_event(w, Event(EventType.ASSISTANT_DONE, {"text": "The sky is blue."}))
    assert w.persona_panel._state == "done"
