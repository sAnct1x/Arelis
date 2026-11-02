"""A typed reply has no audio, yet her mouth moves while it streams; voice keeps its audio level."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from arelis.core.events import Event, EventType
from arelis.ui.event_host import dispatch_event
from tests.test_scene_loads_visible import _FakeScene


def test_streamed_text_drives_mouth_and_audio_wins(qt_app, monkeypatch) -> None:
    from arelis.ui.persona_face import PersonaPanel, web_avatar

    levels: list = []
    monkeypatch.setattr(web_avatar, "unavailable_reason", lambda: None)
    monkeypatch.setattr(web_avatar, "WebAvatar", _FakeScene)
    monkeypatch.setattr(_FakeScene, "set_level", lambda self, v: levels.append(v), raising=False)
    now = [10.0]
    panel = PersonaPanel()
    panel.set_clock(lambda: now[0])
    panel.set_state("speaking")
    window = SimpleNamespace(
        _mobile_foreign=False, _assistant_streaming=True, _clear_model_loading=lambda: None,
        conversation=MagicMock(), chat=MagicMock(), persona_panel=panel,
    )
    dispatch_event(window, Event(EventType.ASSISTANT_DELTA, {"text": "Hello there, "}))
    seen = []
    for _ in range(10):
        now[0] += 0.033
        panel._tick_level()
        seen.append(levels[-1])
    assert all(v is not None for v in seen) and max(seen) - min(seen) > 0.15
    now[0] += 1.0  # streaming stopped: the mouth rests
    panel._tick_level()
    assert levels[-1] is None
    panel.note_text("more")
    panel.set_level_source(lambda: 0.7)  # voice audio takes over
    panel._tick_level()
    assert levels[-1] == 0.7
