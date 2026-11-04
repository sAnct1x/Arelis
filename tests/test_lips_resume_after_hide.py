"""Hidden and shown again mid-reply, her lips keep following the level."""

from __future__ import annotations

from tests.test_scene_loads_visible import _FakeScene


def test_lip_timer_restarts_when_shown_mid_reply(qt_app, monkeypatch) -> None:
    from arelis.ui.persona_face import PersonaPanel, web_avatar

    monkeypatch.setattr(web_avatar, "unavailable_reason", lambda: None)
    monkeypatch.setattr(web_avatar, "WebAvatar", _FakeScene)
    monkeypatch.setattr(_FakeScene, "set_level", lambda self, v: None, raising=False)
    panel = PersonaPanel()
    panel.show()
    panel.set_state("speaking")
    assert panel._level_timer.isActive()
    panel.hide()
    assert not panel._level_timer.isActive()
    panel.show()
    assert panel._level_timer.isActive()
    panel.hide()
