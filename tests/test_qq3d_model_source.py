"""Where her Quick 3D model comes from: the app's own folder first, the override only as a fallback."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from arelis.ui.persona_face import qq3d_avatar


def _model(folder: Path, tag: str) -> Path:
    (folder / "meshes").mkdir(parents=True)
    (folder / qq3d_avatar.LOOK_FILE).write_text(f"// {tag}\n", encoding="utf-8")
    (folder / "meshes" / "a.mesh").write_text(tag, encoding="utf-8")
    return folder


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    app = tmp_path / "data" / "avatar" / "qq3d"
    monkeypatch.setattr(qq3d_avatar, "user_data_dir", lambda: tmp_path / "data")
    monkeypatch.delenv(qq3d_avatar.DIR_ENV, raising=False)
    monkeypatch.setattr(qq3d_avatar, "_saved_user_env", lambda name: "")
    return app, tmp_path / "override"


def test_app_folder_model_wins_over_the_override(dirs, monkeypatch) -> None:
    app, other = dirs
    _model(app, "app")
    monkeypatch.setenv(qq3d_avatar.DIR_ENV, str(_model(other, "override")))
    assert qq3d_avatar.model_source() == ("app", app)
    assert qq3d_avatar.model_path() == app / qq3d_avatar.LOOK_FILE


def test_saved_user_variable_is_the_override_when_the_process_env_has_none(dirs, monkeypatch) -> None:
    _app, other = dirs
    _model(other, "override")
    monkeypatch.setattr(
        qq3d_avatar, "_saved_user_env", lambda name: str(other) if name == qq3d_avatar.DIR_ENV else ""
    )
    assert qq3d_avatar.model_source() == ("override", other)


def test_override_model_is_copied_into_the_app_folder(dirs, monkeypatch) -> None:
    app, other = dirs
    _model(other, "override")
    app.mkdir(parents=True)
    (app / "pipeline.cache").write_text("keep", encoding="utf-8")
    monkeypatch.setenv(qq3d_avatar.DIR_ENV, str(other))
    assert qq3d_avatar.install_model() == app
    assert (app / "meshes" / "a.mesh").read_text(encoding="utf-8") == "override"
    assert (app / "pipeline.cache").read_text(encoding="utf-8") == "keep"
    assert qq3d_avatar.model_source() == ("app", app)


def test_startup_line_says_where_the_model_came_from(dirs, monkeypatch, caplog) -> None:
    _app, other = dirs
    monkeypatch.setenv(qq3d_avatar.DIR_ENV, str(_model(other, "override")))
    monkeypatch.setenv("ARELIS_AVATAR_ENGINE", "qq3d")
    monkeypatch.delenv("ARELIS_AVATAR_ENGINE_SOURCE", raising=False)
    monkeypatch.setattr(qq3d_avatar, "unavailable_reason", lambda: "x")
    with caplog.at_level(logging.INFO, logger="arelis.avatar"):
        qq3d_avatar.log_engine_choice("filament")
    assert f"model=override dir={str(other)!r}" in caplog.text
