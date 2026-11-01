"""Which host draws her, and the startup line that says why."""

from __future__ import annotations

import logging


def test_saved_user_variable_picks_quick3d_when_the_launcher_env_is_stale(monkeypatch) -> None:
    from arelis.ui.persona_face import qq3d_avatar

    monkeypatch.delenv("ARELIS_AVATAR_ENGINE", raising=False)
    monkeypatch.delenv("ARELIS_AVATAR_ENGINE_SOURCE", raising=False)
    monkeypatch.setattr(qq3d_avatar, "_saved_user_env", lambda name: "qq3d", raising=False)
    assert qq3d_avatar.wanted("filament")


def test_startup_line_names_engine_source_and_fallback(monkeypatch, caplog) -> None:
    from arelis.ui.persona_face import qq3d_avatar

    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "qq3d")
    monkeypatch.delenv("ARELIS_AVATAR_ENGINE_SOURCE", raising=False)
    monkeypatch.setattr(qq3d_avatar, "unavailable_reason", lambda: "no model at X")
    with caplog.at_level(logging.INFO, logger="arelis.avatar"):
        qq3d_avatar.log_engine_choice("filament")
    assert "[avatar] engine=qq3d source=env room=filament unavailable='no model at X'" in caplog.text
