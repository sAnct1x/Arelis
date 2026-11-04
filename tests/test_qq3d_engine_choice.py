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
    assert "[avatar] engine=qq3d source=env room=filament model=" in caplog.text
    assert "unavailable='no model at X'" in caplog.text


def test_avatar_engine_flag_wins_over_env_and_saved_user_variable(monkeypatch) -> None:
    import arelis.login_start as login_start
    from arelis.main import main
    from arelis.ui.persona_face import qq3d_avatar

    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "web")
    monkeypatch.delenv("ARELIS_AVATAR_ENGINE_SOURCE", raising=False)
    monkeypatch.setattr(qq3d_avatar, "_saved_user_env", lambda name: "web", raising=False)
    monkeypatch.setattr(login_start, "remove_login_start", lambda: "ok")
    assert main(["--avatar-engine", "qq3d", "--remove-login-start"]) == 0
    assert qq3d_avatar.engine_choice() == ("qq3d", "flag")


def test_with_no_env_set_the_avatar_quick3d_and_quick_surface_are_the_defaults(monkeypatch):
    from arelis.ui.persona_face import qq3d_avatar, quick_surface

    for name in ("ARELIS_AVATAR_ENGINE", "ARELIS_AVATAR_ENGINE_SOURCE", "ARELIS_SURFACE", "ARELIS_WEB_AVATAR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(qq3d_avatar, "_saved_user_env", lambda name: "", raising=False)
    assert qq3d_avatar.engine_choice() == ("qq3d", "default")
    assert quick_surface.surface_choice() == ("quick", "default")
    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "web")
    assert qq3d_avatar.engine() == "web"
